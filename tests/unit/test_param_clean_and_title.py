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


def test_clean_keeps_new_and_removed_with_equal_or_null_values():
    rows = [
        _pc("New buffer", None, "2.5%", "new"),
        _pc("Old levy", "1%", "0%", "removed"),
    ]
    out = _clean_param_changes(rows)
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


def test_title_falls_back_when_no_real_heading():
    chunks = [_chunk("Index", layout="heading-1")]
    assert _title_from_chunks(chunks, "the-fallback") == "the-fallback"


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
