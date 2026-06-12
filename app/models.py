"""Curator data contracts.

These pydantic models are the shared vocabulary threaded through every
sub-agent of the regulatory-change-intelligence chain. Treat them as the
authoritative typed boundary — the LLM-generated outputs are validated
into these shapes before being passed to the next agent.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ----- inputs ---------------------------------------------------------------


class AmendmentInput(BaseModel):
    """The raw amendment notification + pointer to the revised Master Direction."""

    amendment_id: str
    master_direction_id: str
    title: str
    effective_date: date | None = None
    notification_url: str | None = None
    raw_text: str


class AmendedClause(BaseModel):
    """A single amended clause in the revised Master Direction.

    The decomposer reads the amendment text and emits one or more of these,
    each anchored to a stable clause id in the source Master Direction.
    """

    clause_id: str
    md_id: str
    heading: str | None = None
    old_text: str | None = None
    new_text: str
    change_type: Literal["insert", "modify", "delete", "renumber"]


# ----- the atomic unit of regulatory work -----------------------------------


class DeonticType(str, Enum):
    """Modality of a regulatory obligation. Used by the judge to score impact."""

    MUST = "must"           # mandatory ("shall", "must", "is required to")
    MUST_NOT = "must_not"   # prohibition ("shall not", "is prohibited")
    MAY = "may"             # permission ("may")
    SHOULD = "should"       # recommendation ("should", "is encouraged")


class Obligation(BaseModel):
    """A single atomic regulatory obligation extracted from an amended clause.

    A clause can fan out into multiple obligations — that fan-out is the
    most important moment in the demo. Each obligation owns its own
    timeline and (probably) its own internal owner.
    """

    id: str
    source_clause_id: str
    deontic_type: DeonticType
    subject: str = Field(description="Who/what the obligation is imposed on")
    action: str = Field(description="What must (not) / may / should be done")
    condition: str | None = Field(default=None, description="Triggering condition, if any")
    temporal_scope: str | None = Field(
        default=None,
        description="Deadline or recurring cadence, e.g. 'within 30 days', 'quarterly'",
    )
    owner_hint: str | None = Field(
        default=None,
        description="Likely internal owner (e.g. 'CFO', 'CRO', 'Compliance').",
    )
    confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Calibrated confidence in this extraction. Below 0.6 triggers the Reflector.",
    )
    missing_evidence: list[str] = Field(
        default_factory=list,
        description="Evidence the extractor wanted but couldn't find. Drives the Reflector loop.",
    )


# ----- the bank's side ------------------------------------------------------


class PolicyDocument(BaseModel):
    """A bank's internal policy / SOP, decomposed to addressable sections."""

    policy_id: str
    title: str
    owner_department: str | None = None
    sections: list[PolicySection]


class PolicySection(BaseModel):
    policy_section_id: str
    heading: str
    text: str


# ----- the mapping --------------------------------------------------------


CoverageLevel = Literal["full", "partial", "missing", "stale", "contradicts"]


class PolicyMatch(BaseModel):
    """Mapping of one obligation to one internal policy section.

    `coverage = missing` is valid and important — it means no internal
    policy currently addresses the obligation, which is a high-priority
    finding for the judge.
    """

    obligation_id: str
    policy_section_id: str | None = Field(
        default=None,
        description="None when coverage == 'missing'.",
    )
    coverage: CoverageLevel
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str | None = None
    missing_evidence: list[str] = Field(
        default_factory=list,
        description="Evidence the mapper wanted but couldn't find. Drives the Reflector loop.",
    )


# ----- the proposed change -------------------------------------------------


class PolicyDiff(BaseModel):
    """A concrete suggested edit to one internal policy section.

    These are *proposals*. The agent never autonomously applies a diff —
    a human reviewer is always in the loop.
    """

    policy_section_id: str
    current_text: str
    suggested_text: str
    rationale: str
    related_obligation_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Calibrated confidence in this suggested edit.",
    )
    missing_evidence: list[str] = Field(
        default_factory=list,
        description="Evidence the differ wanted but couldn't find (e.g. bank tone samples).",
    )


ChangeDirection = Literal[
    "increase", "decrease", "new", "removed", "restructured", "unchanged"
]


class ParameterChange(BaseModel):
    """A single quantitative regulatory parameter that moved between the
    prior framework (old) and the amending framework (new).

    This is the heart of a real change-analysis: a compliance officer does
    not want a generic 'you must implement the SA' obligation — they want
    'corporate unrated exposures: 100% → external-rating-banded (20%–150%);
    listed equity: 125% → 250%; effective 1-Apr-2025; higher RWA → lower
    CRAR'. Each ParameterChange pairs the old value with the new value and
    states the direction + the downstream capital effect.
    """

    parameter: str = Field(
        description="The regulatory lever that changed, e.g. 'Risk weight — listed equity exposures'."
    )
    exposure_class: str | None = Field(
        default=None,
        description="Portfolio/segment the parameter applies to (e.g. 'Corporate — unrated', 'Consumer credit / personal loans', 'CRE').",
    )
    old_value: str | None = Field(
        default=None,
        description="Value under the prior framework. None when the parameter is newly introduced.",
    )
    new_value: str = Field(description="Value under the amending framework.")
    direction: ChangeDirection
    unit: str | None = Field(default=None, description="e.g. '%', 'bps', 'x', 'ratio', 'LTV band'.")
    effective_date: str | None = Field(
        default=None,
        description="Commencement language as written, e.g. '1 April 2025', 'date of issue'.",
    )
    crar_impact: str | None = Field(
        default=None,
        description="Directional capital effect, e.g. 'higher risk weight → higher RWA → lower CRAR, all else equal'.",
    )
    source_old: str | None = Field(default=None, description="Clause/section ref in the prior framework.")
    source_new: str | None = Field(default=None, description="Clause/section ref in the new framework.")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    notes: str | None = None


class ImpactSummary(BaseModel):
    """Judge's verdict on the change package as a whole."""

    impact_score: float = Field(ge=0.0, le=1.0)
    priority: Literal["low", "medium", "high", "critical"]
    affected_departments: list[str] = Field(default_factory=list)
    downstream_effects: list[str] = Field(
        default_factory=list,
        description="Non-obvious second-order effects — the value-add of the judge.",
    )
    summary: str
    confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Calibrated confidence in this impact assessment.",
    )
    missing_evidence: list[str] = Field(
        default_factory=list,
        description="Evidence the judge wanted but couldn't find (e.g. ICAAP calibration data).",
    )


class AuditFinding(BaseModel):
    """One issue raised by the compliance / internal-audit review."""

    severity: Literal["info", "minor", "major", "blocker"]
    category: Literal[
        "data_quality",
        "accuracy",
        "completeness",
        "consistency",
        "compliance",
        "other",
    ]
    item: str = Field(description="What the finding is about (parameter, obligation, field).")
    detail: str = Field(description="Why it's a problem and what to check.")


class AuditReport(BaseModel):
    """Verdict of the compliance + internal-audit review of the final package.

    This is the automated control before a human signs off — proposals only,
    human approves. It does NOT rewrite the analysis; it judges whether the
    analysis is fit to publish and flags what a reviewer must check.
    """

    verdict: Literal["pass", "review", "fail"] = Field(
        description="pass = publishable; review = publish with caveats; fail = do not publish.",
    )
    publishable: bool = Field(
        description="True only when the package is safe to present without a human first resolving blockers.",
    )
    compliance_summary: str = Field(
        description="Compliance officer's one-paragraph verdict.",
    )
    audit_summary: str = Field(
        description="Internal auditor's one-paragraph verdict on data quality / evidence.",
    )
    findings: list[AuditFinding] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


# ----- the shared state ----------------------------------------------------


class AgentState(BaseModel):
    """The blackboard threaded sequentially through every sub-agent.

    Each sub-agent reads what it needs and appends its own output. The
    orchestrator owns this state; sub-agents do not mutate inputs.
    """

    amendment: AmendmentInput
    amended_clauses: list[AmendedClause] = Field(default_factory=list)
    # The prior / consolidated framework being compared against (Doc B).
    # Populated by ``ingest_two_pdfs`` so the parameter-diff stage can put
    # both documents side-by-side. None for single-document analysis.
    comparison_title: str | None = None
    comparison_text: str | None = None
    obligations: list[Obligation] = Field(default_factory=list)
    # Quantitative old→new parameter changes between the two frameworks.
    param_changes: list[ParameterChange] = Field(default_factory=list)
    policies: list[PolicyDocument] = Field(default_factory=list)
    matches: list[PolicyMatch] = Field(default_factory=list)
    diffs: list[PolicyDiff] = Field(default_factory=list)
    impact: ImpactSummary | None = None
    # Compliance + internal-audit review of the assembled package — the
    # automated control gate before a human approves / publishes.
    audit: "AuditReport | None" = None
    qna_history: list[QnATurn] = Field(default_factory=list)
    confidence_log: dict[str, float] = Field(
        default_factory=dict,
        description="Per-agent aggregate confidence captured by the chain (key = agent name).",
    )
    reflection_count: int = Field(
        default=0,
        description="Number of Reflector loops invoked across this run.",
    )


class QnATurn(BaseModel):
    question: str
    answer: str
    citations: list[str] = Field(default_factory=list)
    confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Calibrated confidence in this answer.",
    )
    missing_evidence: list[str] = Field(
        default_factory=list,
        description="Evidence the Q&A agent wanted but couldn't find.",
    )


PolicyDocument.model_rebuild()
AgentState.model_rebuild()
