"""Deterministic Stage-1 chain runner.

Executes the full decompose → map → diff → judge → qna pipeline by
calling each sub-agent's ``stub_*`` function in order. No LLM, no GCP,
no network — used by the smoke test, the eval harness, and the
``python -m app.chain`` entrypoint.

Stage 2 swaps each stub call for the corresponding ADK Agent
invocation (real Gemini reasoning, real retrieval).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from app.grounding import MockGroundingBackend
from app.models import (
    AgentState,
    AmendedClause,
    AmendmentInput,
)
from app.sub_agents.decompose import stub_decompose
from app.sub_agents.diff import stub_diff
from app.sub_agents.judge import stub_judge
from app.sub_agents.map_ import stub_map
from app.sub_agents.qna import stub_qna

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_demo_amendment(
    amendment_id: str = "AMD-2026-capital-adequacy",
) -> tuple[AmendmentInput, list[AmendedClause]]:
    backend = MockGroundingBackend()
    text = backend.get_amendment_text(amendment_id)
    meta_path = (
        REPO_ROOT / "data" / "fixtures" / "amendments" / f"{amendment_id}.json"
    )
    meta = json.loads(meta_path.read_text())
    amendment = AmendmentInput(
        amendment_id=meta["amendment_id"],
        master_direction_id=meta["master_direction_id"],
        title=meta["title"],
        effective_date=meta.get("effective_date"),
        notification_url=meta.get("notification_url"),
        raw_text=text,
    )
    clauses = [AmendedClause(**c) for c in meta["amended_clauses"]]
    return amendment, clauses


def run_chain(
    amendment_id: str = "AMD-2026-capital-adequacy",
    questions: Iterable[str] = (),
) -> AgentState:
    """Run the deterministic stub chain end-to-end and return the final state."""
    amendment, clauses = load_demo_amendment(amendment_id)
    backend = MockGroundingBackend()
    policies = backend.load_bank_policies()

    state = AgentState(amendment=amendment, amended_clauses=clauses, policies=policies)
    state.obligations = stub_decompose(state.amended_clauses)
    state.matches = stub_map(state.obligations, state.policies)
    state.diffs = stub_diff(state.matches, state.obligations, state.policies)
    state.impact = stub_judge(state.obligations, state.matches, state.diffs)
    for q in questions:
        state.qna_history.append(stub_qna(state, q))
    return state


def _summarise(state: AgentState) -> str:
    miss = sum(1 for m in state.matches if m.coverage == "missing")
    return (
        f"amendment={state.amendment.amendment_id} | "
        f"clauses={len(state.amended_clauses)} | "
        f"obligations={len(state.obligations)} | "
        f"matches={len(state.matches)} (missing={miss}) | "
        f"diffs={len(state.diffs)} | "
        f"priority={state.impact.priority if state.impact else 'n/a'}"
    )


if __name__ == "__main__":  # pragma: no cover - smoke entry point
    final = run_chain(
        questions=[
            "Which obligations have no internal policy coverage?",
            "What is the overall priority of this amendment?",
        ]
    )
    print(_summarise(final))
    print()
    for t in final.qna_history:
        print(f"Q: {t.question}")
        print(f"A: {t.answer}")
        print(f"   citations: {t.citations}")
        print()
