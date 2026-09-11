"""
Chunker — turns LoadedPages into Chunks with metadata (ADR-002, ADR-008).

Uses LangChain's RecursiveCharacterTextSplitter with a paragraph-first
separator cascade. Walks page by page so page numbers, section headings,
and character offsets all survive into the metadata.

Why per-page (not document-wide) chunking:
- Preserves the page → chunk mapping we need for citations.
- Prevents chunks from straddling a page boundary in a way that
  confuses "which page is this on?" — a chunk is always attributed to
  exactly one page.
- Loses a little context at page edges; acceptable for this corpus
  (handbook sections are short and self-contained).

Section detection:
- The TechCorp handbook uses ALL-CAPS or title-cased headings on their
  own line, e.g. "Deployment Policy" or "SECURITY GUIDELINES".
- We keep a rolling "current section" per page and attach it to every
  chunk derived from that page.
- If no heading has been seen yet on a page, section is "" (empty).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter
from shared.logging.setup import get_logger
from shared.schemas.chunk import Chunk, ChunkMetadata

from ingestion.loader import LoadedDocument, LoadedPage

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────
# Section-heading heuristic
# ─────────────────────────────────────────────────────────────
# A line is treated as a heading if:
#   - length 3..80 chars
#   - no trailing sentence punctuation (., ;, ,)
#   - either ALL CAPS (>=2 letters), Title Case, or "N. Title" numbering
#   - not purely numeric, not a bare page marker like "Page 12"
_HEADING_MAX_LEN = 80
_SENTENCE_PUNCT = re.compile(r"[.;,]$")
_NUMBERED = re.compile(r"^\d+(\.\d+)*\.?\s+[A-Z]")
_ALLCAPS = re.compile(r"^[A-Z][A-Z0-9 \-&/:]{2,}$")
_TITLE = re.compile(r"^[A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+){0,6}$")
_PAGE_MARKER = re.compile(r"^page\s+\d+$", re.IGNORECASE)


def _looks_like_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > _HEADING_MAX_LEN:
        return False
    if _PAGE_MARKER.match(s):
        return False
    if _SENTENCE_PUNCT.search(s):
        return False
    if _NUMBERED.match(s):
        return True
    if _ALLCAPS.match(s) and any(c.isalpha() for c in s):
        return True
    # Title-case heuristic: 2–7 words, each capitalized, no sentence.
    words = s.split()
    if 1 < len(words) <= 7 and _TITLE.match(s):
        return True
    return False


def _extract_section_map(page: LoadedPage) -> list[tuple[int, str]]:
    """
    Return [(line_index, heading_text), ...] for every heading on a page.

    We use line indices (not char offsets) because the splitter works on
    the page's text as a string, and we later map a chunk's start offset
    back to the nearest preceding heading by scanning lines up to that
    offset.
    """
    headings: list[tuple[int, str]] = []
    for idx, line in enumerate(page.text.splitlines()):
        if _looks_like_heading(line):
            headings.append((idx, line.strip()))
    return headings


def _heading_before_offset(
    page_text: str, headings: list[tuple[int, str]], offset: int
) -> str:
    """
    Find the last heading whose line starts before `offset` (a char offset
    into `page_text`). Returns "" if no heading precedes the offset.
    """
    if not headings:
        return ""
    # Compute character offset of the start of each heading's line.
    line_offsets: list[int] = []
    running = 0
    for line in page_text.splitlines(keepends=True):
        line_offsets.append(running)
        running += len(line)

    best = ""
    for (line_idx, heading_text) in headings:
        if line_idx >= len(line_offsets):
            continue
        if line_offsets[line_idx] <= offset:
            best = heading_text
        else:
            break
    return best


# ─────────────────────────────────────────────────────────────
# Splitter
# ─────────────────────────────────────────────────────────────
def _build_splitter(chunk_size: int, chunk_overlap: int) -> RecursiveCharacterTextSplitter:
    """
    Paragraph-first separator cascade (ADR-002).

    LangChain tries each separator in order: it prefers to split on the
    first one that produces chunks under the size limit. Blank lines
    first, then single newlines, then sentence boundaries, then words,
    then characters as a last resort.
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
        keep_separator=True,
        length_function=len,
    )


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ChunkerConfig:
    chunk_size: int = 800
    chunk_overlap: int = 150

    def __post_init__(self) -> None:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"chunk_overlap ({self.chunk_overlap}) must be < chunk_size ({self.chunk_size})"
            )


def chunk_document(
    doc: LoadedDocument,
    config: ChunkerConfig | None = None,
) -> list[Chunk]:
    """
    Split a LoadedDocument into Chunks with full ChunkMetadata.

    Every chunk gets:
      - a fresh uuid4 as chunk_id
      - page = the page it came from
      - section = nearest preceding heading on that page (or "")
      - chunk_index = global order across the whole document
      - char_start / char_end = offsets into doc.full_text
      - doc_hash = from the loaded doc
    """
    cfg = config or ChunkerConfig()
    splitter = _build_splitter(cfg.chunk_size, cfg.chunk_overlap)

    chunks: list[Chunk] = []
    global_index = 0

    for page in doc.pages:
        headings = _extract_section_map(page)

        # split_text returns the raw chunk strings in order; we don't get
        # per-chunk offsets from LangChain, so we compute them ourselves
        # by advancing a cursor. Overlap means a chunk starts before the
        # previous one ended, so we track with `find` from the previous
        # end offset — the splitter's output is a subsequence of the
        # input text (up to whitespace normalization).
        page_chunks = splitter.split_text(page.text)

        search_from = 0
        for text in page_chunks:
            # Locate this chunk in the page text (from the previous match
            # forward, to handle overlaps correctly).
            found_at = page.text.find(text, search_from)
            if found_at < 0:
                # Fallback: search from start (rare, only if splitter
                # normalized whitespace beyond our `find` expectation).
                found_at = page.text.find(text)
            if found_at < 0:
                # Give up on precise offsets — fall back to sequential.
                local_start = search_from
                local_end = search_from + len(text)
            else:
                local_start = found_at
                local_end = found_at + len(text)

            # Advance for the next iteration; overlap means we don't jump
            # past the next chunk's start, so use `local_start + 1`.
            search_from = max(search_from, local_start + 1)

            section = _heading_before_offset(page.text, headings, local_start)

            chunk_char_start = page.char_start + local_start
            chunk_char_end = page.char_start + local_end

            metadata = ChunkMetadata(
                chunk_id=str(uuid.uuid4()),
                source=doc.source_name,
                page=page.page_number,
                section=section,
                chunk_index=global_index,
                char_start=chunk_char_start,
                char_end=chunk_char_end,
                doc_hash=doc.doc_hash,
            )
            chunks.append(Chunk(text=text, metadata=metadata))
            global_index += 1

    log.info(
        "document_chunked",
        source=doc.source_name,
        pages=len(doc.pages),
        chunks=len(chunks),
        chunk_size=cfg.chunk_size,
        chunk_overlap=cfg.chunk_overlap,
    )

    return chunks


__all__ = [
    "ChunkerConfig",
    "chunk_document",
]