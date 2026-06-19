"""Core document loading and chunking logic for RAG ingestion."""

from dataclasses import dataclass
from pathlib import Path
import re
import tempfile
from typing import List, Optional

DEFAULT_CHUNK_SIZE = 300
DEFAULT_CHUNK_OVERLAP = 50
SUPPORTED_FILE_EXTENSIONS = (".txt", ".md", ".pdf")
_SECTION_SPLIT = re.compile(r"^(#{2,3}\s+.+)$", re.MULTILINE)


@dataclass(frozen=True)
class DocumentChunk:
    """A chunk generated from a source document."""

    chunk_id: str
    source_path: str
    text: str
    start_token: int
    end_token: int


def discover_documents(docs_dir: str) -> List[Path]:
    """Return all supported document files under a directory (recursive)."""
    root = Path(docs_dir).expanduser().resolve()
    workspace_root = Path.cwd().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    allowed_roots = (workspace_root, temp_root)
    if not any(root.is_relative_to(allowed_root) for allowed_root in allowed_roots):
        allowed_display = ", ".join(str(path) for path in allowed_roots)
        raise PermissionError(
            f"Documents directory must be inside allowed roots: {allowed_display}"
        )
    if not root.exists():
        raise FileNotFoundError(f"Documents directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Expected a directory path: {root}")

    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_FILE_EXTENSIONS
        ),
        key=lambda path: str(path),
    )


def read_document(path: str) -> str:
    """Read supported documents (.txt, .md, .pdf) into plain text."""
    source = Path(path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Document does not exist: {source}")
    if not source.is_file():
        raise ValueError(f"Expected a file path, got: {source}")

    suffix = source.suffix.lower()
    if suffix in (".txt", ".md"):
        return source.read_text(encoding="utf-8").strip()
    if suffix == ".pdf":
        return _read_pdf(source)

    raise ValueError(
        f"Unsupported file type '{suffix}'. Supported: {SUPPORTED_FILE_EXTENSIONS}"
    )


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> List[str]:
    """Split text into overlapping token chunks."""
    tokens = _tokenize(text)
    if not tokens:
        return []

    _validate_chunk_config(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    step = chunk_size - chunk_overlap

    chunks: List[str] = []
    for start in range(0, len(tokens), step):
        end = min(start + chunk_size, len(tokens))
        chunks.append(" ".join(tokens[start:end]))
        if end == len(tokens):
            break
    return chunks


def build_document_chunks(
    text: str,
    source_path: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> List[DocumentChunk]:
    """Build structured chunks with source metadata for one document."""
    if Path(source_path).suffix.lower() == ".md":
        sections = _split_markdown_sections(text)
    else:
        sections = [text]

    source_name = Path(source_path).name
    chunks: List[DocumentChunk] = []
    chunk_index = 0
    for section in sections:
        section_chunks = _chunk_token_window(
            section,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        for section_text, start, end in section_chunks:
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{source_name}:{chunk_index}",
                    source_path=source_path,
                    text=section_text,
                    start_token=start,
                    end_token=end,
                )
            )
            chunk_index += 1
    return chunks


def _split_markdown_sections(text: str) -> List[str]:
    """Split markdown on ``##`` / ``###`` headings so chunks stay semantically coherent."""
    parts = _SECTION_SPLIT.split(text)
    if len(parts) <= 1:
        return [text.strip()] if text.strip() else []

    sections: List[str] = []
    preamble = parts[0].strip()
    if preamble:
        sections.append(preamble)

    for index in range(1, len(parts), 2):
        heading = parts[index]
        body = parts[index + 1] if index + 1 < len(parts) else ""
        section = f"{heading}\n{body}".strip()
        if section:
            sections.append(section)
    return sections


def _chunk_token_window(
    text: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> List[tuple[str, int, int]]:
    """Return (chunk_text, start_token, end_token) tuples for one text window."""
    tokens = _tokenize(text)
    if not tokens:
        return []

    _validate_chunk_config(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    step = chunk_size - chunk_overlap

    chunks: List[tuple[str, int, int]] = []
    for start in range(0, len(tokens), step):
        end = min(start + chunk_size, len(tokens))
        chunks.append((" ".join(tokens[start:end]), start, end))
        if end == len(tokens):
            break
    return chunks


def discover_documents_optional(docs_dir: str) -> List[Path]:
    """Like :func:`discover_documents` but returns ``[]`` when *docs_dir* is missing."""
    root = Path(docs_dir).expanduser().resolve()
    if not root.exists():
        return []
    return discover_documents(docs_dir)


def discover_knowledge_documents(
    starter_dir: str,
    private_dir: Optional[str] = None,
) -> List[Path]:
    """Discover starter + private knowledge files, with private overriding starter.

    Both directories are scanned recursively for ``.txt``, ``.md``, and ``.pdf``.
    When the same relative path exists in both (e.g. ``grow_model.md``), the
    private copy wins so coaches can fork and customize bundled content locally.
    """
    by_key: dict[str, Path] = {}
    starter_root = Path(starter_dir).expanduser().resolve()

    for path in discover_documents(starter_dir):
        key = path.relative_to(starter_root).as_posix()
        by_key[key] = path

    if private_dir:
        private_root = Path(private_dir).expanduser().resolve()
        for path in discover_documents_optional(private_dir):
            key = path.relative_to(private_root).as_posix()
            by_key[key] = path

    return sorted(by_key.values(), key=lambda item: str(item))


def ingest_documents_from_dirs(
    starter_dir: str,
    private_dir: Optional[str] = None,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> List[DocumentChunk]:
    """Load supported files from starter + private dirs and return all chunks."""
    chunks: List[DocumentChunk] = []
    for path in discover_knowledge_documents(starter_dir, private_dir):
        text = read_document(str(path))
        if not text:
            continue
        chunks.extend(
            build_document_chunks(
                text=text,
                source_path=str(path),
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        )
    return chunks


def ingest_documents_from_dir(
    docs_dir: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> List[DocumentChunk]:
    """Load supported files from a single directory and return all generated chunks."""
    chunks: List[DocumentChunk] = []
    for path in discover_documents(docs_dir):
        text = read_document(str(path))
        if not text:
            continue
        chunks.extend(
            build_document_chunks(
                text=text,
                source_path=str(path),
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        )
    return chunks


def _tokenize(text: str) -> List[str]:
    return [token for token in text.split() if token]


def _validate_chunk_config(chunk_size: int, chunk_overlap: int) -> None:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be >= 0")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Reading PDF files requires 'pypdf'. Install it before ingesting PDFs."
        ) from exc

    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(page.strip() for page in pages if page.strip()).strip()
