"""Stage-1 offline smoke test for the full Curator chain.

Runs decompose → map → diff → judge → qna against the fixture amendment
using the deterministic stub of each sub-agent. No GCP, no network, no
LLM. The smoke test is the Stage-1 'it executes end-to-end' verification
that ``adk run`` will repeat once GCP credentials are wired.
"""

from __future__ import annotations

from app.chain import run_chain
from app.models import AgentState


def test_chain_runs_end_to_end() -> None:
    state = run_chain(
        questions=[
            "Which obligations have no internal policy coverage?",
            "What is the overall priority of this amendment?",
        ]
    )
    assert isinstance(state, AgentState)
    assert state.amended_clauses, "decomposer received no amended clauses"
    assert state.obligations, "decomposer produced no obligations"
    assert state.policies, "no bank policies loaded — fixtures missing?"
    assert state.matches, "mapper produced no PolicyMatch records"
    assert state.diffs, "differ produced no PolicyDiff records"
    assert state.impact is not None, "judge produced no ImpactSummary"
    assert len(state.qna_history) == 2, "qna agent did not produce 2 turns"


def test_chain_fanout_signal() -> None:
    """The stub recognises two demo clauses by heading and fans them out.

    Climate Risk Capital Buffer → 2 obligations (steady-state +
    phase-in). Pillar 3 disclosure → 2 obligations (policy update +
    template change). The other clauses are 1:1. With 4 amended
    clauses, we expect 6 obligations.
    """
    state = run_chain()
    assert len(state.obligations) > len(state.amended_clauses), (
        "fan-out demo regression: expected >4 obligations from "
        f"{len(state.amended_clauses)} clauses, got {len(state.obligations)}"
    )


def test_chain_surfaces_missing_coverage() -> None:
    """The fixture is designed so at least one obligation has no coverage."""
    state = run_chain()
    missing = [m for m in state.matches if m.coverage == "missing"]
    # Stub mapping uses token overlap; the climate buffer obligation should
    # not match any existing section. If this fails, the fixtures drifted.
    assert len(missing) >= 1, (
        "fixtures should have at least one obligation with no coverage"
    )
