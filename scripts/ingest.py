"""CLI helper to ingest coaching documents into the local retriever index."""

import argparse

from app.core.config import settings
from app.rag.retriever import ingest_and_index_directory


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest coaching documents")
    parser.add_argument("--docs-dir", default=settings.rag_docs_dir)
    parser.add_argument("--chunk-size", type=int, default=settings.rag_chunk_size)
    parser.add_argument("--chunk-overlap", type=int, default=settings.rag_chunk_overlap)
    args = parser.parse_args()

    docs, chunks = ingest_and_index_directory(
        args.docs_dir,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )
    print(f"Indexed {chunks} chunks from {docs} documents in '{args.docs_dir}'.")


if __name__ == "__main__":
    main()
