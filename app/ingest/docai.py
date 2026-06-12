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

    request = documentai.ProcessRequest(
        name=resolved_processor,
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

    result = client.process_document(request=request)
    document = result.document

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
