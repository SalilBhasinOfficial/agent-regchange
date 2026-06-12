"""Pre-parsed sidecar loader — a zero-cost Doc AI bypass for known docs.

The four RBI demo PDFs each ship with a pre-parsed ``<stem>.html.json``
sidecar in ``inout/`` (a structured ``chapters`` extraction of the full
document, including the 412-page capital-adequacy master direction).
Re-running Doc AI Layout Parser on those at demo time would cost ~$10/1k
pages and minutes of wall-clock; the sidecar gives the *same full
document* in milliseconds for $0.

Activation
----------
``parse_pdf`` calls :func:`load_sidecar_chunks` first. If a sidecar for
the PDF's filename stem exists under ``CURATOR_SIDECAR_DIR`` (default
``inout``), its chapters are converted to ``ChunkedSection`` records and
returned — no Doc AI call. If no sidecar exists (e.g. a judge uploads a
novel PDF), the function returns ``None`` and ``parse_pdf`` falls
through to live Doc AI. Set ``CURATOR_DISABLE_SIDECAR=1`` to force live
Doc AI for everything.

This keeps the demo honest: the *full* document is genuinely ingested
into Spanner Graph; only the expensive re-parse is short-circuited. The
"re-run live" path in the UI can force a real Doc AI parse.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

LOGGER = logging.getLogger(__name__)

# Committed, IP-clean sidecars live under app/data/sidecars (shipped in
# the Docker image). inout/ is the dev-only superset.
_DEFAULT_DIR = "app/data/sidecars"


def _sidecar_path(pdf_path: Path) -> Path | None:
    if os.environ.get("CURATOR_DISABLE_SIDECAR", "0").strip().lower() in {"1", "true", "yes", "on"}:
        return None
    base_dir = Path(os.environ.get("CURATOR_SIDECAR_DIR", _DEFAULT_DIR))
    if not base_dir.is_absolute():
        # Resolve relative to the repo root (two levels up from this file).
        base_dir = Path(__file__).resolve().parents[2] / base_dir
    cand = base_dir / f"{pdf_path.stem}.html.json"
    return cand if cand.exists() else None


def has_sidecar(pdf_path: Path | str) -> bool:
    return _sidecar_path(Path(pdf_path)) is not None


def load_sidecar_chunks(pdf_path: Path | str, doc_id: str):  # type: ignore[no-untyped-def]
    """Return ``list[ChunkedSection]`` from the sidecar, or ``None``.

    Converts the sidecar's ``chapters`` (each: heading + paragraphs +
    tables) into the same ChunkedSection shape Doc AI would emit, so the
    downstream graph extractor is identical whether the source was a
    live parse or a sidecar.
    """
    path = _sidecar_path(Path(pdf_path))
    if path is None:
        return None

    # Late import to avoid a cycle (docai imports this module).
    from app.ingest.docai import ChunkedSection

    try:
        data = json.loads(path.read_text())
    except Exception as e:  # noqa: BLE001
        LOGGER.warning("sidecar parse failed (%s): %s", path, e)
        return None

    chapters = data.get("chapters") or []
    chunks: list[ChunkedSection] = []
    ordinal = 0

    def _emit(text: str, layout_type: str, heading: str | None) -> None:
        nonlocal ordinal
        text = (text or "").strip()
        if not text:
            return
        chunks.append(
            ChunkedSection(
                text=text,
                layout_type=layout_type,
                page_start=1,
                page_end=1,
                chunk_id=f"{doc_id}#chunk-{ordinal:04d}",
                parent_heading=heading,
            )
        )
        ordinal += 1

    for ch in chapters:
        if not isinstance(ch, dict):
            continue
        heading = (ch.get("heading") or ch.get("title") or "").strip() or None
        if heading:
            _emit(heading, "heading-1", None)
        for para in ch.get("paragraphs") or []:
            if isinstance(para, dict):
                _emit(para.get("text", ""), "paragraph", heading)
            elif isinstance(para, str):
                _emit(para, "paragraph", heading)
        for tbl in ch.get("tables") or []:
            # Tables carry their own text rendering in most sidecars; fall
            # back to a JSON dump so no content is silently dropped.
            if isinstance(tbl, dict):
                t = tbl.get("text") or tbl.get("markdown") or json.dumps(tbl)[:4000]
                _emit(t, "table", heading)

    if not chunks:
        LOGGER.info("sidecar %s had no usable chapters", path)
        return None

    LOGGER.info("sidecar hit: %s → %d chunks (Doc AI bypassed)", path.name, len(chunks))
    return chunks


__all__ = ["has_sidecar", "load_sidecar_chunks"]
