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


def reflect_and_requery(
    obligations: list[Obligation],
    *,
    namespace: str,
    grounding=None,
) -> tuple[ReflectionDecision, list[dict]]:
    """D4 reflection with optional Spanner Graph re-query.

    Wraps :func:`reflect` and, when the panel signal indicates the
    result is shaky (aggregate confidence below
    :data:`LOW_CONFIDENCE_THRESHOLD` OR a non-empty ``requeries`` cue
    list), asks the grounding backend for additional context anchored
    on the lowest-confidence obligation's source clause.

    Best-effort: any failure inside the grounding backend (missing
    method, network error, NotImplementedError) degrades silently to an
    empty extra-context list. This keeps the Python demo path robust
    while still surfacing the re-query path in trace logs.

    Args:
      obligations: the reconciled obligation list from the panel.
      namespace: the Spanner demo/tenant namespace (passed through to
        the backend; some implementations need it for tenant filtering).
        Currently unused by ``query_graph_neighborhood`` but reserved
        for future per-namespace scoping.
      grounding: optional :class:`GroundingBackend`. Defaults to
        :func:`app.grounding.get_grounding_backend` — lazily imported
        so this module stays importable even before Track 1 lands the
        SpannerGraphBackend / get_grounding_backend factory.

    Returns:
      ``(decision, extra_context)`` where ``decision`` is the
      ReflectionDecision computed by :func:`reflect` and
      ``extra_context`` is the list of dicts returned by the backend's
      ``query_graph_neighborhood``. Empty list when no re-query
      happened or the backend couldn't fulfil the request.
    """
    decision = reflect(obligations)

    needs_requery = (
        decision.aggregate_confidence < LOW_CONFIDENCE_THRESHOLD
        or bool(decision.requeries)
    )
    if not needs_requery or not obligations:
        return decision, []

    if grounding is None:
        try:
            from app.grounding import get_grounding_backend  # lazy import
            grounding = get_grounding_backend()
        except Exception:  # noqa: BLE001 — best-effort
            return decision, []

    # Anchor the neighborhood query on the weakest-link obligation's
    # source clause. Stable, simple, and matches what an operator would
    # do triaging a low-confidence run.
    lowest = min(obligations, key=lambda o: o.confidence)
    node_id = lowest.source_clause_id

    query_method = getattr(grounding, "query_graph_neighborhood", None)
    if query_method is None:
        return decision, []

    try:
        extra = query_method(
            node_id=node_id,
            depth=2,
            requeries=decision.requeries,
        )
    except Exception:  # noqa: BLE001 — best-effort
        extra = None

    extra_list = list(extra) if extra else []

    # D7.5 fallback: if the local Spanner Graph returned nothing AND the
    # remote A2A bridge is enabled, query the external regulatory corpus
    # on the first re-query cue. Fail-quiet on any error.
    if not extra_list and decision.requeries:
        try:
            from app.tools.a2a_enrichment_client import is_enabled, regulatory_deep_lookup
            if is_enabled():
                extra_list = regulatory_deep_lookup(decision.requeries[0], k=3)
        except Exception:  # noqa: BLE001 — best-effort
            extra_list = []

    return decision, extra_list


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
    from app.llm import curator_model_name

    return Agent(
        name="reflector",
        model=Gemini(model=curator_model_name()),
        instruction=REFLECTOR_INSTRUCTION,
        description=(
            "Decides whether the panel's reconciled obligations are "
            "good enough or should be re-queried against Spanner Graph "
            "(D4+). Emits escalate=True in D2 unconditionally."
        ),
        output_schema=ReflectionDecision,
        output_key="reflection_decision",
    )
