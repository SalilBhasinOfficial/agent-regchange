"""Unit tests for truncated-JSON-array salvage in runners._coerce."""

from __future__ import annotations

import json

from app.runners import _salvage_truncated_array


def test_salvage_recovers_complete_objects():
    truncated = (
        '[{"parameter":"A","new_value":"40%"},'
        '{"parameter":"B","new_value":"30%"},'
        '{"parameter":"C","new_val'  # cut mid-row
    )
    out = _salvage_truncated_array(truncated)
    rows = json.loads(out)
    assert [r["parameter"] for r in rows] == ["A", "B"]


def test_salvage_ignores_braces_inside_strings():
    truncated = '[{"parameter":"risk } weight","new_value":"40%"},{"parameter":"X'
    rows = json.loads(_salvage_truncated_array(truncated))
    assert len(rows) == 1
    assert rows[0]["parameter"] == "risk } weight"


def test_salvage_returns_none_for_non_array():
    assert _salvage_truncated_array('{"not":"an array"}') is None


def test_salvage_returns_none_when_no_complete_object():
    assert _salvage_truncated_array('[{"parameter":"A') is None
