# RAG Knowledge Base

Two sources are indexed together on every startup and `POST /api/ingest`:

| Directory | Git | Purpose |
|-----------|-----|---------|
| [`starter/`](starter/) | **This repo** | Bundled coaching frameworks (GROW, MI, SMART, …). Safe for public git. |
| [`private/`](private/) | **Submodule** → [`coach-knowledge`](https://github.com/rezaghadimim/coach-knowledge) | Your real manuals and overrides |

**Merge rule:** all starter files are indexed. Private files are **appended**.
If the same relative path exists in both (e.g. `grow_model.md`), the **private
copy overrides** the starter copy.

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

## Starter disclaimer

Files in `starter/` are **bootstrap content** for retrieval testing — general
coaching framework summaries, not authoritative clinical or licensed material.
Put production content in your **private repo**.

## Environment

```env
RAG_KNOWLEDGE_STARTER_DIR=docs/knowledge/starter
RAG_KNOWLEDGE_PRIVATE_DIR=docs/knowledge/private
# Documented for teammates only — not read by the app:
PRIVATE_KNOWLEDGE_REPO=https://github.com/rezaghadimim/coach-knowledge.git
```

Legacy `RAG_KNOWLEDGE_TEMPLATES_DIR` and `RAG_DOCS_DIR` map to the starter directory.

See [`docs/RAG.md`](../RAG.md) for the full retrieval pipeline.
