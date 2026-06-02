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


# ----- the shared state ----------------------------------------------------


class AgentState(BaseModel):
    """The blackboard threaded sequentially through every sub-agent.

    Each sub-agent reads what it needs and appends its own output. The
    orchestrator owns this state; sub-agents do not mutate inputs.
    """

    amendment: AmendmentInput
    amended_clauses: list[AmendedClause] = Field(default_factory=list)
    obligations: list[Obligation] = Field(default_factory=list)
    policies: list[PolicyDocument] = Field(default_factory=list)
    matches: list[PolicyMatch] = Field(default_factory=list)
    diffs: list[PolicyDiff] = Field(default_factory=list)
    impact: ImpactSummary | None = None
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
