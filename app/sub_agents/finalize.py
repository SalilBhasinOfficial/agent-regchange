"""Finalize — loop the audit's observations back into the report.

The audit stage (``app.sub_agents.audit``) reviews the assembled package and
raises findings, but a flag alone doesn't make the report true and fair. This
stage closes the loop: it takes the package *plus* the audit findings and
produces a :class:`Finalization` — which parameter rows to exclude as not
genuine, a corrected overall priority if the judge's was unsupported, and a
balanced "true and fair" final summary that acknowledges the audit's caveats.

The chain applies the exclusions/priority deterministically and then re-audits
once, so the published report reflects the audit's observations rather than
merely listing them. Bounded to a single loop — no unbounded back-and-forth.

Offline-safe: ``stub_finalize`` echoes the existing summary with no changes.
"""

from __future__ import annotations

from app.models import AgentState, Finalization

FINALIZE_INSTRUCTION = """You are the engagement partner finalizing a regulatory
change-analysis report for a bank's Risk Management Committee. You are given the
assembled package AND the compliance + internal-audit findings on it. Your job
is to make the report TRUE AND FAIR by acting on those findings — not to
re-do the analysis.

Produce a Finalization:
  * excluded_parameters — the EXACT parameter names (as they appear in the
    package) that the audit showed are NOT genuine quantitative changes:
    table-of-contents lines, section headings, page numbers, or rows where the
    value did not actually move. These will be removed from the final report.
    Only list parameters that are clearly not real changes; when in doubt,
    keep them.
  * corrected_priority — if the audit found the overall priority unsupported by
    the (cleaned) evidence, give the corrected priority; otherwise null.
  * true_and_fair_summary — a single balanced paragraph stating what genuinely
    changed and its capital/compliance impact, written so it would survive
    audit: no overstatement, no figures that aren't supported, and an explicit
    note of any material limitation the audit raised (e.g. "no internal policy
    corpus was available, so coverage was not assessed").
  * changes_made — short bullet list of what you reconciled in response to the
    audit (for the change record).
  * confidence — 0..1.

If the audit found nothing material, return empty excluded_parameters, null
corrected_priority, a faithful true_and_fair_summary, and changes_made noting
"audit raised no material issues".
"""


def stub_finalize(state: AgentState) -> Finalization:
    """Offline placeholder — no changes, echoes the existing summary."""
    summary = state.impact.summary if state.impact else "(no impact summary)"
    return Finalization(
        excluded_parameters=[],
        corrected_priority=None,
        true_and_fair_summary=summary,
        changes_made=["(stub) audit loop not run offline"],
        confidence=1.0,
    )


def real_finalize(state: AgentState) -> Finalization:
    """Apply the audit's observations to produce the true-and-fair report."""
    import json

    from app.runners import require_real_llm, run_agent

    require_real_llm("finalize")

    package = {
        "title": state.amendment.title,
        "is_document_comparison": bool(state.comparison_text),
        "had_internal_policy_corpus": len(state.policies) > 0,
        "n_param_changes": len(state.param_changes),
        "param_changes_sample": [
            {
                "parameter": p.parameter,
                "old_value": p.old_value,
                "new_value": p.new_value,
                "direction": p.direction,
            }
            for p in state.param_changes[:60]
        ],
        "n_obligations": len(state.obligations),
        "impact": state.impact.model_dump() if state.impact else None,
        "audit": state.audit.model_dump() if state.audit else None,
    }
    prompt = (
        "Assembled package and the audit findings on it (JSON):\n"
        "=================================================\n"
        f"{json.dumps(package, indent=2, default=str)}\n"
        "=================================================\n"
        "Produce the Finalization that makes this report true and fair."
    )
    agent = build_agent()
    return run_agent(agent, prompt, output_schema=Finalization)


def apply_finalization(state: AgentState, fin: Finalization) -> None:
    """Deterministically apply a Finalization to the state, in place.

    Drops excluded parameter rows, corrects the priority, and replaces the
    impact summary with the true-and-fair text. Deterministic so the published
    numbers exactly match what the audit loop decided.
    """
    if fin.excluded_parameters:
        drop = {p.strip().lower() for p in fin.excluded_parameters if p.strip()}
        if drop:
            state.param_changes = [
                pc
                for pc in state.param_changes
                if (pc.parameter or "").strip().lower() not in drop
            ]
    if state.impact is not None:
        if fin.corrected_priority:
            state.impact.priority = fin.corrected_priority
        if fin.true_and_fair_summary and fin.true_and_fair_summary.strip():
            state.impact.summary = fin.true_and_fair_summary.strip()
    state.finalization = fin


def review_and_finalize(state: AgentState, *, max_loops: int = 1) -> None:
    """Audit → (if findings) finalize + apply → re-audit. Mutates state.

    The control loop that makes the report true and fair: the compliance +
    internal-audit observations are looped back into the report and applied,
    then the finalized report is re-audited to confirm. Bounded to ``max_loops``
    finalize passes so there is never unbounded back-and-forth.
    """
    from app.sub_agents.audit import real_audit

    def _actionable(report: AuditReport | None) -> bool:
        # Only loop back for findings a human would actually require fixing —
        # major/blocker. Info/minor notes are expected on real documents and a
        # "pass" should not trigger a finalize pass (wasted LLM calls + risk of
        # over-remediation).
        return bool(report) and any(
            (f.severity or "").strip().lower() in {"major", "blocker"}
            for f in report.findings
        )

    state.audit = real_audit(state)
    loops = 0
    while _actionable(state.audit) and loops < max_loops:
        fin = real_finalize(state)
        apply_finalization(state, fin)
        # Re-audit the finalized report so the published verdict reflects the
        # corrections, not the pre-finalization package.
        state.audit = real_audit(state)
        loops += 1


def build_agent():  # type: ignore[no-untyped-def]
    from google.adk.agents import Agent
    from google.adk.models import Gemini

    from app.llm import curator_generation_config, curator_model_name

    return Agent(
        name="finalize_agent",
        model=Gemini(model=curator_model_name()),
        generate_content_config=curator_generation_config(),
        instruction=FINALIZE_INSTRUCTION,
        description=(
            "Loops compliance + internal-audit observations back into the report "
            "to produce a true-and-fair finalization."
        ),
        output_schema=Finalization,
    )


__all__ = [
    "real_finalize",
    "stub_finalize",
    "apply_finalization",
    "build_agent",
    "FINALIZE_INSTRUCTION",
]
