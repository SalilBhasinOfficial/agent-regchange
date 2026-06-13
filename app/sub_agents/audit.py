"""Compliance + internal-audit review — the control gate before publishing.

Every other stage *produces* analysis; this one *judges whether the analysis
is fit to publish*. It embodies two reviewers a bank would put in front of any
output that reaches the Risk Management Committee:

  * a COMPLIANCE OFFICER (is it regulatorily sound and not overstated?), and
  * an INTERNAL AUDITOR (is the data clean, traceable, non-duplicated?).

It does NOT rewrite the package — it returns an :class:`AuditReport` with a
verdict (pass / review / fail), a publishable flag, and concrete findings a
human must resolve. This is the automated control before the human sign-off
that the product always requires ("proposals only, human approves").

Offline-safe: ``stub_audit`` returns a clean pass so the canonical line is
unchanged.
"""

from __future__ import annotations

from app.models import AgentState, AuditReport

AUDIT_INSTRUCTION = """You are a two-person review panel signing off a
regulatory change-analysis package before it reaches a bank's Risk Management
Committee:

  * COMPLIANCE OFFICER — is the analysis regulatorily sound? Do the parameter
    changes, obligations and impact reflect what the documents actually say?
    No overstated, generic or fabricated requirements; effective dates and the
    CRAR direction make sense.
  * INTERNAL AUDITOR — is the DATA clean and traceable? Flag junk masquerading
    as findings: "parameters" that are really table-of-contents lines, page
    numbers or section headings; values reported as changed when old == new;
    duplicates; an implausibly large change count for the document; a document
    title that is obviously front-matter ("Table of Contents", "Index").

You are given the assembled package (title, parameter-change count + sample,
obligation count + sample, impact). Do NOT rewrite it. Judge whether it is fit
to publish and list what a human must resolve first.

Emit an AuditReport:
  * verdict — "pass" (clean), "review" (publishable with caveats), or "fail"
    (do not publish — serious data-quality or accuracy problems).
  * publishable — false if there is any "blocker" finding.
  * compliance_summary — the compliance officer's one-paragraph verdict.
  * audit_summary — the internal auditor's one-paragraph verdict on data quality.
  * findings — each with severity (info/minor/major/blocker), category, the
    item, and what to check. FLAG, for example: a TOC/front-matter title;
    parameter rows that are not real quantitative levers or where old == new;
    an implausible number of changes; boilerplate obligations ("comply with the
    directions"); internal inconsistency (priority HIGH with no material change).
  * confidence — 0..1.

Be specific and terse. A genuinely clean package gets verdict "pass",
publishable true, and an empty findings list — do not invent problems.
"""


def stub_audit(state: AgentState) -> AuditReport:
    """Offline placeholder — assumes clean (no LLM review)."""
    return AuditReport(
        verdict="pass",
        publishable=True,
        compliance_summary="(stub) not reviewed offline.",
        audit_summary="(stub) not reviewed offline.",
        findings=[],
        confidence=1.0,
    )


def real_audit(state: AgentState) -> AuditReport:
    """Compliance + internal-audit review of the assembled package.

    Sends a COMPACT view (counts + samples, not the full raw text) so the
    review is cheap and its own output never approaches the token ceiling.
    """
    import json

    from app.runners import require_real_llm, run_agent

    require_real_llm("audit")

    package = {
        "title": state.amendment.title,
        "comparison_title": state.comparison_title,
        "is_document_comparison": bool(state.comparison_text),
        "had_internal_policy_corpus": len(state.policies) > 0,
        "n_param_changes": len(state.param_changes),
        "param_changes_sample": [p.model_dump() for p in state.param_changes[:40]],
        "n_obligations": len(state.obligations),
        "obligations_sample": [o.action for o in state.obligations[:20]],
        "impact": state.impact.model_dump() if state.impact else None,
    }
    prompt = (
        "Assembled change-analysis package to review (JSON; samples are "
        "truncated, counts are full):\n"
        "=================================================\n"
        f"{json.dumps(package, indent=2, default=str)}\n"
        "=================================================\n"
        "Produce the AuditReport per your instructions."
    )
    agent = build_agent()
    return run_agent(agent, prompt, output_schema=AuditReport)


def build_agent():  # type: ignore[no-untyped-def]
    from google.adk.agents import Agent
    from google.adk.models import Gemini

    from app.llm import curator_generation_config, curator_model_name

    return Agent(
        name="audit_agent",
        model=Gemini(model=curator_model_name()),
        generate_content_config=curator_generation_config(),
        instruction=AUDIT_INSTRUCTION,
        description=(
            "Compliance + internal-audit review gate: judges whether the final "
            "change-analysis package is fit to publish and flags issues."
        ),
        output_schema=AuditReport,
    )


__all__ = ["real_audit", "stub_audit", "build_agent", "AUDIT_INSTRUCTION"]
