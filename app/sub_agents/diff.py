"""Differ — PolicyMatch → PolicyDiff.

Produces concrete suggested edits to the bank's policy text. Every diff
is a *proposal* — the agent never autonomously applies changes; a human
reviewer is always in the loop (an explicit Stage-1 safety constraint).
"""

from __future__ import annotations

import os

from app.models import Obligation, PolicyDiff, PolicyDocument, PolicyMatch

DIFF_INSTRUCTION = """You draft specific suggested edits to internal bank
policies so they comply with regulatory obligations.

For each PolicyMatch where coverage is partial, missing, stale, or
contradicts, emit a PolicyDiff:

  * current_text   — the existing section text (empty if missing).
  * suggested_text — the proposed replacement. Match the bank's tone
                     and structure; keep numbering conventions intact.
  * rationale      — one paragraph explaining the change and citing
                     the obligation(s) and source clause it addresses.

If coverage is 'full', skip — no diff needed.

NEVER autonomously apply edits. These are proposals for human review.

For EACH PolicyDiff also emit:
  * confidence       — 0.0 to 1.0, your calibrated trust in the suggested
                       edit. Default 0.7; raise to 0.9+ when the rewrite is
                       clearly mandated by the obligation; lower when tone
                       or numbering convention is uncertain.
  * missing_evidence — short list naming evidence you wanted (e.g.
                       ["bank's preferred numbering style", "prior amendment
                       template"]). Empty when confident.
"""


def stub_diff(
    matches: list[PolicyMatch],
    obligations: list[Obligation],
    policies: list[PolicyDocument],
) -> list[PolicyDiff]:
    """Deterministic placeholder edits.

    TODO(stage-2): replace with Gemini-driven edit synthesis that
    preserves document style and inline numbering.
    """
    obl_by_id = {o.id: o for o in obligations}
    section_text: dict[str, tuple[str, str]] = {}
    for p in policies:
        for s in p.sections:
            section_text[s.policy_section_id] = (s.heading, s.text)

    out: list[PolicyDiff] = []
    for m in matches:
        if m.coverage == "full":
            continue
        obl = obl_by_id.get(m.obligation_id)
        if obl is None:
            continue
        if m.coverage == "missing":
            out.append(
                PolicyDiff(
                    policy_section_id="NEW",
                    current_text="",
                    suggested_text=(
                        f"[New section to be added]\n"
                        f"The {obl.subject} shall {obl.action}."
                    ),
                    rationale=(
                        f"No internal policy currently addresses obligation "
                        f"{obl.id} (clause {obl.source_clause_id}). Adding "
                        f"a new section is recommended (stub)."
                    ),
                    related_obligation_ids=[obl.id],
                    confidence=1.0,
                )
            )
        else:
            heading, current = section_text.get(
                m.policy_section_id or "", ("", "")
            )
            out.append(
                PolicyDiff(
                    policy_section_id=m.policy_section_id or "",
                    current_text=current,
                    suggested_text=(
                        f"{current}\n\n[Suggested addition] "
                        f"The {obl.subject} shall {obl.action}."
                    ),
                    rationale=(
                        f"Section '{heading}' has {m.coverage} coverage of "
                        f"obligation {obl.id} ({obl.source_clause_id}). "
                        f"Suggested wording brings it in line (stub)."
                    ),
                    related_obligation_ids=[obl.id],
                    confidence=1.0,
                )
            )
    return out


def real_diff(
    matches: list[PolicyMatch],
    obligations: list[Obligation],
    policies: list[PolicyDocument],
) -> list[PolicyDiff]:
    """Gemini-driven edit synthesis to draft suggested edits to bank policies.

    D5 speed-lift: non-full matches are drafted concurrently via a
    ThreadPoolExecutor (up to ``CURATOR_DIFF_CONCURRENCY`` workers,
    default 8). Each diff is still one Gemini call; the parallel fan-
    out drops wall-clock from O(N) to O(N/8) for typical 10-19 diffs.
    """
    from concurrent.futures import ThreadPoolExecutor
    from app.runners import require_real_llm, run_agent
    require_real_llm("diff")

    agent = build_agent()

    obl_by_id = {o.id: o for o in obligations}
    section_map = {
        s.policy_section_id: s for p in policies for s in p.sections
    }

    def _resolve_target(m: PolicyMatch) -> tuple[Obligation | None, str, str, str]:
        """Return (obligation, section_id, current_heading, current_text)."""
        obl = obl_by_id.get(m.obligation_id)
        if not obl:
            return None, "", "", ""
        if m.coverage == "missing" or not m.policy_section_id:
            return obl, "NEW", "None (Creating new section)", ""
        sec = section_map.get(m.policy_section_id)
        return (
            obl,
            m.policy_section_id,
            sec.heading if sec else "Unknown",
            sec.text if sec else "",
        )

    def _diff_one(m: PolicyMatch) -> PolicyDiff | None:
        obl, section_id, current_heading, current_text = _resolve_target(m)
        if obl is None:
            return None
        prompt = (
            f"Policy Section Details:\n"
            f"  Section ID: {section_id}\n"
            f"  Heading: {current_heading}\n"
            f"  Current Text: {current_text}\n\n"
            f"Regulatory Obligation to Incorporate:\n"
            f"  Obligation ID: {obl.id}\n"
            f"  Source Clause ID: {obl.source_clause_id}\n"
            f"  Subject: {obl.subject}\n"
            f"  Action: {obl.action}\n"
            f"  Deontic Type: {obl.deontic_type.value}\n"
            f"  Temporal Scope: {obl.temporal_scope or 'None'}\n"
            f"  Coverage Assessment: {m.coverage}\n"
            f"  Mapper Rationale: {m.rationale}\n"
        )
        res = run_agent(agent, prompt, output_schema=PolicyDiff)
        res.policy_section_id = section_id
        res.current_text = current_text
        if not res.related_obligation_ids:
            res.related_obligation_ids = [obl.id]
        elif obl.id not in res.related_obligation_ids:
            res.related_obligation_ids.append(obl.id)
        return res

    todo = [m for m in matches if m.coverage != "full"]
    if not todo:
        return []
    max_workers = int(os.environ.get("CURATOR_DIFF_CONCURRENCY", "8"))
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            results = list(ex.map(_diff_one, todo))
    except Exception:  # pragma: no cover - degraded path; sequential fallback
        results = [_diff_one(m) for m in todo]
    return [r for r in results if r is not None]


def build_agent():  # type: ignore[no-untyped-def]
    from google.adk.agents import Agent
    from google.adk.models import Gemini
    from app.llm import curator_model_name

    return Agent(
        name="diff_agent",
        model=Gemini(model=curator_model_name()),
        instruction=DIFF_INSTRUCTION,
        description=(
            "Drafts concrete suggested edits to bank policy sections "
            "for partial/missing/stale/contradicts matches. Proposals "
            "only — never applies edits."
        ),
        output_schema=PolicyDiff,
    )
