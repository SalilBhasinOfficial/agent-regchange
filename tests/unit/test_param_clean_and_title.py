"""Unit tests for param-diff cleaning + title extraction guards."""

from __future__ import annotations

from app.ingest.docai import ChunkedSection
from app.ingest.pipeline import _title_from_chunks
from app.models import ParameterChange
from app.sub_agents.param_diff import _clean_param_changes


def _pc(parameter, old, new, direction):
    return ParameterChange(
        parameter=parameter, old_value=old, new_value=new, direction=direction
    )


def test_clean_drops_unchanged_rows():
    rows = [
        _pc("CET1 ratio", "5.5%", "5.5%", "unchanged"),
        _pc("Equity RW", "125%", "250%", "increase"),
    ]
    out = _clean_param_changes(rows)
    assert [r.parameter for r in out] == ["Equity RW"]


def test_clean_drops_equal_old_new_even_if_not_labelled_unchanged():
    rows = [_pc("Tier 1", "9%", "9%", "increase")]  # mislabelled, old==new
    assert _clean_param_changes(rows) == []


def test_clean_keeps_new_rows_without_prior_text():
    # Cannot verify "new" rows without the prior framework text → keep them all
    # (a brand-new-table amendment must not be blanked).
    rows = [
        _pc("Add-on factor A", None, "0.25", "new"),
        _pc("Add-on factor B", None, "0.50", "new"),
    ]
    out = _clean_param_changes(rows)
    assert len(out) == 2


def test_clean_drops_restatements_present_in_prior_but_keeps_genuine_new():
    # Evidence-based: a null-old "new" row whose concept already appears in the
    # prior text is a restatement (drop); one whose concept is absent is
    # genuinely new (keep). Movements and prior-citing rows always survive.
    prior = "The risk weight for Central Government exposures shall be 0%."
    rows = [
        _pc("Risk weight — Central Government", None, "0%", "new"),  # in prior → drop
        _pc("Risk weight — Startup ventures", None, "150%", "new"),  # absent → keep
        _pc("Equity RW", "125%", "250%", "increase"),  # movement → keep
        _pc("Old levy", "1%", "0%", "removed"),  # cites prior value → keep
    ]
    out = _clean_param_changes(rows, comparison_text=prior)
    params = {r.parameter for r in out}
    assert "Risk weight — Central Government" not in params
    assert "Risk weight — Startup ventures" in params
    assert "Equity RW" in params
    assert "Old levy" in params


def test_clean_empty_guard_keeps_all_when_everything_is_a_restatement():
    # capad case: prior (post-amendment master) contains every concept, so all
    # rows look like restatements — the empty-guard keeps them rather than blank.
    prior = "add-on factor for market related off balance sheet items table"
    rows = [
        _pc("Add-on factor market related off balance sheet", None, "0.25", "new"),
        _pc("Add-on factor market related off balance sheet items", None, "0.50", "new"),
    ]
    out = _clean_param_changes(rows, comparison_text=prior)
    assert len(out) == 2


def test_clean_dedupes():
    rows = [
        _pc("Equity RW", "125%", "250%", "increase"),
        _pc("equity rw", "125%", "250%", "increase"),  # case-insensitive dup
    ]
    assert len(_clean_param_changes(rows)) == 1


def _chunk(text, layout="heading-1"):
    return ChunkedSection(
        text=text, layout_type=layout, page_start=1, page_end=1, chunk_id="c"
    )


def test_title_skips_table_of_contents():
    chunks = [
        _chunk("Table of Contents"),
        _chunk("Master Direction - Prudential Norms on Capital Adequacy"),
    ]
    assert _title_from_chunks(chunks, "fb") == (
        "Master Direction - Prudential Norms on Capital Adequacy"
    )


def test_title_skips_materialised_table():
    chunks = [
        _chunk("| A | B |\n| 1 | 2 |", layout="table"),
        _chunk("Reserve Bank of India Directions, 2026"),
    ]
    assert _title_from_chunks(chunks, "fb") == "Reserve Bank of India Directions, 2026"


def test_title_skips_parenthesised_clause_sentence():
    # "(2) These instructions shall come into effect from April 01, 2027."
    # was wrongly picked as the creditrisk demo title — a parenthesised
    # sub-clause sentence, not the document name.
    chunks = [
        _chunk("(2) These instructions shall come into effect from April 01, 2027."),
        _chunk("Master Circular – Basel III Capital Regulations"),
    ]
    assert _title_from_chunks(chunks, "fb") == (
        "Master Circular – Basel III Capital Regulations"
    )


def test_title_falls_back_to_prettified_filename_when_no_real_heading():
    # No parseable title → derive a readable title from the filename stem
    # rather than exposing the raw stem (general, honest fallback).
    chunks = [_chunk("Index", layout="heading-1")]
    assert _title_from_chunks(chunks, "the-fallback") == "The Fallback"


def test_title_prettifies_rbi_filename_stem():
    from app.ingest.pipeline import _prettify_filename

    assert _prettify_filename(
        "05_credit_risk_standardised_2026-04-27_RBI-087798ec1547"
    ) == "Credit Risk Standardised (RBI · 2026-04-27)"


def test_apply_finalization_drops_excluded_and_corrects():
    from app.models import (
        AgentState,
        AmendmentInput,
        Finalization,
        ImpactSummary,
        ParameterChange,
    )
    from app.sub_agents.finalize import apply_finalization

    st = AgentState(
        amendment=AmendmentInput(
            amendment_id="x", master_direction_id="y", title="T", raw_text="r"
        )
    )
    st.param_changes = [
        ParameterChange(parameter="Table of Contents", old_value=None, new_value="5", direction="new"),
        ParameterChange(parameter="Equity RW", old_value="125%", new_value="250%", direction="increase"),
    ]
    st.impact = ImpactSummary(impact_score=0.9, priority="critical", summary="old")
    apply_finalization(
        st,
        Finalization(
            excluded_parameters=["Table of Contents"],
            corrected_priority="high",
            true_and_fair_summary="Balanced final view.",
            changes_made=["Excluded TOC row"],
        ),
    )
    assert [p.parameter for p in st.param_changes] == ["Equity RW"]
    assert st.impact.priority == "high"
    assert st.impact.summary == "Balanced final view."
    assert st.finalization is not None


def test_audit_calibration_severity_based_verdict():
    from app.models import AuditFinding, AuditReport
    from app.sub_agents.audit import _calibrate_verdict

    def rpt(severities):
        return AuditReport(
            verdict="review",  # wrong on purpose — override should fix it
            publishable=False,
            compliance_summary="c",
            audit_summary="a",
            findings=[
                AuditFinding(severity=s, category="data_quality", item="i", detail="d")
                for s in severities
            ],
            confidence=0.9,
        )

    # info/minor only → pass, publishable
    r = _calibrate_verdict(rpt(["info", "minor"]))
    assert r.verdict == "pass" and r.publishable is True
    # any major (no blocker) → review, still publishable
    r = _calibrate_verdict(rpt(["minor", "major"]))
    assert r.verdict == "review" and r.publishable is True
    # any blocker → fail, not publishable
    r = _calibrate_verdict(rpt(["major", "blocker"]))
    assert r.verdict == "fail" and r.publishable is False
    # no findings → pass
    r = _calibrate_verdict(rpt([]))
    assert r.verdict == "pass" and r.publishable is True
