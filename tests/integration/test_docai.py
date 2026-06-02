"""Live Document AI Layout Parser integration test.

Hard-skipped at module collection time when ``CURATOR_LIVE_GCP != "1"``.
This avoids billable API calls during the default test run and prevents
``pytest`` from even importing the module's expensive dependencies.

Run live with:
    source scripts/env.sh
    CURATOR_LIVE_GCP=1 \\
    CURATOR_DOCAI_PROCESSOR_ID=projects/<num>/locations/us/processors/<id> \\
    uv run pytest tests/integration/test_docai.py -q
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

if os.environ.get("CURATOR_LIVE_GCP", "0") != "1":
    pytest.skip(
        "Set CURATOR_LIVE_GCP=1 to run live Document AI integration tests",
        allow_module_level=True,
    )

# Imports below are deferred until after the skip-gate so that even
# missing GCP credentials don't break test collection.
from app.ingest.docai import ChunkedSection, parse_pdf  # noqa: E402

# Repo-relative path to the fixture PDF. We resolve via __file__ so the
# test is location-independent.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_PDF = (
    _REPO_ROOT
    / "data"
    / "fixtures"
    / "source_pdfs"
    / "02_second_amendment_2026-02-13_RBI-dbecd9fe73f6.pdf"
)


# Layout labels that count as headings for the "at least one heading"
# assertion. Doc AI's exact label has shifted across versions, so we
# stay permissive.
_HEADING_LIKE = {
    "heading-1",
    "heading-2",
    "heading-3",
    "heading-4",
    "heading-5",
    "subtitle",
    "title",
    "section_heading",
    "heading",
}


def test_parse_02_amendment_smoke() -> None:
    """Smoke: parse the second-amendment fixture and sanity-check the chunks."""
    assert _FIXTURE_PDF.exists(), f"missing fixture: {_FIXTURE_PDF}"

    chunks = parse_pdf(pdf_path=_FIXTURE_PDF, doc_id="rbi-amend-02")

    assert isinstance(chunks, list), "parse_pdf should return a list"
    assert all(isinstance(c, ChunkedSection) for c in chunks), (
        "every entry must be a ChunkedSection"
    )

    # 1.3 MB amendment PDF will produce many chunks.
    assert len(chunks) >= 5, f"expected >=5 chunks from a 1.3 MB PDF, got {len(chunks)}"

    # Every chunk has non-empty text.
    for c in chunks:
        assert c.text and c.text.strip(), f"empty text in chunk {c.chunk_id}"

    # At least one heading-like chunk.
    heading_chunks = [c for c in chunks if c.layout_type in _HEADING_LIKE]
    assert heading_chunks, (
        "expected at least one heading-like chunk; got layout_types: "
        f"{sorted({c.layout_type for c in chunks})}"
    )

    # Chunk IDs are unique.
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids)), "duplicate chunk_id detected"

    # Chunk IDs are stable across a second run.
    chunks_again = parse_pdf(pdf_path=_FIXTURE_PDF, doc_id="rbi-amend-02")
    ids_again = [c.chunk_id for c in chunks_again]
    assert ids == ids_again, "chunk_ids are not stable across runs"

    # Page numbers are sensible.
    for c in chunks:
        assert c.page_start >= 1, f"{c.chunk_id}: page_start < 1 ({c.page_start})"
        assert c.page_end >= c.page_start, (
            f"{c.chunk_id}: page_end {c.page_end} < page_start {c.page_start}"
        )
