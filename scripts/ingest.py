"""CLI helper to ingest coaching documents into the local retriever index."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.core.knowledge_paths import knowledge_ingest_summary
from app.rag.retriever import ingest_and_index_knowledge


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest coaching documents")
    parser.add_argument(
        "--starter-dir",
        default=settings.rag_knowledge_starter_dir,
        help="Committed starter knowledge directory (default from settings).",
    )
    parser.add_argument(
        "--private-dir",
        default=settings.rag_knowledge_private_dir,
        help="Local private knowledge directory (default from settings).",
    )
    parser.add_argument("--chunk-size", type=int, default=settings.rag_chunk_size)
    parser.add_argument("--chunk-overlap", type=int, default=settings.rag_chunk_overlap)
    args = parser.parse_args()

    if (
        args.starter_dir != settings.rag_knowledge_starter_dir
        or args.private_dir != settings.rag_knowledge_private_dir
    ):
        from app.rag.ingest import ingest_documents_from_dirs
        from app.rag.retriever import index_chunks

        chunks = ingest_documents_from_dirs(
            args.starter_dir,
            args.private_dir,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
        )
        docs = len({chunk.source_path for chunk in chunks})
        index_chunks(chunks, reset=True)
        print(
            f"Indexed {len(chunks)} chunks from {docs} documents in "
            f"'{args.starter_dir}' + '{args.private_dir}'."
        )
        return

    docs, chunks = ingest_and_index_knowledge(
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )
    print(
        f"Indexed {chunks} chunks from {docs} documents in "
        f"'{knowledge_ingest_summary()}'."
    )


if __name__ == "__main__":
    main()
