"""Differ — PolicyMatch → PolicyDiff.

Produces concrete suggested edits to the bank's policy text. Every diff
is a *proposal* — the agent never autonomously applies changes; a human
reviewer is always in the loop (an explicit Stage-1 safety constraint).
"""

from __future__ import annotations

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
                )
            )
    return out


def build_agent():  # type: ignore[no-untyped-def]
    from google.adk.agents import Agent
    from google.adk.models import Gemini

    return Agent(
        name="diff_agent",
        model=Gemini(model="gemini-flash-latest"),
        instruction=DIFF_INSTRUCTION,
        description=(
            "Drafts concrete suggested edits to bank policy sections "
            "for partial/missing/stale/contradicts matches. Proposals "
            "only — never applies edits."
        ),
    )
