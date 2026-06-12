"""Unit tests for the deterministic pre-diff gate."""

from __future__ import annotations

from dataclasses import dataclass

from app.ingest.prediff import (
    filter_unchanged_clauses,
    normalize_text,
    prediff,
    split_paragraphs,
)


def test_normalize_preserves_numbers_but_folds_cosmetics():
    a = normalize_text("Risk  weight  is  125%.")
    b = normalize_text("risk weight is 125%.")
    assert a == b  # whitespace + case folded
    # A numeric change must survive normalization (not be folded away).
    assert normalize_text("125%") != normalize_text("250%")


def test_smart_quotes_folded():
    assert normalize_text("the “bank’s” buffer") == normalize_text(
        'the "bank\'s" buffer'
    )


def test_split_paragraphs_blank_line_and_newline_fallback():
    assert split_paragraphs("a\n\nb\n\nc") == ["a", "b", "c"]
    # Single-newline blob falls back to line splitting.
    assert split_paragraphs("a\nb\nc") == ["a", "b", "c"]
    assert split_paragraphs("") == []


def test_prediff_exact_unchanged_skipped():
    old = ["para one", "para two", "para three"]
    new = ["para one", "para two CHANGED 250%", "para three"]
    r = prediff(old, new, mode="exact")
    assert r.total_new == 3
    assert r.unchanged == 2
    assert r.changed_new == 1
    assert r.modified == 1


def test_prediff_added_and_removed():
    old = ["a", "b", "c"]
    new = ["a", "c", "d"]  # b removed, d added
    r = prediff(old, new, mode="exact")
    assert r.unchanged == 2  # a, c
    assert r.added == 1  # d
    assert r.removed == 1  # b


def test_numeric_change_is_never_unchanged():
    old = ["Listed equity exposures attract a risk weight of 125%."]
    new = ["Listed equity exposures attract a risk weight of 250%."]
    r = prediff(old, new, mode="exact")
    assert r.unchanged == 0
    assert r.modified == 1
    blob = r.changed_blob(10_000)
    assert "125%" in blob and "250%" in blob  # both sides visible to the LLM


def test_similarity_mode_pairs_moved_reworded_paragraph():
    # The reworded paragraph also MOVES (end of doc), so SequenceMatcher emits
    # an orphan delete + orphan insert rather than a 1:1 replace. Exact mode
    # leaves them as added + removed; similarity re-pairs them as modified.
    old = [
        "common opening",
        "the corporate unrated exposure risk weight shall be one hundred percent",
        "common closing",
    ]
    new = [
        "common opening",
        "common closing",
        "risk weight for unrated corporate exposures is one hundred percent flat",
    ]
    r_exact = prediff(old, new, mode="exact")
    assert r_exact.unchanged == 2
    assert r_exact.added == 1 and r_exact.removed == 1
    r_sim = prediff(old, new, mode="similarity", threshold=0.3)
    assert r_sim.unchanged == 2
    assert r_sim.modified == 1
    assert r_sim.removed == 0


@dataclass
class _Clause:
    new_text: str


def test_filter_unchanged_clauses_drops_only_identical():
    comparison = "alpha clause text\n\nbeta clause text\n\ngamma clause text"
    clauses = [
        _Clause("alpha clause text"),  # identical → dropped
        _Clause("beta clause text CHANGED to 40%"),  # numeric change → kept
        _Clause("brand new clause"),  # absent in prior → kept
    ]
    kept, dropped = filter_unchanged_clauses(clauses, comparison)
    assert dropped == 1
    assert len(kept) == 2
    assert all("alpha clause text" != c.new_text for c in kept)


def test_filter_no_comparison_is_noop():
    clauses = [_Clause("x"), _Clause("y")]
    kept, dropped = filter_unchanged_clauses(clauses, None)
    assert dropped == 0 and len(kept) == 2
