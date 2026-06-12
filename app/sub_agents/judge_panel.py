"""Four-critic judge panel — the senior-reviewer debate moment.

The judge debate-panel mirrors the decompose panel (``lenses.py`` +
``reconciler.py`` + ``reflector.py``) but on the *impact assessment*
side: four critics read the same ``(obligations, matches, diffs)``
package and each produces a complete ``ImpactSummary`` from a distinct
angle. A deterministic Python reconciler then merges those four
summaries into one, and the existing ``reflector.reflect`` decides
whether the loop should escalate or re-query.

The four critics are deliberately *senior-reviewer roles*, each
calibrating ``impact_score`` and ``downstream_effects`` from a
different vantage:

  * ``judge_impact_critic``     — banks-business / P&L impact angle.
  * ``judge_icaap_critic``      — capital adequacy / ICAAP angle.
  * ``judge_pillar3_critic``    — disclosure / Pillar 3 narrative angle.
  * ``judge_ops_risk_critic``   — operational risk + audit + governance.

The critics share the existing ``JUDGE_INSTRUCTION`` (so the output
schema and scoring rubric are identical) with a perspective preamble
prepended. Outputs land in distinct ``state`` keys so the Reconciler
can read all four.

This module consolidates lenses + reconciler + reflector-Agent into a
single file because, unlike decompose, each judge-panel member produces
a *single* ``ImpactSummary`` (not a list), so the merge logic is more
compact. ``ReflectionDecision`` and ``reflect`` are imported from
``app.sub_agents.reflector`` rather than re-implemented — that function
already accepts any iterable of objects with ``.confidence`` and
``.missing_evidence``, so it works on the merged ``ImpactSummary`` too.
"""

from __future__ import annotations

from collections import Counter

from app.models import ImpactSummary
from app.sub_agents.judge import JUDGE_INSTRUCTION

# ----- critic catalogue -----------------------------------------------------

CRITIC_NAMES = (
    "judge_impact_critic",
    "judge_icaap_critic",
    "judge_pillar3_critic",
    "judge_ops_risk_critic",
)

CRITIC_STATE_KEYS: dict[str, str] = {
    "judge_impact_critic": "impact_critic_summary",
    "judge_icaap_critic": "icaap_critic_summary",
    "judge_pillar3_critic": "pillar3_critic_summary",
    "judge_ops_risk_critic": "ops_risk_critic_summary",
}

CRITIC_PREAMBLES: dict[str, str] = {
    "judge_impact_critic": """You are a senior reviewer at an Indian
commercial bank evaluating regulatory-change impact from the
**banks-business** angle. Your job is to calibrate impact_score against
the *cost to the bank*: capital deployment, balance-sheet impact,
operational disruption, product re-pricing, customer-facing changes,
P&L drag. You notice the line items that show up in next quarter's
board pack. Tilt impact_score up when capital plans or revenue lines
move; tilt down for purely procedural changes. Surface downstream
effects rooted in *business operations* (training rollouts, branch
SOP rewrites, vendor contract impact, repricing of in-flight loans).""",
    "judge_icaap_critic": """You are a senior reviewer at an Indian
commercial bank evaluating regulatory-change impact from the **capital
adequacy and ICAAP** angle. Your job is to assess whether the change
forces ICAAP recalibration, capital plan revision, internal capital
allocation rebalancing, stress-test scenario refresh, or Pillar 2
add-on changes. Tilt impact_score up when the change touches CET1,
RWAs, buffers, or capital conservation. Surface downstream effects
rooted in *capital math*: ICAAP document refresh, capital plan
re-Board-approval, RAS (risk appetite statement) limits review,
ALCO impact analysis, dividend policy review.""",
    "judge_pillar3_critic": """You are a senior reviewer at an Indian
commercial bank evaluating regulatory-change impact from the
**disclosure and Pillar 3** angle. Your job is to assess whether the
change forces new disclosure templates, Pillar 3 narrative updates,
investor-facing changes, KFS (Key Facts Statement) revisions, annual
report restatements, or quarterly disclosure expansions. Tilt
impact_score up when the change moves what the bank tells the market.
Surface downstream effects rooted in *external communication*: Pillar
3 template edits, investor-relations briefing notes, annual-report
narrative, regulatory-filing template changes, rating-agency
notifications.""",
    "judge_ops_risk_critic": """You are a senior reviewer at an Indian
commercial bank evaluating regulatory-change impact from the
**operational risk, audit, and governance** angle. Your job is to
assess whether the change requires new internal controls, board
reporting cadence changes, RMC standing-agenda items, audit-committee
touchpoints, internal-audit plan refresh, model validation expansion,
training programmes, or attestation cycles. Tilt impact_score up when
the change adds new governance plumbing. Surface downstream effects
rooted in *running and auditing the bank*: new RMC standing item,
audit-committee briefing, internal-audit annual plan refresh, control
testing additions, three-lines-of-defence reassignment, training
module rollout.""",
}


def _critic_instruction(critic_name: str) -> str:
    """Compose a critic-specific instruction by prepending the perspective preamble."""
    if critic_name not in CRITIC_PREAMBLES:
        raise ValueError(f"unknown judge critic: {critic_name}")
    return (
        f"{CRITIC_PREAMBLES[critic_name]}\n\n"
        f"---\n\n"
        f"{JUDGE_INSTRUCTION}\n\n"
        f"Important: stay in your perspective. Produce a complete\n"
        f"ImpactSummary from your angle — calibrate impact_score and\n"
        f"priority through your lens, and bias downstream_effects\n"
        f"toward the second-order effects YOUR perspective surfaces.\n"
        f"If you see effects clearly outside your lens, you may still\n"
        f"include them but lower your confidence and add a\n"
        f"missing_evidence entry naming the critic you would have\n"
        f"wanted to consult (e.g. 'icaap_critic_review_needed').\n"
    )


def build_critic_agent(critic_name: str):  # type: ignore[no-untyped-def]
    """Construct a single critic ADK Agent. Lazy import keeps import-time GCP-free."""
    from google.adk.agents import Agent
    from google.adk.models import Gemini
    from app.llm import curator_model_name

    return Agent(
        name=critic_name,
        model=Gemini(model=curator_model_name()),
        instruction=_critic_instruction(critic_name),
        description=(
            f"Scores impact and surfaces downstream effects of the change "
            f"package from the {critic_name.replace('judge_', '').replace('_', ' ')} "
            f"perspective. One of four panel members in the debate-panel judge."
        ),
        output_schema=ImpactSummary,
        output_key=CRITIC_STATE_KEYS[critic_name],
    )


def build_all_critic_agents() -> list:
    """Construct all 4 critic agents. Used by the ParallelAgent panel and
    by the ThreadPoolExecutor-based path in ``real_judge``."""
    return [build_critic_agent(name) for name in CRITIC_NAMES]


# ----- reconciler -----------------------------------------------------------

_PRIORITY_ORDER: dict[str, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}
_PRIORITY_NAMES = ("low", "medium", "high", "critical")


def _max_priority(priorities: list[str]) -> str:
    """Pick the highest priority across critics (one 'critical' voter → critical)."""
    if not priorities:
        return "low"
    ranks = [_PRIORITY_ORDER.get(p, 0) for p in priorities]
    return _PRIORITY_NAMES[max(ranks)]


def _agreement_factor(priorities: list[str]) -> float:
    """Confidence multiplier based on how much critics agreed on priority.

    All-agree: 1.0; spans two levels: 0.85; spans three or more: 0.7.
    Mirrors the per-lens agreement_factor in ``reconciler.py`` but
    operates on priority levels rather than lens count.
    """
    if not priorities:
        return 1.0
    ranks = {_PRIORITY_ORDER.get(p, 0) for p in priorities}
    span = max(ranks) - min(ranks)
    if span == 0:
        return 1.0
    if span == 1:
        return 0.85
    return 0.7


def _union_preserve_order(*lists: list[str]) -> list[str]:
    """Union of strings, deduplicated, preserving first-appearance order."""
    out: list[str] = []
    seen: set[str] = set()
    for lst in lists:
        for s in lst:
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out


def _merge_summary_text(summaries: list[str]) -> str:
    """Pick the longest non-empty summary as a deterministic fallback.

    A Python merge can't outsmart the model on prose; the longer summary
    usually carries more downstream-effect context. The Reconciler Agent
    factory in ``build_reconciler_agent`` provides a Gemini-driven
    alternative if the demo path ever wants one.
    """
    candidates = [s for s in summaries if s and s.strip()]
    if not candidates:
        return "(no summary)"
    return max(candidates, key=len)


def reconcile_impacts(
    critic_outputs: dict[str, ImpactSummary],
) -> ImpactSummary:
    """Merge four critic ImpactSummary outputs into one.

    Args:
        critic_outputs: mapping of critic_name → ImpactSummary produced
            by that critic. Keys are members of ``CRITIC_NAMES``.

    Returns:
        A single merged ``ImpactSummary`` with:
          * impact_score: weighted mean by per-critic confidence.
          * priority: max across critics (one critical → critical).
          * affected_departments: dedup union, first-appearance order.
          * downstream_effects: dedup union — the panel's main payoff.
          * summary: longest critic summary (simple heuristic).
          * confidence: mean × agreement_factor on priority spread.
          * missing_evidence: union plus ``not_seen_by:<critic>`` for
            any critic whose ``downstream_effects`` was empty.
    """
    if not critic_outputs:
        # Degenerate but well-formed result so callers never KeyError.
        return ImpactSummary(
            impact_score=0.0,
            priority="low",
            affected_departments=[],
            downstream_effects=[],
            summary="(no critic outputs)",
            confidence=0.0,
            missing_evidence=["no_critic_outputs"],
        )

    items = [(name, critic_outputs[name]) for name in critic_outputs]

    # impact_score — weighted mean by per-critic confidence.
    total_weight = sum(s.confidence for _, s in items) or 1.0
    weighted_score = (
        sum(s.impact_score * s.confidence for _, s in items) / total_weight
    )

    priorities = [s.priority for _, s in items]
    merged_priority = _max_priority(priorities)

    merged_departments = _union_preserve_order(
        *[list(s.affected_departments) for _, s in items]
    )
    merged_effects = _union_preserve_order(
        *[list(s.downstream_effects) for _, s in items]
    )

    summary = _merge_summary_text([s.summary for _, s in items])

    avg_conf = sum(s.confidence for _, s in items) / len(items)
    adjusted_conf = min(1.0, max(0.0, avg_conf * _agreement_factor(priorities)))

    union_evidence = _union_preserve_order(
        *[list(s.missing_evidence) for _, s in items]
    )
    # Simplified per-critic attribution: mark critics whose
    # downstream_effects came back empty — i.e. that critic didn't see
    # the panel-level effects the others did. (Per-effect attribution is
    # explicitly an acceptable simplification per the D3 brief.)
    for name, s in items:
        if not s.downstream_effects:
            marker = f"not_seen_by:{name}"
            if marker not in union_evidence:
                union_evidence.append(marker)

    return ImpactSummary(
        impact_score=min(1.0, max(0.0, weighted_score)),
        priority=merged_priority,  # type: ignore[arg-type]
        affected_departments=merged_departments,
        downstream_effects=merged_effects,
        summary=summary,
        confidence=adjusted_conf,
        missing_evidence=union_evidence,
    )


RECONCILER_INSTRUCTION = """You receive four ImpactSummary verdicts on
the *same* regulatory-change package, produced by four senior reviewers
from four different angles:

  * impact_critic     — banks-business / P&L impact.
  * icaap_critic      — capital adequacy / ICAAP recalibration.
  * pillar3_critic    — disclosure / Pillar 3 narrative.
  * ops_risk_critic   — operational risk / audit / governance.

Your job is to produce one merged ImpactSummary.

Rules:
  * impact_score — weighted mean of the four impact_scores, weighted
    by each critic's own confidence (low-confidence votes count less).
  * priority — take the MAX across the four. One 'critical' voter is
    enough to make the merged result 'critical'.
  * affected_departments — union, deduplicated, preserve first-
    appearance order.
  * downstream_effects — union, deduplicated. This is where the panel
    earns its keep — each critic surfaces effects the others miss.
  * summary — one paragraph for the head of compliance, synthesising
    the four perspectives.
  * confidence — mean of the four confidences, scaled DOWN when the
    critics disagreed on priority (full agreement × 1.0; two-level
    spread × 0.85; three-level spread × 0.7).
  * missing_evidence — union of cues, plus 'not_seen_by:<critic>' for
    any critic that produced empty downstream_effects.

Never invent effects or departments not present in the input. Never
suppress a critic's verdict — if you have doubts, surface the dissent
via missing_evidence with a lower merged confidence.

Return the merged ImpactSummary as JSON matching the schema.
"""


def build_reconciler_agent():  # type: ignore[no-untyped-def]
    """Construct the Judge Reconciler ADK Agent for adk run / A2A surface.

    The demo path uses ``reconcile_impacts`` (Python) directly for
    deterministic, debuggable merging. This Agent exists so the skill
    appears in the agent card and judges can browse the four-critic
    structure as a discoverable skill (mirrors the decompose Reconciler
    in ``reconciler.py``).
    """
    from google.adk.agents import Agent
    from google.adk.models import Gemini
    from app.llm import curator_model_name

    return Agent(
        name="judge_reconciler",
        model=Gemini(model=curator_model_name()),
        instruction=RECONCILER_INSTRUCTION,
        description=(
            "Merges the four senior-reviewer-critic ImpactSummary outputs "
            "into one with cross-critic-agreement confidence."
        ),
        output_schema=ImpactSummary,
        output_key="reconciled_impact",
    )


# ----- reflector (re-exported) ---------------------------------------------

# We deliberately reuse ``ReflectionDecision`` and ``reflect`` from
# ``app.sub_agents.reflector`` rather than redefining: the function
# already operates on any iterable of objects with ``.confidence`` and
# ``.missing_evidence``, so passing a one-element list with the merged
# ImpactSummary works correctly. This keeps reflector behaviour
# centralised — D4's Spanner-graph re-query upgrade lands once and
# benefits both decompose and judge panels.
from app.sub_agents.reflector import (  # noqa: E402, F401  (re-export)
    LOW_CONFIDENCE_THRESHOLD,
    ReflectionDecision,
    build_agent as build_reflector_agent,
    reflect,
)
