# coach-knowledge-private

Your **private** coaching knowledge base for [Coach Assistant AI](https://github.com/YOUR_USER/coach-assistant-ai).

This repository is cloned into `docs/knowledge/private/` in the app project.
On every ingest, these files are **merged with** the app’s committed
`starter/` docs — same filename in this repo **overrides** the starter copy.

## What to put here

- Your coaching manuals, playbooks, and licensed materials you have rights to use
- Customized markdown overrides (copy from app `starter/` and edit)
- PDFs and `.txt` reference documents

**Do not store client PII** (names, emails, session notes). Client data belongs in
the app’s SQLite memory, not in RAG files.

## Quick start (after clone)

```bash
# Copy a starter doc from the app repo and customize
cp ../coach-assistant-ai/docs/knowledge/starter/grow_model.md ./grow_model.md

# Or add your own files
# my_company_playbook.pdf
# session_frameworks.md

git add .
git commit -m "Add initial coaching knowledge"
git push
```

Re-index in the app:

```bash
cd ../coach-assistant-ai
python scripts/ingest.py
```

## Override rule

| File location | Indexed? |
|---------------|----------|
| Only in `starter/` | Yes (bootstrap) |
| Only in this repo | Yes (appended) |
| Same name in both | **This repo wins** |

## Supported formats

- `.md` — best results; use `##` section headings
- `.txt` — plain text
- `.pdf` — requires `pypdf` in the API environment

## Suggested layout

```text
coach-knowledge-private/
├── README.md                 ← this file
├── grow_model.md             ← optional override
├── company_playbook.md
├── manuals/
│   └── internal_coaching_guide.pdf
└── notes/
    └── methodology_2024.md
```

## Backup

Because this is its own git repository, every `git push` backs up your documents.
Use a **private** GitHub repository and enable 2FA on your account.
