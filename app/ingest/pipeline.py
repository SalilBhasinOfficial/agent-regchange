"""Two-PDF ingestion orchestrator.

Given an amendment PDF (e.g. RBI Second Amendment) and a Master Direction
PDF, this module:

    1. Parses both PDFs via Document AI Layout Parser (``docai.parse_pdf``).
    2. Extracts deterministic clauses + (optionally) LLM-derived entities
       and relations (``graph_extractor.extract_graph``).
    3. Persists both documents into Spanner via
       ``SpannerGraphBackend.ingest_document`` (skippable with
       ``dry_run=True``).
    4. Constructs the ``AgentState`` that the existing 5-step debated
       chain consumes: ``amendment``, ``amended_clauses``, ``policies``.

The function is the *entry point* the D4-D5 wiring points at. The chain
itself (``app/chain.py``) is intentionally left untouched in D4 — the
demo path still flows through ``MockGroundingBackend`` until D5 wires
``ingest_two_pdfs`` in.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.grounding import MockGroundingBackend, SpannerGraphBackend
from app.ingest.docai import ChunkedSection, parse_pdf
from app.ingest.graph_extractor import (
    ExtractedClause,
    GraphExtractionResult,
    extract_graph,
)
from app.models import AgentState, AmendedClause, AmendmentInput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_NON_SLUG = re.compile(r"[^a-z0-9]+")


def _doc_id_from_path(path: Path) -> str:
    """Derive a stable doc_id from a PDF filename.

    Example:
        ``02_second_amendment_2026-02-13_RBI-dbecd9fe73f6.pdf``
            -> ``02-second-amendment-2026-02-13-rbi-dbecd9fe73f6``
    """
    stem = path.stem.lower()
    slug = _NON_SLUG.sub("-", stem).strip("-")
    return slug


def _amended_clauses_from_extraction(
    extraction: GraphExtractionResult, md_id: str
) -> list[AmendedClause]:
    """Convert ``ExtractedClause`` → ``AmendedClause`` for the chain."""
    out: list[AmendedClause] = []
    for c in extraction.clauses:
        # Skip clauses with no text — they'd add noise to the decompose
        # panel without value.
        if not (c.new_text or "").strip():
            continue
        change_type = c.change_type if c.change_type in (
            "insert",
            "modify",
            "delete",
            "renumber",
        ) else "modify"
        out.append(
            AmendedClause(
                clause_id=c.clause_id,
                md_id=md_id,
                heading=c.heading,
                old_text=c.old_text,
                new_text=c.new_text,
                change_type=change_type,  # type: ignore[arg-type]
            )
        )
    return out


def _raw_text_from_chunks(chunks: list[ChunkedSection]) -> str:
    return "\n\n".join(c.text for c in chunks if c.text)


def _title_from_chunks(chunks: list[ChunkedSection], fallback: str) -> str:
    """Pick the first heading-typed chunk's text as the document title."""
    for ch in chunks:
        if ch.layout_type in {"title", "subtitle", "heading-1"} and ch.text.strip():
            return ch.text.strip()
    # Fallback: first non-empty chunk.
    for ch in chunks:
        if ch.text.strip():
            return ch.text.strip().splitlines()[0][:200]
    return fallback


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def ingest_two_pdfs(
    pdf_a: Path | str,
    pdf_b: Path | str,
    namespace: str,
    *,
    doc_a_kind: str = "amendment",
    doc_b_kind: str = "master_direction",
    dry_run: bool = False,
    bank_id: str = "demo",
) -> AgentState:
    """Ingest an (amendment, master_direction) pair and return an AgentState.

    Args:
        pdf_a: amendment PDF (the change notification).
        pdf_b: master direction PDF (the canonical document being amended).
        namespace: tenant / demo namespace tag persisted with the docs.
        doc_a_kind / doc_b_kind: ``documents.doc_kind`` values.
        dry_run: when True, skip Spanner writes (orchestrator-only test
            mode). Doc AI is still called — caller must arrange a mock
            or set ``CURATOR_LIVE_GCP=0`` and stub via the test.
        bank_id: passed to ``load_bank_policies``; defaults to ``"demo"``.

    Returns:
        ``AgentState`` populated with ``amendment``, ``amended_clauses``,
        and ``policies``. Downstream sub-agents (decompose / map / diff /
        judge / qna) consume this state directly.
    """
    pdf_a = Path(pdf_a)
    pdf_b = Path(pdf_b)
    if not pdf_a.exists():
        raise FileNotFoundError(f"amendment PDF not found: {pdf_a}")
    if not pdf_b.exists():
        raise FileNotFoundError(f"master direction PDF not found: {pdf_b}")

    doc_a_id = _doc_id_from_path(pdf_a)
    doc_b_id = _doc_id_from_path(pdf_b)

    # ---- 1) Doc AI parse both PDFs ----
    chunks_a = parse_pdf(pdf_path=pdf_a, doc_id=doc_a_id)
    chunks_b = parse_pdf(pdf_path=pdf_b, doc_id=doc_b_id)

    # ---- 2) Graph extraction (deterministic clauses + optional LLM graph) ----
    extraction_a = extract_graph(chunks_a, doc_id=doc_a_id, namespace=namespace)
    extraction_b = extract_graph(chunks_b, doc_id=doc_b_id, namespace=namespace)

    # ---- 3) Persist to Spanner (unless dry_run) ----
    if not dry_run:
        backend = SpannerGraphBackend()
        backend.ingest_document(
            doc_id=doc_a_id,
            namespace=namespace,
            source_pdf_path=str(pdf_a.resolve()),
            title=_title_from_chunks(chunks_a, fallback=pdf_a.stem),
            doc_kind=doc_a_kind,
            raw_text=_raw_text_from_chunks(chunks_a),
            clauses=extraction_a.clauses,
        )
        backend.ingest_document(
            doc_id=doc_b_id,
            namespace=namespace,
            source_pdf_path=str(pdf_b.resolve()),
            title=_title_from_chunks(chunks_b, fallback=pdf_b.stem),
            doc_kind=doc_b_kind,
            raw_text=_raw_text_from_chunks(chunks_b),
            clauses=extraction_b.clauses,
        )

    # ---- 4) Build the AgentState ----
    amended_clauses = _amended_clauses_from_extraction(extraction_a, md_id=doc_b_id)
    amendment = AmendmentInput(
        amendment_id=doc_a_id,
        master_direction_id=doc_b_id,
        title=_title_from_chunks(chunks_a, fallback=pdf_a.stem),
        effective_date=None,
        notification_url=None,
        raw_text=_raw_text_from_chunks(chunks_a),
    )

    # Policies: for D4 we always source policies from the Mock backend
    # (bank policies aren't part of the two-PDF input). SpannerGraphBackend
    # delegates to MockGroundingBackend internally for ``load_bank_policies``
    # — we go through it explicitly so a future D5 swap works uniformly.
    if dry_run:
        policies = MockGroundingBackend().load_bank_policies(bank_id=bank_id)
    else:
        policies = SpannerGraphBackend().load_bank_policies(bank_id=bank_id)

    return AgentState(
        amendment=amendment,
        amended_clauses=amended_clauses,
        policies=policies,
    )


__all__ = ["ingest_two_pdfs"]
