"""Reflector — decides whether the reconciled obligations need a re-query.

After the Reconciler produces a merged obligation list, the Reflector
looks at aggregate confidence and the union of ``missing_evidence``
entries. If aggregate confidence is below ``LOW_CONFIDENCE_THRESHOLD``,
or any obligation has cited missing evidence the panel couldn't supply,
the Reflector emits a re-query request.

Stage of evolution:
  * **D2 (today)** — Reflector is a no-op signal generator. It computes
    the decision but does *not* re-query anything; the
    ``SpannerGraphBackend.query_graph_neighborhood`` hook arrives in D4.
    The loop terminates after one pass regardless.
  * **D4** — Reflector calls ``SpannerGraphBackend.query_graph_neighborhood``
    with the cued missing_evidence and feeds the additional context back
    into the panel for a second iteration.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models import Obligation

LOW_CONFIDENCE_THRESHOLD = 0.6


class ReflectionDecision(BaseModel):
    """Reflector's verdict on the reconciled obligations."""

    escalate: bool = Field(
        description=(
            "True when the panel result is satisfactory and the LoopAgent "
            "should terminate. False to trigger another iteration "
            "(D4+ — re-queries Spanner Graph for additional context)."
        )
    )
    aggregate_confidence: float = Field(ge=0.0, le=1.0)
    requeries: list[str] = Field(
        default_factory=list,
        description=(
            "Missing-evidence cues collected from the panel obligations, "
            "rolled up for a targeted Spanner Graph re-query. Empty when "
            "no re-query needed."
        ),
    )
    rationale: str = Field(
        default="",
        description="Short human-readable explanation of the decision.",
    )


def reflect(obligations: list[Obligation]) -> ReflectionDecision:
    """Deterministic D2 reflection.

    Computes aggregate confidence and collects missing_evidence cues.
    Returns ``escalate=True`` unconditionally for D2 — there is no
    Spanner backend wired yet, so re-running the panel without new
    context would just burn tokens. D4 lifts this constraint.
    """
    if not obligations:
        return ReflectionDecision(
            escalate=True,
            aggregate_confidence=1.0,
            requeries=[],
            rationale="No obligations produced; nothing to reflect on.",
        )

    avg_conf = sum(o.confidence for o in obligations) / len(obligations)
    # Collect every distinct missing_evidence cue, filtering the
    # mechanical "not_seen_by:<lens>" markers (those are dissent, not
    # evidence gaps).
    cues: list[str] = []
    for o in obligations:
        for cue in o.missing_evidence:
            if cue.startswith("not_seen_by:"):
                continue
            if cue not in cues:
                cues.append(cue)

    low_conf = avg_conf < LOW_CONFIDENCE_THRESHOLD
    has_cues = bool(cues)

    if low_conf or has_cues:
        return ReflectionDecision(
            escalate=True,  # D2: still terminate; D4 will flip to False when re-query helps.
            aggregate_confidence=avg_conf,
            requeries=cues,
            rationale=(
                f"Aggregate confidence {avg_conf:.2f} "
                f"(threshold {LOW_CONFIDENCE_THRESHOLD}); "
                f"{len(cues)} evidence cue(s) collected. "
                f"D2 stub: no Spanner re-query yet — terminating loop."
            ),
        )
    return ReflectionDecision(
        escalate=True,
        aggregate_confidence=avg_conf,
        requeries=[],
        rationale=(
            f"Aggregate confidence {avg_conf:.2f} above threshold; "
            f"no missing-evidence cues. Terminating loop."
        ),
    )


REFLECTOR_INSTRUCTION = """You receive a reconciled list of regulatory
Obligations produced by the four-lens decompose panel + Reconciler.
Your job is to decide whether the panel's output is good enough to
ship, or whether it should re-run with additional context.

Compute:
  * aggregate_confidence — mean of obligation confidences (0.0–1.0).
  * requeries            — list of missing_evidence cues across all
                           obligations (drop the mechanical
                           "not_seen_by:<lens>" markers; those track
                           lens dissent, not evidence gaps).
  * escalate             — TRUE to terminate the loop (panel is good
                           enough OR no re-query mechanism available).
                           FALSE to trigger another iteration. In D2
                           the runtime has no Spanner re-query yet, so
                           always emit TRUE.

Be conservative: if requeries is non-empty but the wider system
doesn't yet support re-querying, terminate (escalate=TRUE) and let
the operator triage the cues manually.
"""


def build_agent():  # type: ignore[no-untyped-def]
    """Construct the Reflector ADK Agent for adk run / A2A surface."""
    from google.adk.agents import Agent
    from google.adk.models import Gemini

    return Agent(
        name="reflector",
        model=Gemini(model="gemini-flash-latest"),
        instruction=REFLECTOR_INSTRUCTION,
        description=(
            "Decides whether the panel's reconciled obligations are "
            "good enough or should be re-queried against Spanner Graph "
            "(D4+). Emits escalate=True in D2 unconditionally."
        ),
        output_schema=ReflectionDecision,
        output_key="reflection_decision",
    )
