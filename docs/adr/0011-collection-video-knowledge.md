# ADR-0011: Per-Collection Video Knowledge and Two-Phase Coach Retrieval

**Date:** 2026-06-25
**Status:** Accepted

## Context

Coaches need to ground answers in **expert video guides** from multiple people — not only the committed starter/private markdown corpus. Each person's content should be:

- Ingested once (transcripts, local media, or YouTube URLs) and embedded into the RAG index.
- Cited with **who said it**, which guide, and a timestamp when available.
- Searchable **across all experts** so a coach asking about one situation sees related solutions from others.

Constraints:

- The existing RAG stack (in-memory index, Ollama E5 stage-1, fastembed rerank) must remain the default for framework docs.
- Video chunks are embedded **once at ingest** — acceptable to use a cloud embed API (OpenRouter/OpenAI) for batch quality without adding latency to every chat message.
- Embeddings from different models **cannot** be compared with cosine similarity — mixing E5 (384-d) and OpenAI `text-embedding-3-small` (1536-d) in one index would be invalid.

## Decision

### 1. Dual in-memory indices

Extend `app/rag/retriever.py` with two logical corpora:

| Index | Content | Default embed provider |
|-------|---------|------------------------|
| `framework_index` | `starter/` + `private/` docs | Ollama E5 (`RAG_EMBED_PROVIDER`) |
| `collection_index` | Per-person video/transcript chunks | OpenRouter or OpenAI (`RAG_COLLECTION_EMBED_PROVIDER`) |

Each `_IndexedChunk` stores `embed_profile_id`. Query embedding uses the **matching provider per index**; phase-1 results from both indices are merged with **RRF** before reranking.

### 2. Pluggable embedding providers

Add `app/core/embed_providers/` with a stable `EmbedProvider` protocol:

- `ollama.py` — local E5 (default for queries + framework ingest)
- `openrouter.py` — OpenAI-compatible `/v1/embeddings`
- `openai.py` — direct OpenAI API

`app/core/embeddings.py` remains the facade used by RAG and tool routing. Collection ingest batches passages through the collection provider; vectors are cached on disk with keys `{embed_profile_id}::{chunk_id}::{text_hash}`.

### 3. Collection data model and filesystem layout

- SQLite tables in `app/knowledge/store.py`: `knowledge_collections`, `knowledge_sources`, `knowledge_chunks`
- Filesystem: `data/knowledge/collections/{slug}/collection.json` + `sources/{id}/transcript.vtt`
- `app/rag/transcript.py` — SRT/VTT parsing, time-aware chunking
- `app/knowledge/ingest.py` — discover collections, chunk transcripts, sync metadata
- `app/knowledge/jobs.py` — pending `local_media` (ffmpeg + faster-whisper) and `youtube` (yt-dlp + captions or Whisper fallback)

### 4. Two-phase coach retrieval

Replace the single `retrieve()` call in chat/briefing with `retrieve_coach_context()` when `RAG_TWO_PHASE_ENABLED=true`:

1. **Phase 1 — Problem alignment:** search `framework_index` + `collection_index`; rerank with the coach's original query; inject as "Relevant Coaching Knowledge (situation)".
2. **Phase 2 — Expert solutions:** build a solution-focused query from phase-1 hits; search `collection_index` only; rerank; apply `diversify_by_collection()` so multiple experts appear; inject as "Expert Perspectives (stored solutions)" with person name, guide title, and timestamp.

The cross-encoder reranker is **text-based** and works across both embed profiles — two rerank passes (one per phase) are used instead of one.

`retrieve()` on the framework index alone is preserved for backward-compatible tests and simple callers.

### 5. Collections API

`app/api/collections.py`:

- `GET/POST /api/collections`
- `POST /api/collections/{id}/sources`
- `GET /api/collections/{id}/sources/{sid}`
- `POST /api/collections/{id}/reindex`
- `POST /api/collections/process-jobs`

`POST /api/ingest` reindexes framework docs **and** all collections.

## Consequences

**Positive:**

- Coaches get multi-expert, attributed answers without per-request collection filtering.
- Framework docs stay on fast local embeddings; collection ingest can use higher-quality cloud embeddings once.
- No vector database required for MVP — consistent with ADR-0003's in-memory approach.
- `retrieve()` interface unchanged for legacy callers; new behaviour is opt-in via two-phase path in chat.

**Negative:**

- Two embed API calls per chat message when both indices have embeddings (framework query + collection query).
- Collection and framework vectors live in separate indices — no single cosine space across corpora; RRF merge is approximate.
- Media jobs require optional host tools (`ffmpeg`, `yt-dlp`, `faster-whisper`) not in `requirements.txt` by default.
- `KnowledgeStore` shares the same SQLite file as `MemoryStore` — acceptable for local deployment but couples schemas.

## Alternatives Considered

| Option | Reason Not Chosen |
|--------|------------------|
| Re-embed everything with OpenAI | Expensive on every starter/private reindex; unnecessary for small framework corpus |
| Single index, one embed model for all | Forces cloud embed on every query or downgrades collection quality to E5 |
| Per-collection isolated search | User wants cross-expert perspectives by default, not siloed retrieval |
| ChromaDB / pgvector now | Corpus still small; ADR-0003 defers vector DB until ~10k chunks |
| LLM topic extraction for phase 2 | Added latency/cost; heuristic query expansion sufficient for MVP |

## Future Direction

- Structured citation objects in API responses (not only prompt injection).
- Per-collection embed provider override in `collection.json`.
- Incremental collection reindex without full `collection_index` rebuild.
- Vector DB behind stable `retrieve_coach_context()` when chunk count grows.
- Eval set for multi-expert diversity and citation accuracy in `data/eval/`.
