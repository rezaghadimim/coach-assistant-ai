# RAG Pipeline

> Retrieval-Augmented Generation: How we ground the AI's responses in the coach's actual methodology.

## Why RAG?

Without RAG, the model gives generic coaching advice. With RAG, it references the coach's specific frameworks, exercises, and terminology.

## How It Works

```
┌─────────────────────────────────────────┐
│             INGESTION (once)             │
│                                          │
│  PDF/TXT ──▶ Chunk ──▶ Embed ──▶ Store  │
│                                ChromaDB  │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│           RETRIEVAL (per query)          │
│                                          │
│  User Msg ──▶ Embed ──▶ Search ──▶ Top K │
│                          ChromaDB        │
└─────────────────────────────────────────┘
```

## Ingestion Details

### Supported Formats
- `.txt` — Plain text files
- `.md` — Markdown files
- `.pdf` — PDF documents (via pypdf)

### Chunking Strategy

```python
CHUNK_SIZE = 512       # tokens per chunk
CHUNK_OVERLAP = 50     # overlap between chunks
SEPARATORS = ["\n\n", "\n", ". ", " "]  # split priority
```

**Why 512 tokens?**
- Small enough to be specific/relevant
- Large enough to contain a complete thought
- Fits well in context window alongside other components

### Embedding Model

```
Model: nomic-embed-text (via Ollama)
Dimensions: 768
Speed: ~100 chunks/second on CPU
Quality: Competitive with OpenAI ada-002
```

## Retrieval Details

### Query Flow
1. User message is embedded using same model
2. ChromaDB finds top-K most similar chunks
3. Chunks are formatted and injected into prompt

### Parameters

```python
TOP_K = 3              # number of chunks to retrieve
MIN_SIMILARITY = 0.7   # ignore chunks below this score
```

### Prompt Integration

```
## Relevant Coaching Knowledge:

[Chunk 1: From "GROW Model Guide", page 3]
The Reality phase involves asking the client to describe their current situation
without judgment. Key questions: "What is happening now?" "What have you tried?"

[Chunk 2: From "Powerful Questions", page 7]
Avoid "why" questions as they trigger defensiveness. Use "what" and "how" instead.

[Chunk 3: ...]
```

## What to Ingest

Place coaching materials in `docs/knowledge/`:

```
docs/knowledge/
├── grow-model.pdf
├── powerful-questions.txt
├── tony-robbins-notes.md
├── motivational-interviewing.pdf
├── client-exercises/
│   ├── wheel-of-life.txt
│   └── values-clarification.txt
└── coach-methodology.md      # Coach's own approach
```

## Usage

```bash
# Ingest all documents
python scripts/ingest.py --docs-dir ./docs/knowledge/

# Ingest a single file
python scripts/ingest.py --file ./docs/knowledge/new-book.pdf

# Check what's ingested
python scripts/ingest.py --status
```
