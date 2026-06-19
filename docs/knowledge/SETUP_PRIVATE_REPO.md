# Private knowledge repository setup

Your real coaching documents live in a **separate private GitHub repository**
([`coach-knowledge`](https://github.com/rezaghadimim/coach-knowledge)). It is linked
as a **git submodule** at `docs/knowledge/private/` in this project.

Ingest merges **starter + private** on every startup and `POST /api/ingest`.

## Architecture

```text
coach-assistant-ai/                    ← this repo
  .gitmodules                          ← pins coach-knowledge commit
  docs/knowledge/starter/              ← committed bootstrap docs
  docs/knowledge/private/              ← git submodule → coach-knowledge

coach-knowledge/                        ← private GitHub repo (separate)
  grow_model.md
  company_playbook.pdf
  ...
```

---

## First-time setup (this project)

The submodule is already configured in `.gitmodules`:

```ini
[submodule "docs/knowledge/private"]
    path = docs/knowledge/private
    url = https://github.com/rezaghadimim/coach-knowledge.git
```

Initialize it:

```bash
./scripts/setup_knowledge_private_repo.sh
# or: git submodule update --init --recursive docs/knowledge/private

python3 scripts/ingest.py
```

---

## Clone on a new machine

```bash
git clone --recurse-submodules git@github.com:YOUR_USER/coach-assistant-ai.git
cd coach-assistant-ai
cp .env.example .env

python3 scripts/ingest.py
```

If you already cloned without submodules:

```bash
git submodule update --init --recursive
```

**Access required:** your GitHub account must have read access to
[`rezaghadimim/coach-knowledge`](https://github.com/rezaghadimim/coach-knowledge)
(private repo). Add collaborators under **Settings → Collaborators** on that repo.

---

## Add or edit documents

```bash
cd docs/knowledge/private

# Optional: override a starter doc from the app repo
cp ../starter/grow_model.md ./grow_model.md
# edit grow_model.md

git add .
git commit -m "Add customized GROW model"
git push
```

Re-index the app:

```bash
cd ../../..
python3 scripts/ingest.py
```

With Docker:

```bash
docker compose restart coach-api
```

The compose file mounts `./docs/knowledge` read-only; the submodule is included
automatically.

---

## Pin a new private-knowledge version in the app repo

After pushing changes to `coach-knowledge`, update the submodule pointer in this repo:

```bash
cd docs/knowledge/private && git pull
cd ../../..
git add docs/knowledge/private
git commit -m "Update private knowledge submodule"
git push
```

---

## Daily workflow

| Action | Command |
|--------|---------|
| Edit knowledge | Edit files in `docs/knowledge/private/` |
| Save + backup | `git add . && git commit -m "..." && git push` (inside submodule) |
| Refresh RAG index | `python3 scripts/ingest.py` or restart API |
| Pull on another machine | `git submodule update --remote docs/knowledge/private` |

---

## Environment variables

Defaults (no change needed):

```env
RAG_KNOWLEDGE_STARTER_DIR=docs/knowledge/starter
RAG_KNOWLEDGE_PRIVATE_DIR=docs/knowledge/private
PRIVATE_KNOWLEDGE_REPO=https://github.com/rezaghadimim/coach-knowledge.git
```

`PRIVATE_KNOWLEDGE_REPO` is documented for teammates only — the app reads
`RAG_KNOWLEDGE_STARTER_DIR` and `RAG_KNOWLEDGE_PRIVATE_DIR` from settings.

---

## Security checklist

- [ ] `coach-knowledge` GitHub repo is **Private**
- [ ] 2FA enabled on GitHub
- [ ] No client PII in knowledge files
- [ ] Licensed PDFs only if you have redistribution rights
- [ ] Collaborators on `coach-knowledge` are intentional (they can read all docs)

---

## Troubleshooting

**Submodule directory is empty after clone**

```bash
git submodule update --init --recursive docs/knowledge/private
```

**Permission denied / 404 on submodule**

You need access to the private `coach-knowledge` repo. Use HTTPS with a personal
access token, or SSH:

```bash
git config submodule.docs/knowledge/private.url git@github.com:rezaghadimim/coach-knowledge.git
git submodule sync
git submodule update --init --recursive
```

**RAG returns empty after clone**

```bash
python3 scripts/ingest.py
docker compose logs coach-api | grep "rag:"
```

---

## Creating `coach-knowledge` from scratch (reference)

Already done for this project. For a new fork, push scaffold from
`docs/knowledge/private-repo-scaffold/` then:

```bash
git submodule add https://github.com/YOUR_USER/coach-knowledge.git docs/knowledge/private
git commit -m "Add private knowledge submodule"
```
