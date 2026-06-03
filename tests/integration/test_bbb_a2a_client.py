"""Tests for the A2A bridge to the bbb MCP gateway.

Two offline tests always run (no env var needed):

  * unset bearer → ``is_enabled()`` False and ``regulatory_deep_lookup``
    returns ``[]`` without making a network call.
  * response shapes → ``_coerce_result`` flattens both legacy and
    MCP-content-wrapped JSON-RPC reply shapes.

One live test hard-skips when ``BBB_MCP_BEARER`` is unset; when set it
asserts a non-empty list comes back from the real endpoint.
"""

from __future__ import annotations

import os

import pytest

from app.tools.bbb_a2a_client import (
    _coerce_result,
    is_enabled,
    regulatory_deep_lookup,
)


def test_disabled_when_no_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BBB_MCP_BEARER", raising=False)
    assert is_enabled() is False
    # Must not raise, must not hit the network, must return [].
    assert regulatory_deep_lookup("anything", k=3) == []


def test_coerce_result_shapes() -> None:
    # Direct list under "result"
    assert _coerce_result({"result": [{"title": "a"}, {"title": "b"}]}, k=5) == [
        {"title": "a"},
        {"title": "b"},
    ]

    # MCP content-wrapped json envelope
    wrapped = {
        "result": {
            "content": [
                {"type": "json", "json": [{"title": "c"}, {"title": "d"}, {"title": "e"}]}
            ]
        }
    }
    assert _coerce_result(wrapped, k=2) == [{"title": "c"}, {"title": "d"}]

    # Malformed → []
    assert _coerce_result({"error": "boom"}, k=5) == []
    assert _coerce_result({"result": {"content": "not-a-list"}}, k=5) == []


@pytest.mark.skipif(
    not os.environ.get("BBB_MCP_BEARER"),
    reason="BBB_MCP_BEARER not set — skipping live A2A bridge call",
)
def test_live_lookup_returns_nonempty() -> None:
    snippets = regulatory_deep_lookup("RBI capital adequacy disclosures", k=3)
    assert isinstance(snippets, list)
    # The remote gateway may legitimately return zero rows for an obscure
    # query, but for this canonical topic we expect at least one row.
    assert len(snippets) >= 1
    assert all(isinstance(s, dict) for s in snippets)
