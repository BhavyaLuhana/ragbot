"""
PDF loader — pypdf wrapper with per-page text extraction.

The loader is deliberately thin: it converts a PDF on disk into a list of
`LoadedPage` records, preserving page numbers and running minimal
normalization (whitespace collapse). Chunking is a separate concern.

Design notes:
- We extract per-page, not document-wide, so page numbers survive into
  chunk metadata (needed for citations — architecture.md §7).
- Whitespace normalization is conservative: collapse runs of spaces and
  strip trailing whitespace per line, but preserve paragraph breaks
  (`\n\n`) because the chunker relies on them.
- No OCR. If a page yields zero extractable text, we log a warning and
  skip it — never silently drop content.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from shared.logging.setup import get_logger

log = get_logger(__name__)


# Collapse 2+ spaces/tabs to a single space; keep newlines intact.
_INLINE_WS = re.compile(r"[ \t]{2,}")


@dataclass(frozen=True)
class LoadedPage:
    """A single page of extracted text."""

    page_number: int  # 1-indexed
    text: str
    char_start: int  # offset in the doc-wide concatenated text (inclusive)
    char_end: int    # offset in the doc-wide concatenated text (exclusive)


@dataclass(frozen=True)
class LoadedDocument:
    """All pages + document-level metadata."""

    source_path: Path
    source_name: str
    doc_hash: str
    pages: list[LoadedPage]
    full_text: str  # pages joined by "\n\n" — used to compute char offsets


class LoaderError(RuntimeError):
    """Raised when a PDF cannot be read or yields no extractable text."""


def _normalize_page_text(text: str) -> str:
    """
    Minimal, non-destructive cleanup.

    - Collapse runs of 2+ spaces/tabs to 1 (PDF extraction often inserts
      extra spaces at line joins).
    - Strip trailing whitespace per line.
    - Collapse 3+ blank lines to 2 (preserve paragraph breaks).
    - Do NOT strip leading indentation entirely — some docs use it.
    """
    text = _INLINE_WS.sub(" ", text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def compute_doc_hash(path: Path, chunk_size: int = 1 << 20) -> str:
    """
    sha256 of the raw PDF bytes, streamed in 1 MiB chunks.

    Used for idempotency — re-ingesting the same PDF is a no-op unless
    `force=True`.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def load_pdf(path: Path) -> LoadedDocument:
    """
    Load a PDF from disk and return a `LoadedDocument`.

    Raises:
        LoaderError: file missing, unreadable PDF, or zero extractable text.

    Notes:
        - We iterate pages in order and preserve 1-indexed page numbers.
        - Empty pages are skipped from `pages` but their character range
          still advances the concatenated `full_text`, so offsets stay
          consistent with a naive concatenation of non-empty pages.
        - `doc_hash` is computed over the raw file bytes, not the extracted
          text, so it's stable against pypdf version changes.
    """
    if not path.is_file():
        raise LoaderError(f"PDF not found: {path}")

    try:
        reader = PdfReader(str(path))
    except PdfReadError as exc:
        raise LoaderError(f"Failed to read PDF: {exc}") from exc

    doc_hash = compute_doc_hash(path)
    pages: list[LoadedPage] = []
    full_text_parts: list[str] = []
    cursor = 0

    for i, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 — pypdf can raise lots
            log.warning(
                "page_extract_failed",
                page=i,
                source=path.name,
                error=str(exc),
            )
            raw = ""

        cleaned = _normalize_page_text(raw)
        if not cleaned:
            log.warning("page_empty", page=i, source=path.name)
            continue

        # char offsets are computed against the concatenated full_text,
        # using "\n\n" as the join separator so we can round-trip.
        if full_text_parts:
            cursor += len("\n\n")  # account for the join separator
        char_start = cursor
        cursor += len(cleaned)
        char_end = cursor

        pages.append(
            LoadedPage(
                page_number=i,
                text=cleaned,
                char_start=char_start,
                char_end=char_end,
            )
        )
        full_text_parts.append(cleaned)

    if not pages:
        raise LoaderError(
            f"No extractable text in {path.name}. Is this a scanned/image PDF?"
        )

    full_text = "\n\n".join(full_text_parts)

    log.info(
        "pdf_loaded",
        source=path.name,
        doc_hash=doc_hash[:12],
        pages_total=len(reader.pages),
        pages_with_text=len(pages),
        chars=len(full_text),
    )

    return LoadedDocument(
        source_path=path,
        source_name=path.name,
        doc_hash=doc_hash,
        pages=pages,
        full_text=full_text,
    )


__all__ = [
    "LoaderError",
    "LoadedDocument",
    "LoadedPage",
    "compute_doc_hash",
    "load_pdf",
]