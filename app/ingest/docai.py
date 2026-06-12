"""Document AI Layout Parser → list[ChunkedSection].

This module is the front of the Phase-2 ingestion pipeline:
    PDF → Doc AI Layout Parser → ChunkedSection[] → graph_extractor → Spanner

Region note: Google's Document AI Layout Parser processor type is only
available in the ``us`` location as of 2026-06. We accept the cross-region
hop from ``us`` (Doc AI) to ``asia-south1`` (Spanner Graph) per
DECISIONS-9 — the Indian-residency story attaches to Spanner, not to the
transient layout extraction.

The Layout Parser returns a ``Document`` with two relevant views:
    * ``document.document_layout.blocks`` — typed blocks (paragraph,
      heading-1..5, subtitle, header, footer, table, list, image) with
      page_span and child blocks. This is the source of ``layout_type``.
    * ``document.chunked_document.chunks`` — flat semantic chunks suitable
      for retrieval, but without explicit layout types.

We flatten ``document_layout.blocks`` recursively and emit one
``ChunkedSection`` per leaf block, preserving the typed layout label. The
flat order is the document's natural reading order, which lets us
resolve ``parent_heading`` with a single forward pass.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# Modern API surface — ``documentai_v1`` exports the canonical client +
# message classes. Avoid the alias module ``documentai`` (it re-exports
# the same names but pins them to v1beta3 internally on some versions).
from google.cloud import documentai_v1 as documentai

_PROCESSOR_ENV_VAR = "CURATOR_DOCAI_PROCESSOR_ID"

# Doc AI's online (synchronous) ``process_document`` rejects any request
# whose processed-page count exceeds 30 (``PAGE_LIMIT_EXCEEDED``). This is a
# hard server-side limit — it cannot be raised via config. To ingest large
# master directions (e.g. a 412-page Basel III circular) we split the PDF
# into <=30-page parts with pypdf, process each part online, and stitch the
# chunks back together with a page offset so page numbers stay absolute.
_ONLINE_PAGE_LIMIT = 30

# Overall ceiling on how many pages we will process for a single document —
# a cost guard, not a hard API limit. Override with CURATOR_DOCAI_MAX_PAGES.
# Default 500 covers every RBI master direction we have seen.
def _max_doc_pages() -> int:
    return int(os.environ.get("CURATOR_DOCAI_MAX_PAGES", "500"))


# Trailing-overlap (in pages) added to each part when batching a large PDF.
# A block (paragraph, table, list) that straddles a 30-page boundary would
# be truncated by a hard split. To prevent that, each part *owns* a primary
# page range but is parsed with this many extra trailing pages of context,
# so any block whose start page is owned by the part is rendered whole. A
# block is kept only by the part that owns its start page, giving a
# deterministic de-dup that never relies on text matching. Raise this for
# documents with very long page-spanning tables (cost: fewer owned pages per
# part → more parts). Override with CURATOR_DOCAI_PAGE_OVERLAP.
def _page_overlap() -> int:
    return max(0, int(os.environ.get("CURATOR_DOCAI_PAGE_OVERLAP", "2")))


class ChunkedSection(BaseModel):
    """One semantic chunk produced by Doc AI Layout Parser.

    Fields:
        text: chunk's text content (the rendered text of the block).
        layout_type: Doc AI's layout label — one of ``paragraph``,
            ``subtitle``, ``heading-1`` ... ``heading-5``, ``header``,
            ``footer``, ``table``, ``list``, ``image``.
        page_start / page_end: 1-indexed page numbers.
        chunk_id: deterministic, format ``{doc_id}#chunk-{ordinal:04d}``.
        parent_heading: the text of the most recent heading-typed chunk
            preceding this one, or None.
        raw_layout: optional raw block dict, populated only when caller
            asks for it via ``include_raw=True``.
    """

    text: str
    layout_type: str
    page_start: int
    page_end: int
    chunk_id: str
    parent_heading: str | None = None
    raw_layout: dict[str, Any] | None = Field(default=None, exclude=False)


# Layout types that count as "headings" for parent_heading resolution.
# Doc AI emits ``heading-1`` .. ``heading-5`` and ``subtitle``; we treat
# all of them as headings so that any indentation level seeds the
# downstream context.
_HEADING_TYPES: frozenset[str] = frozenset(
    {
        "subtitle",
        "title",
        "heading-1",
        "heading-2",
        "heading-3",
        "heading-4",
        "heading-5",
        "section_heading",
    }
)


def _normalise_page(p: int) -> int:
    """Doc AI page_span uses 1-indexed pages already, but defensively
    normalise: if a 0 appears (older SDK builds), bump to 1.
    """
    return max(1, int(p) if p else 1)


def _cell_text(cell: Any) -> str:
    """Flatten a Doc AI TableCell into a single line of text.

    A cell holds nested layout blocks; we pull the text from each text_block
    (recursing into children) and join with spaces. Numbers, percentages and
    dates inside a cell are preserved verbatim — these are exactly the
    risk-weight / CCF / LTV values the parameter-diff must see.
    """
    parts: list[str] = []

    def _walk(blocks: list[Any]) -> None:
        for blk in blocks or []:
            tb = getattr(blk, "text_block", None)
            if tb is not None:
                t = (getattr(tb, "text", "") or "").strip()
                if t:
                    parts.append(t)
                _walk(list(getattr(tb, "blocks", []) or []))

    _walk(list(getattr(cell, "blocks", []) or []))
    return " ".join(parts).strip()


def _render_table(table_block: Any) -> str:
    """Render a Doc AI table_block as pipe-delimited rows of real cell text.

    Materialising the cell values (rather than emitting a "[table: NhxMb]"
    placeholder) is what lets the diff catch numeric movements that live
    inside tables — e.g. an equity risk weight moving 125% → 250%.
    """
    lines: list[str] = []
    header_rows = list(getattr(table_block, "header_rows", []) or [])
    body_rows = list(getattr(table_block, "body_rows", []) or [])
    for row in header_rows + body_rows:
        cells = list(getattr(row, "cells", []) or [])
        rendered = [_cell_text(c) for c in cells]
        if any(rendered):
            lines.append(" | ".join(rendered))
    return "\n".join(lines)


def _flatten_blocks(
    blocks: list[Any],
    out: list[dict[str, Any]],
) -> None:
    """Recursively walk DocumentLayout.blocks, emitting one flat entry
    per leaf block (or per typed-text block, even if it has children —
    headings often nest paragraphs underneath them, and we want the
    heading recorded before its descendants).
    """
    for blk in blocks:
        page_span = getattr(blk, "page_span", None)
        ps = _normalise_page(getattr(page_span, "page_start", 1) or 1)
        pe = _normalise_page(getattr(page_span, "page_end", ps) or ps)

        # text_block: emit the text + recurse into children (children
        # are sometimes inline runs that duplicate the parent text; we
        # de-dup by emitting parent first and recursing only when the
        # parent itself has no text).
        text_block = getattr(blk, "text_block", None)
        if text_block is not None and (
            getattr(text_block, "text", "") or getattr(text_block, "blocks", None)
        ):
            text = (text_block.text or "").strip()
            layout_type = (text_block.type_ or "paragraph").strip() or "paragraph"
            if text:
                out.append(
                    {
                        "text": text,
                        "layout_type": layout_type,
                        "page_start": ps,
                        "page_end": pe,
                        "raw": {"kind": "text", "type": layout_type},
                    }
                )
            # Recurse into nested children; if parent already emitted
            # text we still recurse so nested headings/lists surface.
            child_blocks = list(getattr(text_block, "blocks", []) or [])
            if child_blocks:
                _flatten_blocks(child_blocks, out)
            continue

        # table_block: render a placeholder text from the caption +
        # row count. Downstream graph_extractor can re-render if it
        # cares, but we want to preserve presence + page span.
        table_block = getattr(blk, "table_block", None)
        if table_block is not None:
            caption = (getattr(table_block, "caption", "") or "").strip()
            header_rows = list(getattr(table_block, "header_rows", []) or [])
            body_rows = list(getattr(table_block, "body_rows", []) or [])
            rendered = _render_table(table_block)
            # Prefer materialised cell text (carries the numeric values the
            # diff needs); fall back to caption / shape placeholder if empty.
            if rendered:
                text = (caption + "\n" + rendered).strip() if caption else rendered
            else:
                text = caption or f"[table: {len(header_rows)}h x {len(body_rows)}b rows]"
            out.append(
                {
                    "text": text,
                    "layout_type": "table",
                    "page_start": ps,
                    "page_end": pe,
                    "raw": {
                        "kind": "table",
                        "header_row_count": len(header_rows),
                        "body_row_count": len(body_rows),
                    },
                }
            )
            continue

        # list_block: walk entries, recursing into each entry's blocks.
        list_block = getattr(blk, "list_block", None)
        if list_block is not None:
            entries = list(getattr(list_block, "list_entries", []) or [])
            for entry in entries:
                entry_blocks = list(getattr(entry, "blocks", []) or [])
                if entry_blocks:
                    # Mark these as list_item so downstream code can
                    # distinguish bullets from prose. We do this by
                    # temporarily collecting into a scratch list,
                    # rewriting the first emitted entry's layout_type
                    # to "list_item".
                    scratch: list[dict[str, Any]] = []
                    _flatten_blocks(entry_blocks, scratch)
                    if scratch:
                        scratch[0]["layout_type"] = "list_item"
                    out.extend(scratch)
            continue

        # image_block: emit a tiny stub so downstream code sees the
        # image's existence and page span.
        image_block = getattr(blk, "image_block", None)
        if image_block is not None:
            alt = (getattr(image_block, "image_text", "") or "").strip()
            out.append(
                {
                    "text": alt or "[image]",
                    "layout_type": "image",
                    "page_start": ps,
                    "page_end": pe,
                    "raw": {"kind": "image"},
                }
            )
            continue


def _document_to_flat(document: Any, page_offset: int = 0) -> list[dict[str, Any]]:
    """Convert a Doc AI ``Document`` into flat block dicts.

    ``page_offset`` is added to every page number so that blocks parsed
    from a split-out PDF part (whose own pages start at 1) carry their
    absolute page number in the original document.
    """
    flat: list[dict[str, Any]] = []
    layout = getattr(document, "document_layout", None)
    if layout is not None and getattr(layout, "blocks", None):
        _flatten_blocks(list(layout.blocks), flat)

    # Fallback: if document_layout is empty (some processor versions
    # only populate chunked_document), synthesise from chunks. Chunks
    # have no layout_type, so we tag them as "paragraph" and leave
    # heading detection to downstream graph_extractor.
    if not flat:
        chunked = getattr(document, "chunked_document", None)
        if chunked is not None:
            for ch in chunked.chunks or []:
                ps_obj = getattr(ch, "page_span", None)
                ps = _normalise_page(getattr(ps_obj, "page_start", 1) or 1)
                pe = _normalise_page(getattr(ps_obj, "page_end", ps) or ps)
                content = (getattr(ch, "content", "") or "").strip()
                if not content:
                    continue
                flat.append(
                    {
                        "text": content,
                        "layout_type": "paragraph",
                        "page_start": ps,
                        "page_end": pe,
                        "raw": {"kind": "chunk", "chunk_id": ch.chunk_id},
                    }
                )

    if page_offset:
        for sec in flat:
            sec["page_start"] += page_offset
            sec["page_end"] += page_offset
    return flat


def _pdf_page_count(raw_bytes: bytes) -> int:
    """Best-effort page count via pypdf. Returns 1 on any failure so the
    caller falls back to a single online call (which will surface the real
    Doc AI error if the document is genuinely oversized)."""
    try:
        import io

        from pypdf import PdfReader

        return len(PdfReader(io.BytesIO(raw_bytes)).pages)
    except Exception:  # noqa: BLE001 — count is advisory only
        return 1


def _split_pdf_pages(raw_bytes: bytes, start: int, end: int) -> bytes:
    """Return a new PDF containing 1-indexed pages [start, end] inclusive."""
    import io

    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(raw_bytes))
    writer = PdfWriter()
    for i in range(start - 1, min(end, len(reader.pages))):
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _process_bytes(client: Any, processor: str, raw_bytes: bytes) -> Any:
    """One online Doc AI Layout-Parser call over ``raw_bytes``."""
    request = documentai.ProcessRequest(
        name=processor,
        raw_document=documentai.RawDocument(
            content=raw_bytes,
            mime_type="application/pdf",
        ),
        process_options=documentai.ProcessOptions(
            layout_config=documentai.ProcessOptions.LayoutConfig(
                chunking_config=documentai.ProcessOptions.LayoutConfig.ChunkingConfig(
                    chunk_size=1000,
                    include_ancestor_headings=True,
                ),
            ),
        ),
    )
    return client.process_document(request=request).document


def _resolve_parent_headings(sections: list[dict[str, Any]]) -> None:
    """Walk forward, attaching the most-recent-heading's text to every
    subsequent non-heading chunk. In-place.
    """
    last_heading: str | None = None
    for sec in sections:
        if sec["layout_type"] in _HEADING_TYPES:
            last_heading = sec["text"]
            sec["parent_heading"] = None
        else:
            sec["parent_heading"] = last_heading


def parse_pdf(
    pdf_path: str | Path,
    doc_id: str,
    processor_id: str | None = None,
    location: str = "us",
    include_raw: bool = False,
) -> list[ChunkedSection]:
    """Send a PDF to Doc AI Layout Parser and return ordered chunks.

    Args:
        pdf_path: local filesystem path to a PDF.
        doc_id: stable identifier used to seed chunk_id.
        processor_id: full Doc AI processor resource name, e.g.
            ``projects/<num>/locations/us/processors/<id>``. If None,
            reads from env ``CURATOR_DOCAI_PROCESSOR_ID``.
        location: Doc AI location, default ``"us"`` (the only location
            where LAYOUT_PARSER_PROCESSOR is available).
        include_raw: when True, attach a small ``raw_layout`` dict to
            each chunk for debugging. Off by default to keep memory
            small.

    Returns:
        list[ChunkedSection] in reading order.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # Zero-cost bypass: if a pre-parsed sidecar exists for this PDF, use
    # it instead of a (slow, paid) live Doc AI call. The full document is
    # still ingested — only the re-parse is short-circuited. Judge-
    # uploaded novel PDFs have no sidecar and fall through to live Doc AI.
    from app.ingest.sidecar import load_sidecar_chunks

    sidecar_chunks = load_sidecar_chunks(pdf_path, doc_id)
    if sidecar_chunks is not None:
        return sidecar_chunks

    resolved_processor = processor_id or os.environ.get(_PROCESSOR_ENV_VAR)
    if not resolved_processor:
        raise RuntimeError(
            "No Doc AI processor configured. Pass processor_id= or set "
            f"{_PROCESSOR_ENV_VAR} (full resource name "
            "'projects/<num>/locations/us/processors/<id>')."
        )

    # The client uses a regional endpoint — Doc AI requires this.
    client_options = {"api_endpoint": f"{location}-documentai.googleapis.com"}
    client = documentai.DocumentProcessorServiceClient(client_options=client_options)

    with pdf_path.open("rb") as fh:
        raw_bytes = fh.read()

    # Doc AI's online endpoint hard-caps at 30 processed pages. For larger
    # documents, split into <=30-page parts, process each, and stitch with
    # an absolute page offset. Documents within the limit take the original
    # single-call path unchanged.
    page_count = _pdf_page_count(raw_bytes)
    max_pages = _max_doc_pages()
    if page_count > max_pages:
        import logging

        logging.getLogger(__name__).warning(
            "docai.parse_pdf: %s has %d pages; capping at CURATOR_DOCAI_MAX_PAGES=%d.",
            pdf_path.name,
            page_count,
            max_pages,
        )
        page_count = max_pages

    flat: list[dict[str, Any]] = []
    if page_count <= _ONLINE_PAGE_LIMIT:
        document = _process_bytes(client, resolved_processor, raw_bytes)
        flat = _document_to_flat(document)
    else:
        # Overlapping page batches so no block is truncated at a boundary.
        # ``step`` = pages each part *owns*; the part is processed with
        # ``overlap`` extra trailing pages of context (total <= 30). A block
        # is kept only by the part whose owned range contains its start page,
        # so the same block re-rendered as overlap in the next part is
        # dropped there — deterministic de-dup, no text matching.
        #
        # Parts are independent, so we fan them out across a bounded thread
        # pool (Doc AI calls are network-bound) and reassemble in page order.
        # This turns ~15 sequential calls for a 412-page doc into a handful
        # of concurrent batches. Bounded by CURATOR_DOCAI_CONCURRENCY to
        # stay under Doc AI's per-minute page quota.
        import logging
        from concurrent.futures import ThreadPoolExecutor

        log = logging.getLogger(__name__)
        overlap = min(_page_overlap(), _ONLINE_PAGE_LIMIT - 1)
        step = _ONLINE_PAGE_LIMIT - overlap
        parts = [
            (ps, min(ps + step - 1, page_count), min(ps + step - 1 + overlap, page_count))
            for ps in range(1, page_count + 1, step)
        ]
        log.info(
            "docai.parse_pdf: %s is %d pages; parsing in %d overlapping parts.",
            pdf_path.name,
            page_count,
            len(parts),
        )

        def _parse_part(spec: tuple[int, int, int]) -> list[dict[str, Any]]:
            primary_start, primary_end, process_end = spec
            part_bytes = _split_pdf_pages(raw_bytes, primary_start, process_end)
            document = _process_bytes(client, resolved_processor, part_bytes)
            part_flat = _document_to_flat(document, page_offset=primary_start - 1)
            kept = [
                sec
                for sec in part_flat
                if primary_start <= sec["page_start"] <= primary_end
            ]
            log.info(
                "docai.parse_pdf: %s part pages %d-%d done (%d blocks).",
                pdf_path.name,
                primary_start,
                primary_end,
                len(kept),
            )
            return kept

        concurrency = max(1, int(os.environ.get("CURATOR_DOCAI_CONCURRENCY", "4")))
        with ThreadPoolExecutor(max_workers=min(concurrency, len(parts))) as ex:
            # executor.map preserves input order → page order is correct.
            for part_flat in ex.map(_parse_part, parts):
                flat.extend(part_flat)

    _resolve_parent_headings(flat)

    results: list[ChunkedSection] = []
    for idx, sec in enumerate(flat):
        results.append(
            ChunkedSection(
                text=sec["text"],
                layout_type=sec["layout_type"],
                page_start=sec["page_start"],
                page_end=sec["page_end"],
                chunk_id=f"{doc_id}#chunk-{idx:04d}",
                parent_heading=sec.get("parent_heading"),
                raw_layout=sec["raw"] if include_raw else None,
            )
        )
    return results


__all__ = ["ChunkedSection", "parse_pdf"]
