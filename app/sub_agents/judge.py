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
    )


def build_agent():  # type: ignore[no-untyped-def]
    from google.adk.agents import Agent
    from google.adk.models import Gemini

    return Agent(
        name="judge_agent",
        model=Gemini(model="gemini-flash-latest"),
        instruction=JUDGE_INSTRUCTION,
        description=(
            "Scores impact and priority of the change package and "
            "surfaces non-obvious downstream effects."
        ),
    )
