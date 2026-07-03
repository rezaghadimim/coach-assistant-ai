"""Tests for the post-answer expert ideas section (attribution + video time)."""

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.api.chat import reset_runtime_state
from app.rag.expert_ideas import (
    build_expert_ideas,
    format_expert_ideas_markdown,
    timestamped_media_url,
)
from app.rag.retriever import (
    CoachRetrievalResult,
    RetrievedChunk,
    clear_index,
    index_chunks,
)
from app.rag.transcript import build_transcript_chunks, parse_json_transcript
from main import app


def _chunk(**overrides) -> RetrievedChunk:
    base = dict(
        chunk_id="c1",
        source_path="/tmp/video.vtt",
        text="Ask the client who else is affected by the habit before pushing for change.",
        score=0.9,
        collection_id="cid-a",
        person_name="Marshall Goldsmith",
        source_title="Feedforward Instead of Feedback",
        source_uri="https://example.com/videos/feedforward",
        start_sec=23.0,
        end_sec=48.0,
        chunk_role="solution",
        corpus="collection",
    )
    base.update(overrides)
    return RetrievedChunk(**base)


class TimestampedMediaUrlTests(unittest.TestCase):
    def test_youtube_url_gets_time_query_param(self) -> None:
        url = timestamped_media_url("https://youtu.be/abc123", 83.4)
        self.assertEqual(url, "https://youtu.be/abc123?t=83")

    def test_youtube_url_with_existing_query_uses_ampersand(self) -> None:
        url = timestamped_media_url("https://www.youtube.com/watch?v=abc", 60.0)
        self.assertEqual(url, "https://www.youtube.com/watch?v=abc&t=60")

    def test_generic_http_url_gets_media_fragment(self) -> None:
        url = timestamped_media_url("https://example.com/talk.mp4", 23.0)
        self.assertEqual(url, "https://example.com/talk.mp4#t=23")

    def test_local_path_returns_none(self) -> None:
        self.assertIsNone(timestamped_media_url("/data/videos/talk.mp4", 23.0))
        self.assertIsNone(timestamped_media_url("", 23.0))
        self.assertIsNone(timestamped_media_url(None, 23.0))

    def test_zero_start_returns_plain_url(self) -> None:
        url = timestamped_media_url("https://example.com/talk.mp4", 0.0)
        self.assertEqual(url, "https://example.com/talk.mp4")


class ParseJsonTranscriptTests(unittest.TestCase):
    def test_whisper_style_segments(self) -> None:
        payload = (
            '{"segments": ['
            '{"start": 1.5, "end": 4.0, "text": "First idea."},'
            '{"start": 5.0, "end": 9.0, "text": "Second idea."}'
            "]}"
        )
        segments = parse_json_transcript(payload)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].text, "First idea.")
        self.assertEqual(segments[0].start_sec, 1.5)
        self.assertEqual(segments[1].end_sec, 9.0)

    def test_chat_message_export_with_timestamps(self) -> None:
        payload = (
            '{"messages": ['
            '{"time": 12, "message": "Welcome to the session."},'
            '{"time": 30, "message": "Try the feedforward exercise."}'
            "]}"
        )
        segments = parse_json_transcript(payload)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[1].text, "Try the feedforward exercise.")
        self.assertEqual(segments[1].start_sec, 30.0)
        # End defaults to start when the export has one time per message.
        self.assertEqual(segments[1].end_sec, 30.0)

    def test_bare_list_and_junk_items(self) -> None:
        payload = '[{"start": 0, "end": 2, "text": "Hello"}, {"nope": 1}, "junk"]'
        segments = parse_json_transcript(payload)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].text, "Hello")

    def test_json_segments_feed_transcript_chunks_with_timing(self) -> None:
        segments = parse_json_transcript(
            '{"segments": [{"start": 10, "end": 15, "text": "How to handle resistance."}]}'
        )
        chunks = build_transcript_chunks(
            segments,
            source_path="/tmp/talk.json",
            chunk_id_prefix="jane/talk",
            collection_id="cid",
            collection_slug="jane",
            person_name="Jane Doe",
            source_title="Handling resistance",
            source_uri="https://example.com/talk",
            embed_profile_id="ollama/multilingual-e5-small",
            chunk_size=20,
            chunk_overlap=5,
        )
        self.assertTrue(chunks)
        self.assertEqual(chunks[0].start_sec, 10.0)
        self.assertEqual(chunks[0].source_uri, "https://example.com/talk")


class BuildExpertIdeasTests(unittest.TestCase):
    def test_one_idea_per_person_with_timestamp_and_link(self) -> None:
        result = CoachRetrievalResult(
            problem_chunks=[],
            expert_chunks=[
                _chunk(),
                _chunk(chunk_id="c2", score=0.8),  # same person → skipped
                _chunk(
                    chunk_id="c3",
                    collection_id="cid-b",
                    person_name="John Whitmore",
                    source_title="GROW Model in Practice",
                    source_uri="https://youtu.be/grow42",
                    start_sec=95.0,
                    end_sec=120.0,
                    score=0.7,
                ),
            ],
        )
        ideas = build_expert_ideas(result)
        self.assertEqual(len(ideas), 2)
        self.assertEqual(ideas[0].person_name, "Marshall Goldsmith")
        self.assertEqual(ideas[0].timestamp, "00:23–00:48")
        self.assertEqual(ideas[0].video_url, "https://example.com/videos/feedforward#t=23")
        self.assertEqual(ideas[1].person_name, "John Whitmore")
        self.assertEqual(ideas[1].video_url, "https://youtu.be/grow42?t=95")

    def test_untimed_text_source_omits_timestamp(self) -> None:
        result = CoachRetrievalResult(
            problem_chunks=[],
            expert_chunks=[_chunk(start_sec=0.0, end_sec=0.0, source_uri=None)],
        )
        ideas = build_expert_ideas(result)
        self.assertEqual(ideas[0].timestamp, "")
        self.assertIsNone(ideas[0].video_url)

    def test_falls_back_to_attributed_problem_chunks(self) -> None:
        result = CoachRetrievalResult(problem_chunks=[_chunk()], expert_chunks=[])
        ideas = build_expert_ideas(result)
        self.assertEqual(len(ideas), 1)

    def test_excerpt_is_truncated(self) -> None:
        long_text = " ".join(f"word{i}" for i in range(200))
        result = CoachRetrievalResult(
            problem_chunks=[], expert_chunks=[_chunk(text=long_text)]
        )
        ideas = build_expert_ideas(result, excerpt_words=10)
        self.assertTrue(ideas[0].excerpt.endswith("…"))
        self.assertEqual(len(ideas[0].excerpt.split()), 10)

    def test_markdown_formatting(self) -> None:
        ideas = build_expert_ideas(
            CoachRetrievalResult(problem_chunks=[], expert_chunks=[_chunk()])
        )
        text = format_expert_ideas_markdown(ideas)
        self.assertIn("**Marshall Goldsmith**", text)
        self.assertIn('"Feedforward Instead of Feedback"', text)
        self.assertIn("video 00:23–00:48", text)
        self.assertIn("(https://example.com/videos/feedforward#t=23)", text)
        self.assertEqual(format_expert_ideas_markdown([]), "")


class ChatAttachesExpertIdeasTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_state()
        clear_index()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        clear_index()

    def _index_expert_chunks(self) -> None:
        from app.rag.ingest import DocumentChunk

        chunks = [
            DocumentChunk(
                chunk_id="marshall/feedforward:0",
                source_path="/tmp/feedforward.vtt",
                text=(
                    "Solution technique for a client who resists feedback: "
                    "try the feedforward exercise and ask for two suggestions "
                    "for the future."
                ),
                start_token=0,
                end_token=25,
                collection_id="cid-a",
                collection_slug="marshall-goldsmith",
                person_name="Marshall Goldsmith",
                source_title="Feedforward Instead of Feedback",
                source_uri="https://example.com/videos/feedforward",
                start_sec=23.0,
                end_sec=48.0,
                corpus="collection",
                chunk_role="solution",
            ),
            DocumentChunk(
                chunk_id="whitmore/grow:0",
                source_path="/tmp/grow.vtt",
                text=(
                    "Approach for client resistance to feedback: use GROW reality "
                    "questions so the client examines the situation without judgment."
                ),
                start_token=0,
                end_token=25,
                collection_id="cid-b",
                collection_slug="john-whitmore",
                person_name="John Whitmore",
                source_title="GROW Model in Practice",
                source_uri="https://youtu.be/grow42",
                start_sec=95.0,
                end_sec=120.0,
                corpus="collection",
                chunk_role="solution",
            ),
        ]
        index_chunks(chunks, reset=True, corpus="collection")

    def test_chat_reply_gets_ideas_section_with_video_times(self) -> None:
        self._index_expert_chunks()
        with (
            patch("app.core.config.settings.rag_rerank_enabled", False),
            patch(
                "app.api.chat.generate_response",
                new=AsyncMock(return_value="Here is my coaching advice."),
            ),
        ):
            response = self.client.post(
                "/api/chat",
                json={
                    "user_id": "ideas-user",
                    "message": (
                        "My client resists feedback in sessions, "
                        "what exercise or approach could help?"
                    ),
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("Here is my coaching advice.", body["reply"])
        self.assertIn("Ideas from your knowledge base", body["reply"])
        self.assertIn("Marshall Goldsmith", body["reply"])
        self.assertIn("John Whitmore", body["reply"])
        self.assertIn("video", body["reply"])

        ideas = body["expert_ideas"]
        self.assertEqual(len(ideas), 2)
        people = {idea["person_name"] for idea in ideas}
        self.assertEqual(people, {"Marshall Goldsmith", "John Whitmore"})
        for idea in ideas:
            self.assertTrue(idea["timestamp"])
            self.assertTrue(idea["video_url"])

    def test_ideas_disabled_via_setting(self) -> None:
        self._index_expert_chunks()
        with (
            patch("app.core.config.settings.rag_rerank_enabled", False),
            patch("app.core.config.settings.rag_attach_expert_ideas", False),
            patch(
                "app.api.chat.generate_response",
                new=AsyncMock(return_value="Here is my coaching advice."),
            ),
        ):
            response = self.client.post(
                "/api/chat",
                json={
                    "user_id": "ideas-user",
                    "message": "My client resists feedback, what could help?",
                },
            )

        body = response.json()
        self.assertNotIn("Ideas from your knowledge base", body["reply"])
        self.assertEqual(body["expert_ideas"], [])


if __name__ == "__main__":
    unittest.main()
