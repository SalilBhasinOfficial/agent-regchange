"""Reconciler must not collapse distinct obligations that share vocabulary."""

from __future__ import annotations

from app.models import DeonticType, Obligation
from app.sub_agents.reconciler import _normalize_action, reconcile_obligations


def _ob(oid, clause, action, conf=0.8):
    return Obligation(
        id=oid,
        source_clause_id=clause,
        deontic_type=DeonticType("must"),
        subject="bank",
        action=action,
        confidence=conf,
        missing_evidence=[],
    )


def test_normalize_keeps_distinct_deadlines_apart():
    # Differing only in the number — must NOT collide.
    a = _normalize_action("report the breach within 6 hours")
    b = _normalize_action("report the breach within 24 hours")
    assert a != b


def test_normalize_keeps_distinct_objects_apart():
    a = _normalize_action("obtain customer consent before sharing data")
    b = _normalize_action("obtain customer consent before cross-selling insurance")
    assert a != b


def test_reconcile_does_not_merge_distinct_obligations_same_clause():
    lens_outputs = {
        "banker": [
            _ob("o1", "c#1", "report the breach within 6 hours"),
            _ob("o2", "c#1", "report the breach within 24 hours"),
        ]
    }
    out = reconcile_obligations(lens_outputs)
    assert len(out) == 2  # two distinct deadlines stay separate


def test_reconcile_merges_same_duty_across_lenses():
    # Same clause, same duty paraphrased → collapses to one.
    lens_outputs = {
        "banker": [_ob("o1", "c#1", "maintain the capital conservation buffer")],
        "compliance": [_ob("o2", "c#1", "maintain a capital conservation buffer")],
    }
    out = reconcile_obligations(lens_outputs)
    assert len(out) == 1
