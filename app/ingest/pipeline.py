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


# Headings that are document structure, not the document's name. Title
# extraction must skip these (a TOC heading rendered first would otherwise
# become the title — observed as the literal title "Table of Contents").
_NON_TITLE_HEADINGS = frozenset(
    {
        "table of contents",
        "contents",
        "index",
        "annex",
        "annexure",
        "appendix",
        "preamble",
        "notification",
        "preliminary",
        "commencement",
        "short title",
        "short title and commencement",
        "powers exercised and commencement",
        "definitions",
        "introduction",
        "applicability",
        "scope of application",
        "powers exercised",
    }
)

# A heading that starts like a numbered/structural clause is not the document
# title: "2. Powers Exercised…", "Chapter I Preliminary", "Section 3", "Part A".
import re as _re

_STRUCTURAL_PREFIX = _re.compile(
    r"^\s*("
    r"\(?\d+(\.\d+)*[\.\)]\s|"  # 1.  2.3)  (2)  etc. — parenthesised too
    r"(chapter|section|part|clause|article|para(graph)?|schedule|annex(ure)?)\b"
    r")",
    _re.IGNORECASE,
)

# Words that signal an actual regulatory-document name.
_TITLE_KEYWORDS = (
    "direction",
    "circular",
    "regulation",
    "guideline",
    "framework",
    "master ",
    "act,",
    " act ",
    "reserve bank of india",
    "notification no",
)


# --- Filename prettifier (general fallback when no title is parseable) ------
# Some documents open with a preamble paragraph and never restate their own
# name as a heading (observed: a credit-risk SA Direction whose parsed text
# begins with the Basel-III preamble; the only title-like phrases in the body
# are cross-references to *other* directions). Rather than risk picking a wrong
# title from the body, derive a clean, honest title from the source filename —
# this generalises to any uploaded document, not just RBI ones.
_FN_TRAILING_HASH = _re.compile(r"[-_][0-9a-fA-F]{8,}$")
_FN_DATE = _re.compile(r"(20\d\d)[-_](\d{2})[-_](\d{2})")
_FN_LEAD_INDEX = _re.compile(r"^\d{1,3}[-_]")
# Letter-only boundaries: ``\b`` treats "_" as a word char, so ``\bRBI\b``
# fails in "..._RBI-hash". Look-arounds keyed on letters make digits, "_", "-"
# all act as separators.
_FN_SOURCE = _re.compile(
    r"(?<![A-Za-z])(RBI|SEBI|IRDAI|NABARD|NHB|PFRDA|FSSAI|MCA)(?![A-Za-z])",
    _re.IGNORECASE,
)
_FN_HEX_TOKEN = _re.compile(r"^[0-9a-fA-F]{6,}$")


def _prettify_filename(stem: str) -> str:
    """Turn a source filename stem into a readable, honest title.

    ``05_credit_risk_standardised_2026-04-27_RBI-087798ec1547``
        -> ``Credit Risk Standardised (RBI · 2026-04-27)``
    Best-effort: an opaque stem (``scan001``) degrades to ``Scan001``.
    """
    if not stem:
        return stem
    s = stem
    m_date = _FN_DATE.search(s)
    date = "-".join(m_date.groups()) if m_date else None
    m_src = _FN_SOURCE.search(s)
    src = m_src.group(1).upper() if m_src else None
    s = _FN_TRAILING_HASH.sub("", s)  # drop trailing content hash
    s = _FN_LEAD_INDEX.sub("", s)  # drop leading "05_" index
    s = _FN_DATE.sub(" ", s)  # remove the whole date token before splitting
    words = [w for w in _re.split(r"[-_\s]+", s) if w]
    keep: list[str] = []
    for w in words:
        if _FN_HEX_TOKEN.match(w):  # stray hash fragment
            continue
        if _re.fullmatch(r"\d{1,4}", w):  # leftover date/number fragments
            continue
        if _FN_SOURCE.fullmatch(w):  # source goes into the suffix instead
            continue
        keep.append(w[:1].upper() + w[1:] if w.islower() else w)
    name = " ".join(keep).strip()
    suffix = " · ".join(b for b in (src, date) if b)
    if name and suffix:
        return f"{name} ({suffix})"
    return name or stem


def _looks_like_title(text: str) -> bool:
    t = text.strip()
    # A real document title is a short noun phrase, not a sentence/paragraph.
    # Reject overly long strings so a body paragraph that happens to contain a
    # keyword ("...the Basel III framework...") can't be picked as the title.
    if len(t) < 10 or len(t) > 160:
        return False
    # A title is not a full sentence — document names never end in sentence
    # punctuation ("(2) These instructions shall come into effect from April
    # 01, 2027." was wrongly picked because the old length>80 guard missed it).
    if t.rstrip().endswith((".", ";")):
        return False
    low = t.lower().strip(" .:-")
    if low in _NON_TITLE_HEADINGS:
        return False
    # Materialised table (pipe rows) or a multi-line dump is not a title.
    if "|" in t or t.count("\n") > 1:
        return False
    # Numbered / structural clause headings are not the document name.
    if _STRUCTURAL_PREFIX.match(t):
        return False
    return True


def _title_from_chunks(chunks: list[ChunkedSection], fallback: str) -> str:
    """Pick the document's actual name as the title.

    Prefers a heading that reads like a regulatory-document name (contains
    "Directions", "Circular", "Reserve Bank of India"…); otherwise the first
    title-like heading. Skips front-matter (TOC, preliminary, definitions),
    numbered/structural clause headings, and materialised tables.
    """
    headings = [
        ch.text.strip()
        for ch in chunks[:40]
        if ch.layout_type in {"title", "subtitle", "heading-1", "heading-2"}
        and _looks_like_title(ch.text)
    ]
    # First choice: a heading that names a regulatory instrument.
    for h in headings:
        low = h.lower()
        if any(k in low for k in _TITLE_KEYWORDS):
            return h[:200]
    # Second: the first title-like heading.
    if headings:
        return headings[0][:200]
    # Fallback: first title-like non-table line, preferring keyword lines.
    candidates: list[str] = []
    for ch in chunks[:60]:
        if ch.layout_type == "table" or not ch.text.strip():
            continue
        line = ch.text.strip().splitlines()[0]
        if _looks_like_title(line):
            candidates.append(line)
    for c in candidates:
        if any(k in c.lower() for k in _TITLE_KEYWORDS):
            return c[:200]
    if candidates:
        return candidates[0][:200]
    # No parseable title in the document — derive a clean one from the filename
    # rather than exposing the raw stem (general, honest fallback).
    return _prettify_filename(fallback)


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
    try:
        from app.observability import progress as _progress

        _progress.set_stage("Building regulatory graph", total=2, unit="document")
    except Exception:  # noqa: BLE001
        _progress = None  # type: ignore[assignment]
    extraction_a = extract_graph(chunks_a, doc_id=doc_a_id, namespace=namespace)
    if _progress:
        _progress.bump()
    extraction_b = extract_graph(chunks_b, doc_id=doc_b_id, namespace=namespace)
    if _progress:
        _progress.bump()

    # ---- 3) Persist to Spanner (unless dry_run) ----
    if not dry_run:
        if _progress:
            _progress.set_stage("Writing graph to Spanner", total=2, unit="document")
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
        if _progress:
            _progress.bump()
        backend.ingest_document(
            doc_id=doc_b_id,
            namespace=namespace,
            source_pdf_path=str(pdf_b.resolve()),
            title=_title_from_chunks(chunks_b, fallback=pdf_b.stem),
            doc_kind=doc_b_kind,
            raw_text=_raw_text_from_chunks(chunks_b),
            clauses=extraction_b.clauses,
        )
        if _progress:
            _progress.bump()

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
        comparison_title=_title_from_chunks(chunks_b, fallback=pdf_b.stem),
        comparison_text=_raw_text_from_chunks(chunks_b),
        policies=policies,
    )


__all__ = ["ingest_two_pdfs"]
