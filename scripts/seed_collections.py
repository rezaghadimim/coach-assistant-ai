"""Seed famous-coach video collections and re-index the RAG store.

Demo transcripts live under ``data/knowledge/collections/`` (VTT files as if
extracted from embedded expert videos). Run:

    python3 scripts/seed_collections.py
    python3 scripts/seed_collections.py --ingest
    python3 scripts/seed_collections.py --ingest --no-embed   # token/TF only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.core.embed_providers import embed_profile_for_corpus
from app.core.embeddings import probe_embed_model
from app.knowledge.ingest import ingest_collection_chunks_from_disk
from app.knowledge.store import KnowledgeStore


def _resolve_embed(*, no_embed: bool) -> bool:
    """Match main.py startup: embed when backend is auto/embedding and provider is up."""
    if no_embed:
        return False
    if settings.rag_backend == "embedding":
        return True
    if settings.rag_backend == "auto":
        return probe_embed_model(corpus="framework")
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo expert video collections")
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="Also rebuild framework + collection RAG indices (same as scripts/ingest.py).",
    )
    parser.add_argument(
        "--no-embed",
        action="store_true",
        help="Skip embedding; index with token/TF similarity only (no Ollama/OpenRouter calls).",
    )
    args = parser.parse_args()

    from app.core.knowledge_paths import collection_dirs

    roots = collection_dirs()
    if not roots:
        print(f"No collections directory found (looked for {settings.rag_collections_dir}")
        print(f" and {settings.rag_collections_private_dir}).")
        sys.exit(1)
    print("Collection roots:")
    for root in roots:
        print(f"  - {root}")

    store = KnowledgeStore(settings.memory_db_path)
    # collections_dir=None → ingest + merge every configured root (public + private).
    chunks = ingest_collection_chunks_from_disk(knowledge_store=store)
    collections = store.list_collections()
    print(f"Registered {len(collections)} collection(s), {len(chunks)} chunk(s) from disk.")
    for row in collections:
        print(
            f"  - {row['person_name']} ({row['slug']}): "
            f"{row['source_count']} source(s), {row['chunk_count']} chunk(s)"
        )

    if args.ingest:
        use_embed = _resolve_embed(no_embed=args.no_embed)
        if args.no_embed:
            print("Embedding disabled (--no-embed); using token/TF retrieval.")
        elif use_embed:
            profile = embed_profile_for_corpus("framework")
            print(
                f"Embedding enabled: {profile.provider}/{profile.model.split('/')[-1]} "
                "(framework + collections)"
            )
        else:
            print(
                "Embedding unavailable (Ollama not reachable); "
                "indexing with token/TF similarity only."
            )

        from app.rag.retriever import ingest_and_index_knowledge

        docs, indexed = ingest_and_index_knowledge(
            chunk_size=settings.rag_chunk_size,
            chunk_overlap=settings.rag_chunk_overlap,
            embed=use_embed,
            cache_path=settings.rag_index_cache_path if use_embed else None,
        )
        print(f"Re-indexed {indexed} chunks from {docs} document(s).")
        if use_embed:
            print(
                "Note: occasional 'embed failed for chunk …' warnings are non-fatal; "
                "those chunks still index via token/TF fallback."
            )
    else:
        print("Tip: run with --ingest to load chunks into the in-memory RAG index.")


if __name__ == "__main__":
    main()
