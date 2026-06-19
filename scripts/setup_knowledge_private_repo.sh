#!/usr/bin/env bash
# Initialize or clone private knowledge into docs/knowledge/private/
#
# Preferred: git submodule (see .gitmodules)
#   ./scripts/setup_knowledge_private_repo.sh
#
# One-off clone (no submodule):
#   ./scripts/setup_knowledge_private_repo.sh https://github.com/USER/oach-knowledge.git
#
# See docs/knowledge/SETUP_PRIVATE_REPO.md

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$ROOT/docs/knowledge/private"
REPO_URL="${1:-}"

if [[ -d "$TARGET/.git" ]]; then
  echo "Private knowledge repo already present at: $TARGET"
  if git -C "$TARGET" rev-parse --is-inside-work-tree &>/dev/null; then
    echo "To update: cd $TARGET && git pull"
  fi
  exit 0
fi

if [[ ! -d "$ROOT/docs/knowledge/starter" ]]; then
  echo "ERROR: expected starter knowledge at $ROOT/docs/knowledge/starter" >&2
  exit 1
fi

# Submodule path configured — init from .gitmodules
if [[ -z "$REPO_URL" && -f "$ROOT/.gitmodules" ]]; then
  echo "Initializing private knowledge submodule..."
  git -C "$ROOT" submodule update --init --recursive docs/knowledge/private
  if [[ -d "$TARGET/.git" ]]; then
    echo "Done. Private knowledge at: $TARGET"
    exit 0
  fi
  echo "ERROR: submodule init failed — check .gitmodules and your GitHub access." >&2
  exit 1
fi

if [[ -z "$REPO_URL" ]]; then
  echo "Usage: $0 [git-clone-url]" >&2
  echo "  No URL: init from .gitmodules (submodule)" >&2
  echo "  With URL: clone into docs/knowledge/private/" >&2
  echo "Example: $0 https://github.com/rezaghadimim/oach-knowledge.git" >&2
  exit 1
fi

mkdir -p "$TARGET"
if [[ -n "$(ls -A "$TARGET" 2>/dev/null || true)" ]]; then
  echo "ERROR: $TARGET is not empty. Move files aside or remove them first." >&2
  exit 1
fi

echo "Cloning $REPO_URL -> $TARGET"
git clone "$REPO_URL" "$TARGET"

echo ""
echo "Done. Private knowledge repo is at: $TARGET"
echo ""
echo "Next steps:"
echo "  1. Add documents:  cd $TARGET"
echo "  2. Re-index RAG:     cd $ROOT && python3 scripts/ingest.py"
