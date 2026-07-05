# RAG Knowledge Base

Three sources are indexed together on every startup and `POST /api/ingest`:

| Source | Location | Git | Purpose |
|--------|----------|-----|---------|
| Starter | [`starter/`](starter/) | **This repo** | Bundled coaching frameworks (GROW, MI, SMART, …) |
| Private | [`private/`](private/) | **Submodule** → [`coach-knowledge`](https://github.com/rezaghadimim/coach-knowledge) | Your manuals and overrides |
| Collections | `data/knowledge/collections/` | **Local data** (not in git by default) | Per-person video/transcript expert guides |

**Merge rule (starter + private):** all starter files are indexed. Private files are **appended**.
If the same relative path exists in both (e.g. `grow_model.md`), the **private copy overrides** the starter copy.

**Collections** are indexed into a separate in-memory index with their own embedding provider (default: OpenRouter/OpenAI at ingest time). See [Collection workflow](#expert-video-collections) below.

## First-time setup (private repo)

**→ Follow [`SETUP_PRIVATE_REPO.md`](SETUP_PRIVATE_REPO.md)** for GitHub steps and clone instructions.

Quick version:

```bash
# 1. Submodule is configured in .gitmodules — init it:
./scripts/setup_knowledge_private_repo.sh

# 2. Re-index
python3 scripts/ingest.py
```

## Daily workflow

```bash
# Edit knowledge (private repo)
cd docs/knowledge/private
vim grow_model.md
git add . && git commit -m "Update GROW notes" && git push

# Refresh RAG index in app
cd ../../.. && python3 scripts/ingest.py
```

## Expert video collections

Each person (coach, trainer, author) gets a **collection** — their video guides embedded as searchable knowledge with citations (who said what, which guide, timestamp).

### Filesystem layout

```text
data/knowledge/collections/
└── jane-doe/
    ├── collection.json
    └── sources/
        └── handling-resistance/
            ├── meta.json
            └── transcript.vtt
```

`collection.json` example:

```json
{
  "slug": "jane-doe",
  "person_name": "Jane Doe",
  "title": "Jane Doe",
  "description": "Resistance and accountability guides",
  "embed_provider": "openrouter",
  "embed_model": "openai/text-embedding-3-small"
}
```

`meta.json` example:

```json
{
  "title": "Handling resistance",
  "source_type": "transcript",
  "uri": ""
}
```

Supported transcript files: `.vtt`, `.srt`, `.txt`, `.md`.  
For local video/audio (`.mp4`, `.mp3`, …) or YouTube URLs, register via API with `source_type` `local_media` or `youtube` and run `POST /api/collections/process-jobs`.

### API workflow

```bash
# Create collection
curl -X POST http://localhost:8000/api/collections \
  -H "Content-Type: application/json" \
  -d '{"slug":"jane-doe","person_name":"Jane Doe","title":"Jane Doe"}'

# Register a transcript source (place files under data/knowledge/collections/jane-doe/sources/...)
curl -X POST http://localhost:8000/api/collections/jane-doe/sources \
  -H "Content-Type: application/json" \
  -d '{"title":"Handling resistance","source_type":"transcript","source_id":"handling-resistance"}'

# Reindex one collection (or reindex everything)
curl -X POST http://localhost:8000/api/collections/jane-doe/reindex
curl -X POST http://localhost:8000/api/ingest -H "Content-Type: application/json" -d '{}'
```

### How retrieval uses collections

Chat uses **two-phase retrieval** (see [`docs/RAG.md`](../RAG.md)):

1. **Situation** — frameworks + relevant expert context from all indices.
2. **Expert solutions** — practical passages from **multiple people** so the coach can compare perspectives.

## Starter disclaimer

Files in `starter/` are **bootstrap content** for retrieval testing — general
coaching framework summaries, not authoritative clinical or licensed material.
Put production content in your **private repo** or **collections**.

## Environment

```env
RAG_KNOWLEDGE_STARTER_DIR=docs/knowledge/starter
RAG_KNOWLEDGE_PRIVATE_DIR=docs/knowledge/private
RAG_COLLECTIONS_DIR=data/knowledge/collections

# Framework + collections use the same embed provider/model by default.
# RAG_EMBED_BASE_URL is an optional address override (e.g. a second server);
# leave empty to use the provider's own address (OLLAMA_BASE_URL / OPENAI_BASE_URL / OPENROUTER_BASE_URL).
RAG_EMBED_PROVIDER=ollama
RAG_EMBED_BASE_URL=
RAG_EMBED_MODEL=karuniaperjuangan/multilingual-e5-small
# Optional cloud embed for collections only:
# RAG_COLLECTION_EMBED_PROVIDER=openrouter
# RAG_COLLECTION_EMBED_MODEL=openai/text-embedding-3-small

# Two-phase coach retrieval
RAG_TWO_PHASE_ENABLED=true
```

Legacy `RAG_KNOWLEDGE_TEMPLATES_DIR` and `RAG_DOCS_DIR` map to the starter directory.

See [`docs/RAG.md`](../RAG.md) for the full retrieval pipeline and [ADR-0011](../adr/0011-collection-video-knowledge.md) for design rationale.
