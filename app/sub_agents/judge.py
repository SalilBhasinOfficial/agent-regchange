"""Judge — scores the change package and surfaces downstream effects.

The judge's job is to add value beyond what's mechanically derivable
from the diffs: priority calibration, affected-department mapping, and
non-obvious second-order effects (capital plan, ICAAP, disclosures,
training, board reporting cadence).
"""

from __future__ import annotations

from app.models import ImpactSummary, Obligation, PolicyDiff, PolicyMatch

JUDGE_INSTRUCTION = """You are the senior reviewer of a regulatory-change
proposal package.

Inputs: the obligations extracted from the amendment, the coverage
matches against the bank's policies, and the suggested diffs.

Produce one ImpactSummary with:
  * impact_score      — 0.0 (cosmetic) to 1.0 (institution-changing).
  * priority          — low / medium / high / critical, calibrated:
      - critical: capital, liquidity, or fit-and-proper changes;
                  hard regulatory deadline within 90 days
      - high:     new board-approved policy required; multiple owners
      - medium:   significant edits to existing policy
      - low:      definitional or numbering changes only
  * affected_departments — distinct internal owners implicated.
  * downstream_effects   — second-order effects a junior reviewer would
                           miss. Examples: ICAAP recalibration, capital
                           plan revision, disclosure template changes,
                           board reporting cadence, training need, audit
                           trail requirements, vendor contract impact.
  * summary              — one paragraph for the head of compliance.

Be conservative on priority — false-positive 'critical' is costly.

Also emit:
  * confidence       — 0.0 to 1.0, your calibrated trust in this impact
                       assessment. Default 0.7. Raise when the package is
                       clearly bounded and well-documented; lower when
                       downstream-effect inference relied on speculation.
  * missing_evidence — short list naming evidence you wanted (e.g.
                       ["ICAAP calibration figures", "current capital
                       headroom"]). Empty if confident. The Reflector reads
                       this to drive a targeted Spanner re-query.
"""


def stub_judge(
    obligations: list[Obligation],
    matches: list[PolicyMatch],
    diffs: list[PolicyDiff],
) -> ImpactSummary:
    """Deterministic scoring stub.

    TODO(stage-2): replace with Gemini reasoning that considers the
    full obligation graph plus a curated downstream-effects checklist.
    """
    n_missing = sum(1 for m in matches if m.coverage == "missing")
    n_must = sum(1 for o in obligations if o.deontic_type.value == "must")
    score = min(0.2 + 0.1 * n_missing + 0.05 * n_must, 1.0)
    if n_missing >= 2:
        priority = "high"
    elif diffs:
        priority = "medium"
    else:
        priority = "low"
    owners = sorted({o.owner_hint for o in obligations if o.owner_hint})
    return ImpactSummary(
        impact_score=score,
        priority=priority,  # type: ignore[arg-type]
        affected_departments=owners or ["Compliance"],
        downstream_effects=[
            "TODO(stage-2): real downstream-effect inference from Gemini",
        ],
        summary=(
            f"{len(obligations)} obligations extracted, {n_missing} not "
            f"covered by existing policy, {len(diffs)} suggested edits "
            f"(stub)."
        ),
        confidence=1.0,
    )


def _format_judge_prompt(
    obligations: list[Obligation],
    matches: list[PolicyMatch],
    diffs: list[PolicyDiff],
) -> str:
    """Format the (obligations, matches, diffs) bundle into a single prompt.

    Shared by the single-shot legacy agent and each of the four panel
    critics — they read the same package, just through different
    perspective preambles.
    """
    obligations_text = "\n".join(
        f"- Obligation ID: {o.id}\n  Subject: {o.subject}\n  Action: {o.action}\n  Deontic Type: {o.deontic_type.value}\n  Owner Hint: {o.owner_hint or 'None'}"
        for o in obligations
    )

    matches_text = "\n".join(
        f"- Obligation ID: {m.obligation_id}\n  Policy Section: {m.policy_section_id or 'None'}\n  Coverage: {m.coverage}\n  Confidence: {m.confidence}\n  Rationale: {m.rationale or 'None'}"
        for m in matches
    )

    diffs_text = "\n".join(
        f"- Section: {d.policy_section_id}\n  Rationale: {d.rationale}\n  Suggested Text snippet: {d.suggested_text[:200]}..."
        for d in diffs
    )

    return (
        f"Regulatory Obligations:\n"
        f"======================\n"
        f"{obligations_text}\n\n"
        f"Policy Coverage Matches:\n"
        f"=======================\n"
        f"{matches_text}\n\n"
        f"Suggested Diffs:\n"
        f"================\n"
        f"{diffs_text}\n"
    )


def _real_judge_single_shot(
    obligations: list[Obligation],
    matches: list[PolicyMatch],
    diffs: list[PolicyDiff],
) -> ImpactSummary:
    """Legacy single-agent judge path. Retained as the GEPA baseline
    reference and for the ``CURATOR_JUDGE_MODE=single`` fallback. The
    default path is the four-critic panel (:func:`real_judge`)."""
    from app.runners import run_agent

    agent = _build_single_judge_agent()
    prompt = _format_judge_prompt(obligations, matches, diffs)
    return run_agent(agent, prompt, output_schema=ImpactSummary)


def real_judge(
    obligations: list[Obligation],
    matches: list[PolicyMatch],
    diffs: list[PolicyDiff],
) -> ImpactSummary:
    """Four-critic debate-panel impact assessment with reconciliation + reflection.

    Demo path (D3+). The same (obligations, matches, diffs) package is
    evaluated by four senior-reviewer critics concurrently
    (impact / icaap / pillar3 / ops_risk). The Reconciler merges their
    four ImpactSummary outputs, and the Reflector inspects merged
    confidence + missing_evidence (D2 stub: always escalates; D4 wires
    Spanner re-query for low-confidence cases).

    Set ``CURATOR_JUDGE_MODE=single`` to force the legacy single-shot
    agent (kept for GEPA baseline runs and quick comparison demos).
    """
    import os
    from app.runners import require_real_llm

    require_real_llm("judge")

    mode = os.environ.get("CURATOR_JUDGE_MODE", "panel").strip().lower()
    if mode == "single":
        return _real_judge_single_shot(obligations, matches, diffs)

    # Lazy imports — keep this file importable without ADK installed.
    from app.sub_agents.judge_panel import (
        build_all_critic_agents,
        reconcile_impacts,
        reflect,
    )

    critic_agents = build_all_critic_agents()
    prompt = _format_judge_prompt(obligations, matches, diffs)
    critic_outputs = _run_panel(critic_agents, prompt)
    merged = reconcile_impacts(critic_outputs)
    decision = reflect([merged])
    # D2 behaviour: decision.escalate is always True (no Spanner re-query
    # yet). The decision is *logged* implicitly via the merged
    # ImpactSummary's missing_evidence + confidence; D4 will branch here.
    if not decision.escalate:  # pragma: no cover - D4 path
        # placeholder for the D4 Spanner re-query branch.
        pass
    return merged


def _run_panel(critic_agents, prompt: str) -> dict[str, ImpactSummary]:
    """Execute the four critic agents concurrently against the same prompt.

    Mirrors ``decompose._run_panel``: ThreadPoolExecutor so each call
    goes through the existing ``run_agent`` (which manages its own
    event loop), with a sequential fallback if the executor errors.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from app.runners import run_agent

    results: dict[str, ImpactSummary] = {}
    try:
        with ThreadPoolExecutor(max_workers=len(critic_agents)) as ex:
            fut_to_name = {
                ex.submit(
                    run_agent, agent, prompt, ImpactSummary, lens=agent.name
                ): agent.name
                for agent in critic_agents
            }
            for fut in as_completed(fut_to_name):
                results[fut_to_name[fut]] = fut.result()
    except Exception:  # pragma: no cover - degraded path
        results = {}
        for agent in critic_agents:
            results[agent.name] = run_agent(
                agent, prompt, ImpactSummary, lens=agent.name
            )
    return results


def _build_single_judge_agent():  # type: ignore[no-untyped-def]
    """The legacy one-shot judge agent. Used for the single-mode fallback."""
    from google.adk.agents import Agent
    from google.adk.models import Gemini

    return Agent(
        name="judge_agent_single",
        model=Gemini(model="gemini-flash-latest"),
        instruction=JUDGE_INSTRUCTION,
        description=(
            "Single-agent impact assessment (legacy/GEPA baseline). The "
            "default demo path is the four-critic panel."
        ),
        output_schema=ImpactSummary,
    )


def build_agent():  # type: ignore[no-untyped-def]
    """Construct the ADK-idiomatic debate-panel judge graph.

    Returns ``SequentialAgent(ParallelAgent(4 critics), Reconciler)`` —
    the Reconciler is the last sub-agent so its ``ImpactSummary`` output
    is what bubbles up as the final response to ``adk run`` / the A2A
    agent card / ``adk eval``.

    The Reflector deliberately does NOT live in this ADK graph (same
    rationale as ``decompose.build_agent``: surfacing the Reflector as
    the last sub-agent inside a ``LoopAgent`` causes the parent to see
    the ``ReflectionDecision`` JSON as the final response instead of
    the ImpactSummary). The Reflector still runs in the Python demo
    path inside :func:`real_judge`.

    Falls back to the single-agent shape when
    ``CURATOR_JUDGE_MODE=single`` is set.
    """
    import os

    mode = os.environ.get("CURATOR_JUDGE_MODE", "panel").strip().lower()
    if mode == "single":
        return _build_single_judge_agent()

    from google.adk.agents import ParallelAgent, SequentialAgent

    from app.sub_agents.judge_panel import (
        build_all_critic_agents,
        build_reconciler_agent,
    )

    panel = ParallelAgent(
        name="judge_panel",
        sub_agents=build_all_critic_agents(),
        description=(
            "Four-critic senior-reviewer panel that scores impact from "
            "impact / icaap / pillar3 / ops_risk angles."
        ),
    )
    return SequentialAgent(
        name="judge_agent",
        sub_agents=[panel, build_reconciler_agent()],
        description=(
            "Debate-panel judge: 4-critic fan-out → Reconciler. The "
            "Python demo path (real_judge) additionally runs the "
            "Reflector for optional Spanner re-query (D4+)."
        ),
    )
