"""Concurrency hardening regression tests.

REL-02 — SQLite WAL + busy_timeout: concurrent writers must not raise
``sqlite3.OperationalError: database is locked``.

REL-03 — a lock around SessionManager.get_or_create_session_id: concurrent
same-user calls must yield exactly one session id (no duplicate sessions).

U-04 / R-16 — RAG in-memory indices: in-place clear/rebuild during iteration
could mix generations in one retrieve (not always RuntimeError). Indices are
copy-on-write: one retrieval must observe a single published generation.
"""

from __future__ import annotations

import sqlite3
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from app.memory.session import SessionManager
from app.memory.store import MemoryStore
from app.rag.ingest import DocumentChunk
from app.rag import retriever as rag


def _gen_chunk(generation: str, i: int) -> DocumentChunk:
    text = (
        f"coaching {generation} topic{i} session accountability "
        f"growth mindset practice reflection"
    )
    return DocumentChunk(
        chunk_id=f"{generation}:{i}",
        source_path=f"/tmp/{generation}/{i}.md",
        text=text,
        start_token=0,
        end_token=len(text.split()),
        corpus="framework",
        chunk_role="general",
    )


def _load_generation(generation: str, n: int) -> None:
    rag.index_chunks(
        [_gen_chunk(generation, i) for i in range(n)],
        reset=True,
        embed=False,
        corpus="framework",
    )


def _generations(chunk_ids: list[str]) -> set[str]:
    return {cid.split(":", 1)[0] for cid in chunk_ids}


class SqliteConcurrentWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._dir = tempfile.TemporaryDirectory()
        self.store = MemoryStore(f"{self._dir.name}/concurrency.db")

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_concurrent_writers_do_not_lock(self) -> None:
        self.store.upsert_user("coach", is_coach=True)
        session_id = self.store.create_session("coach")

        errors: list[Exception] = []
        barrier = threading.Barrier(8)

        def writer(worker: int) -> None:
            barrier.wait()  # release all writers simultaneously
            try:
                for i in range(25):
                    self.store.add_message(session_id, "user", f"w{worker}-{i}")
            except sqlite3.OperationalError as exc:  # pragma: no cover - failure path
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(writer, range(8)))

        self.assertEqual(errors, [], f"writers hit lock errors: {errors}")
        self.assertEqual(len(self.store.get_session_messages(session_id)), 8 * 25)

    def test_wal_mode_enabled(self) -> None:
        conn = self.store._connect()
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(mode.lower(), "wal")


class SessionManagerConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._dir = tempfile.TemporaryDirectory()
        self.store = MemoryStore(f"{self._dir.name}/sessions.db")
        self.manager = SessionManager(self.store)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_concurrent_same_user_yields_single_session(self) -> None:
        barrier = threading.Barrier(16)

        def get_session(_: int) -> str:
            barrier.wait()
            return self.manager.get_or_create_session_id("coach-1")

        with ThreadPoolExecutor(max_workers=16) as pool:
            ids = list(pool.map(get_session, range(16)))

        self.assertEqual(len(set(ids)), 1, f"multiple sessions created: {set(ids)}")
        # And the store must hold exactly one session row for the user.
        conn = self.store._connect()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE user_id = ?", ("coach-1",)
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 1)


class RagIndexConcurrencyTests(unittest.TestCase):
    """U-04: one retrieve must not observe a torn clear/rebuild generation."""

    def setUp(self) -> None:
        rag.clear_index()

    def tearDown(self) -> None:
        rag.clear_index()

    def test_in_place_clear_rebuild_mixes_generations(self) -> None:
        """Characterize pre-COW failure mode: in-place mutate mid-iteration.

        CPython list iterators do not always raise RuntimeError; clear+extend
        during iteration yields a torn view mixing old and new items. This
        documents the invariant we enforce via copy-on-write publish.
        """
        xs = [f"A:{i}" for i in range(40)]
        seen: list[str] = []
        for i, item in enumerate(xs):
            seen.append(item.split(":")[0])
            if i == 9:
                xs.clear()
                xs.extend(f"B:{j}" for j in range(30))
        gens = set(seen)
        self.assertEqual(gens, {"A", "B"}, f"expected mixed gens, got {gens} from {seen}")

    def test_reindex_during_retrieve_keeps_snapshot_generation(self) -> None:
        """Forced interleaving: snapshot A, publish B, score still sees only A."""
        _load_generation("A", 120)
        barrier = threading.Barrier(2)
        hit_ids: list[str] = []
        errors: list[BaseException] = []

        real_snapshot = rag._snapshot_index
        pause_next = threading.Event()
        pause_next.set()

        def snapshot_then_yield_to_reindex(corpus: rag.CorpusKind):
            snap = real_snapshot(corpus)
            # Pause once (first snapshot in retrieve) so reindex can publish B
            # while this call still holds generation A's list reference.
            if pause_next.is_set():
                pause_next.clear()
                barrier.wait()
                barrier.wait()
            return snap

        def reader() -> None:
            try:
                with patch.object(
                    rag, "_snapshot_index", side_effect=snapshot_then_yield_to_reindex
                ):
                    hits = rag.retrieve(
                        "coaching session accountability growth",
                        top_k=40,
                        min_score=0.0,
                        backend="token",
                    )
                hit_ids.extend(h.chunk_id for h in hits)
            except BaseException as exc:  # pragma: no cover - failure path
                errors.append(exc)

        def writer() -> None:
            barrier.wait()
            _load_generation("B", 80)
            barrier.wait()

        t_read = threading.Thread(target=reader)
        t_write = threading.Thread(target=writer)
        t_read.start()
        t_write.start()
        t_read.join()
        t_write.join()

        self.assertEqual(errors, [], f"retrieve raised: {errors}")
        self.assertTrue(hit_ids, "expected retrieval hits from generation A")
        self.assertEqual(_generations(hit_ids), {"A"})
        self.assertEqual(
            _generations([c.chunk.chunk_id for c in rag._framework_index]),
            {"B"},
        )

    def test_concurrent_reindex_and_retrieve_never_mix_generations(self) -> None:
        _load_generation("A", 100)
        stop = threading.Event()
        mixed: list[set[str]] = []
        errors: list[BaseException] = []
        lock = threading.Lock()

        def reader_loop() -> None:
            while not stop.is_set():
                try:
                    hits = rag.retrieve(
                        "coaching session accountability growth mindset",
                        top_k=25,
                        min_score=0.0,
                        backend="token",
                    )
                except BaseException as exc:  # pragma: no cover
                    with lock:
                        errors.append(exc)
                    return
                gens = _generations([h.chunk_id for h in hits])
                if len(gens) > 1:
                    with lock:
                        mixed.append(gens)
                    return

        def writer_loop() -> None:
            toggle = False
            while not stop.is_set():
                toggle = not toggle
                _load_generation("B" if toggle else "A", 60 if toggle else 100)

        readers = [threading.Thread(target=reader_loop) for _ in range(4)]
        writers = [threading.Thread(target=writer_loop) for _ in range(2)]
        for t in readers + writers:
            t.start()
        threading.Event().wait(0.4)
        stop.set()
        for t in readers + writers:
            t.join(timeout=5)

        self.assertEqual(errors, [], f"retrieve errors: {errors}")
        self.assertEqual(mixed, [], f"mixed generations observed: {mixed}")
        # Final index must itself be a single generation.
        final_gens = _generations([c.chunk.chunk_id for c in rag._framework_index])
        self.assertLessEqual(len(final_gens), 1, f"final index mixed: {final_gens}")


if __name__ == "__main__":
    unittest.main()
