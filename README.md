# Life Coach AI

An AI-powered life coaching assistant that runs locally using open-source LLMs. Designed for a single coach to use with their clients (10-20/day).

## Quick Summary

| Item | Detail |
|------|--------|
| LLM | Llama 3.1 8B (via Ollama) |
| RAG | ChromaDB (local vector store) |
| Backend | FastAPI (Python) |
| Frontend | Open WebUI or custom web UI |
| Database | SQLite (user memory) |
| Hosting | Local machine (coach's PC/laptop) |
| Cost | $0/month after setup |

## Prerequisites

- PC/Laptop with **NVIDIA GPU (8GB+ VRAM)** or Apple Silicon Mac (M1+)
- Python 3.11+
- [Ollama](https://ollama.com) installed

## Getting Started

```bash
# 1. Clone
git clone https://github.com/rezaghadimim/life-coach-ai.git
cd life-coach-ai

# 2. Install Ollama & pull model
ollama pull llama3.1:8b

# 3. Install dependencies
pip install -r requirements.txt

# 4. Ingest coach's documents
python scripts/ingest.py --docs-dir ./docs/knowledge/

# 5. Run
python main.py
```

## Documentation

- [Architecture](./docs/ARCHITECTURE.md) — System design and component overview
- [Implementation Plan](./docs/IMPLEMENTATION.md) — Step-by-step build plan
- [RAG Pipeline](./docs/RAG.md) — How knowledge retrieval works
- [Memory System](./docs/MEMORY.md) — Long-term user memory design
- [Fine-tuning Guide](./docs/FINETUNE.md) — Future model customization

## Project Structure

See [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) for full details.

```
life-coach-ai/
├── main.py                 # App entrypoint
├── app/
│   ├── api/               # FastAPI routes
│   ├── core/              # Config, prompts, LLM client
│   ├── rag/               # Document ingestion & retrieval
│   ├── memory/            # User session & long-term memory
│   └── models/            # Pydantic schemas
├── docs/
│   ├── knowledge/         # Coach's materials (PDFs, text)
│   ├── ARCHITECTURE.md
│   ├── IMPLEMENTATION.md
│   ├── RAG.md
│   ├── MEMORY.md
│   └── FINETUNE.md
├── scripts/
│   ├── ingest.py          # Ingest docs into vector store
│   └── finetune.py        # Fine-tune script (future)
├── tests/
└── requirements.txt
```
