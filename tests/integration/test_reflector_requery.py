"""Tests for ``reflector.reflect_and_requery`` — the D4 Spanner Graph hook.

Two cases:

  * High-confidence obligations with no missing-evidence cues → no
    re-query, empty extra_context returned.
  * Low-confidence obligations with cues → grounding mock's
    ``query_graph_neighborhood`` is called with the anchor clause and
    cues, and its return value is forwarded verbatim.

These tests deliberately don't touch Spanner. Track 1's
``SpannerGraphBackend`` ships independently; this module only verifies
the contract that the reflector calls the right method with the right
arguments.
"""

from __future__ import annotations

from app.models import DeonticType, Obligation
from app.sub_agents.reflector import reflect_and_requery


def _obl(
    idx: int,
    *,
    confidence: float,
    clause_id: str = "MD-RBI-TEST#1",
    missing: list[str] | None = None,
) -> Obligation:
    return Obligation(
        id=f"obl-{idx}",
        source_clause_id=clause_id,
        deontic_type=DeonticType.MUST,
        subject="bank",
        action=f"do thing {idx}",
        confidence=confidence,
        missing_evidence=missing or [],
    )


class _RecordingGrounding:
    """Minimal stand-in for the SpannerGraphBackend grounding contract."""

    def __init__(self, return_value: list[dict] | None = None) -> None:
        self.return_value = return_value if return_value is not None else []
        self.calls: list[dict] = []

    def query_graph_neighborhood(
        self,
        *,
        node_id: str,
        depth: int,
        requeries: list[str],
    ) -> list[dict]:
        self.calls.append(
            {"node_id": node_id, "depth": depth, "requeries": list(requeries)}
        )
        return self.return_value


def test_reflect_and_requery_no_op_on_high_confidence():
    """High-confidence + no cues → no re-query, empty extra_context."""
    obls = [
        _obl(i, confidence=0.9, clause_id="MD-RBI-CAP-2025#11.5A")
        for i in range(3)
    ]
    grounding = _RecordingGrounding(return_value=[{"unexpected": True}])

    decision, extra = reflect_and_requery(
        obls, namespace="demo", grounding=grounding
    )

    # D2 always escalates=True; the existing reflect() contract.
    assert decision.escalate is True
    assert decision.aggregate_confidence >= 0.6
    assert decision.requeries == []
    # No re-query because confidence is fine and there are no cues.
    assert grounding.calls == [], (
        "grounding.query_graph_neighborhood must NOT be called on high-confidence"
    )
    assert extra == []


def test_reflect_and_requery_calls_grounding_when_low_conf():
    """Low confidence + missing-evidence cues → grounding called, dicts forwarded."""
    # Two obligations: the second is the weakest link and should anchor
    # the re-query. Both contribute a distinct missing_evidence cue.
    obls = [
        _obl(
            1,
            confidence=0.5,
            clause_id="MD-RBI-CAP-2025#11.5A",
            missing=["effective date"],
        ),
        _obl(
            2,
            confidence=0.3,
            clause_id="MD-RBI-CAP-2025#11.5B",
            missing=["implementation guidance", "not_seen_by:auditor"],
        ),
    ]
    expected_context = [
        {"node_id": "MD-RBI-CAP-2025#11.5B", "neighbor": "MD-RBI-CAP-2025#11.5C"},
        {"node_id": "MD-RBI-CAP-2025#11.5B", "neighbor": "MD-RBI-CAP-2025#11.5D"},
    ]
    grounding = _RecordingGrounding(return_value=expected_context)

    decision, extra = reflect_and_requery(
        obls, namespace="demo", grounding=grounding
    )

    # The reflect() decision should aggregate the two confidences (avg 0.4)
    # and surface the two non-mechanical cues.
    assert decision.aggregate_confidence == 0.4
    assert "effective date" in decision.requeries
    assert "implementation guidance" in decision.requeries
    assert "not_seen_by:auditor" not in decision.requeries

    # Grounding must have been called exactly once with the weakest-link
    # clause as the anchor and the same requery cues.
    assert len(grounding.calls) == 1, f"expected 1 grounding call, got {len(grounding.calls)}"
    call = grounding.calls[0]
    assert call["node_id"] == "MD-RBI-CAP-2025#11.5B"
    assert call["depth"] == 2
    assert "effective date" in call["requeries"]
    assert "implementation guidance" in call["requeries"]

    # And the returned dicts must be forwarded verbatim.
    assert extra == expected_context


def test_reflect_and_requery_degrades_on_grounding_exception():
    """If the grounding method raises, return empty extra_context (best-effort)."""

    class _BrokenGrounding:
        def query_graph_neighborhood(self, **_kw):
            raise RuntimeError("simulated Spanner outage")

    obls = [
        _obl(1, confidence=0.3, missing=["effective date"]),
    ]
    decision, extra = reflect_and_requery(
        obls, namespace="demo", grounding=_BrokenGrounding()
    )
    assert decision.aggregate_confidence == 0.3
    assert extra == [], "broken grounding must degrade silently to []"


def test_reflect_and_requery_handles_missing_method():
    """If the grounding backend lacks the method, return [] without raising."""

    class _MockOnly:
        pass  # no query_graph_neighborhood

    obls = [_obl(1, confidence=0.3, missing=["effective date"])]
    decision, extra = reflect_and_requery(
        obls, namespace="demo", grounding=_MockOnly()
    )
    assert decision.aggregate_confidence == 0.3
    assert extra == []
