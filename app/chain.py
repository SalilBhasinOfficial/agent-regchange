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


def _mean_confidence(items: list) -> float:
    """Aggregate per-item confidence into a single float for confidence_log."""
    vals = [getattr(it, "confidence", 1.0) for it in items]
    return sum(vals) / len(vals) if vals else 1.0


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
    *,
    initial_state: AgentState | None = None,
) -> AgentState:
    """Run the chain end-to-end and return the final state.

    Swaps between deterministic stubs and real Gemini-driven agents
    based on the CURATOR_REAL_LLM environment variable.

    Args:
      amendment_id: fixture id to load when ``initial_state`` is None
        (offline / canonical-line path).
      questions: optional Q&A turns to append at the end.
      initial_state: pre-built AgentState to run against — used by the
        Inbox per-row "Analyse" route and by ``ingest_two_pdfs``-fed
        callers so the chain skips its built-in fixture loader.
        ``policies`` is populated from ``MockGroundingBackend`` when
        the caller-supplied state has none.
    """
    from app.observability.run_log import current_pipeline_run_id, begin_pipeline_run
    from app.runners import real_llm_enabled

    # Tag every agent_runs row emitted during this chain with one shared
    # pipeline_run_id. Only open a fresh id if the caller hasn't already
    # done so (FastAPI background runner pre-binds via bind_pipeline_run).
    if current_pipeline_run_id() is None:
        begin_pipeline_run()

    if initial_state is not None:
        state = initial_state
        if not state.policies:
            state.policies = MockGroundingBackend().load_bank_policies()
    else:
        amendment, clauses = load_demo_amendment(amendment_id)
        backend = MockGroundingBackend()
        policies = backend.load_bank_policies()
        state = AgentState(
            amendment=amendment, amended_clauses=clauses, policies=policies
        )

    if real_llm_enabled():
        # CURATOR_FAST_MODE=1 flips a triage profile: caps obligation count
        # before map/diff so an interactive demo finishes in well under a
        # minute even under tight Vertex AI quotas. Trades fan-out fidelity
        # for latency. The full-panel run remains the production default.
        import os as _os

        fast_mode = _os.environ.get("CURATOR_FAST_MODE", "0").strip().lower() in {
            "1", "true", "yes", "on"
        }
        max_obls = int(_os.environ.get("CURATOR_FAST_MAX_OBLIGATIONS", "5"))

        from app.sub_agents.decompose import real_decompose
        from app.sub_agents.diff import real_diff
        from app.sub_agents.judge import real_judge
        from app.sub_agents.map_ import real_map
        from app.sub_agents.param_diff import real_param_diff
        from app.sub_agents.qna import real_qna

        # Quantitative old→new parameter diff (no-op when there is no
        # comparison document, e.g. single-doc Inbox analysis).
        state.param_changes = real_param_diff(
            state.amended_clauses,
            new_title=state.amendment.title,
            new_text=state.amendment.raw_text,
            comparison_title=state.comparison_title,
            comparison_text=state.comparison_text,
        )
        # Pre-diff clause filter: the four-lens panel costs ~4 LLM calls per
        # clause, so drop clauses byte-identical to the prior document before
        # decomposing. Exact-match only — a clause that changed any number
        # survives. Biggest win for same-document version diffs; near-no-op
        # for cross-framework pairs. Disable with CURATOR_PREDIFF_FILTER_CLAUSES=0.
        if _os.environ.get("CURATOR_PREDIFF_FILTER_CLAUSES", "1") != "0":
            from app.ingest.prediff import filter_unchanged_clauses

            kept, dropped = filter_unchanged_clauses(
                state.amended_clauses, state.comparison_text
            )
            if dropped:
                import logging

                logging.getLogger(__name__).info(
                    "chain: pre-diff dropped %d unchanged clause(s); %d to decompose "
                    "(~%d fewer LLM calls).",
                    dropped,
                    len(kept),
                    dropped * 4,
                )
                state.amended_clauses = kept
        state.obligations = real_decompose(state.amended_clauses)
        if fast_mode and len(state.obligations) > max_obls:
            state.obligations = state.obligations[:max_obls]
        state.matches = real_map(state.obligations, state.policies)
        state.diffs = real_diff(state.matches, state.obligations, state.policies)
        state.impact = real_judge(
            state.obligations, state.matches, state.diffs, state.param_changes
        )
        # Compliance + internal-audit control gate over the assembled package.
        from app.sub_agents.audit import real_audit

        try:
            state.audit = real_audit(state)
        except Exception:  # noqa: BLE001 — audit is a gate, never fail the run
            import logging

            logging.getLogger(__name__).warning("audit stage failed; continuing")
        for q in questions:
            state.qna_history.append(real_qna(state, q))
    else:
        state.obligations = stub_decompose(state.amended_clauses)
        state.matches = stub_map(state.obligations, state.policies)
        state.diffs = stub_diff(state.matches, state.obligations, state.policies)
        state.impact = stub_judge(state.obligations, state.matches, state.diffs)
        from app.sub_agents.audit import stub_audit

        state.audit = stub_audit(state)
        for q in questions:
            state.qna_history.append(stub_qna(state, q))

    state.confidence_log = {
        "decompose": _mean_confidence(state.obligations),
        "map": _mean_confidence(state.matches),
        "diff": _mean_confidence(state.diffs),
        "judge": state.impact.confidence if state.impact else 1.0,
        "qna": _mean_confidence(state.qna_history),
    }
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
