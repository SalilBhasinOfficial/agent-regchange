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
  * verdict — calibrate by the WORST finding severity, not by whether any
    finding exists:
      - "pass"   — no major or blocker findings (info/minor notes are normal
                   and expected on real documents; they do NOT block a pass).
      - "review" — at least one "major" finding (publishable with caveats a
                   human should weigh).
      - "fail"   — at least one "blocker" finding (do not publish).
  * publishable — true unless there is a "blocker" finding.
  * compliance_summary — the compliance officer's one-paragraph verdict.
  * audit_summary — the internal auditor's one-paragraph verdict on data quality.
  * findings — each with severity (info/minor/major/blocker), category, the
    item, and what to check. FLAG, for example: a TOC/front-matter title
    (blocker); parameter rows that are not real quantitative levers or where
    old == new (major); an implausible number of changes (major); boilerplate
    obligations "comply with the directions" (minor); internal inconsistency
    such as priority HIGH with no material change (major).
  * confidence — 0..1.

Severity discipline — do NOT inflate severity:
  * The absence of an internal bank-policy corpus in a DOCUMENT-vs-DOCUMENT
    comparison (had_internal_policy_corpus = false, is_document_comparison =
    true) is an expected SCOPING NOTE, severity "info" — NOT a coverage gap,
    NOT a defect. Coverage mapping simply isn't in scope for that run.
  * Obligations being "missing" internal-policy coverage is only a finding when
    a policy corpus WAS provided.
  * "newly introduced" parameters (genuine additions with no prior value) are
    legitimate, not junk — flag them only if they look fabricated.

Be specific and terse. A clean, well-grounded package with only info/minor
notes gets verdict "pass", publishable true. Do not invent problems.
"""


_SEVERITY_RANK = {"info": 0, "minor": 1, "major": 2, "blocker": 3}


def _calibrate_verdict(report: AuditReport) -> AuditReport:
    """Derive verdict + publishable deterministically from finding severities.

    The LLM's self-assigned verdict was a stuck gate — it tended to "review"
    on essentially every document because *any* finding (even an info-level
    scoping note) read as "not clean". We override it with a consistent rule
    keyed only on the worst severity actually present, so the gate discriminates
    real quality: blocker → fail/unpublishable; major → review; otherwise pass.
    Findings, summaries and confidence from the model are preserved.
    """
    worst = max(
        (_SEVERITY_RANK.get((f.severity or "").strip().lower(), 0) for f in report.findings),
        default=0,
    )
    if worst >= _SEVERITY_RANK["blocker"]:
        report.verdict, report.publishable = "fail", False
    elif worst >= _SEVERITY_RANK["major"]:
        report.verdict, report.publishable = "review", True
    else:
        report.verdict, report.publishable = "pass", True
    return report


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
    report = run_agent(agent, prompt, output_schema=AuditReport)
    return _calibrate_verdict(report)


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
