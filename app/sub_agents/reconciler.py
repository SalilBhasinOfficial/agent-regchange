"""Reconciler — merges the four lens-specific obligation lists into one.

The Reconciler is **deterministic Python** by default: it dedupes by
``(source_clause_id, normalized_action)``, takes the union of optional
fields across lenses, and adjusts ``confidence`` and ``missing_evidence``
based on per-lens agreement (an obligation seen by all 4 lenses is high
confidence; an obligation seen by only 1 lens carries a dissent flag).

An ADK ``Agent`` factory is also provided for the ``adk run`` / A2A
discovery surface — judges browsing the agent card see the Reconciler
as a discoverable skill — but the demo path (`real_decompose` in
``app/sub_agents/decompose.py``) calls ``reconcile_obligations`` directly.
This mirrors the existing project decision (DECISIONS-pending):
deterministic Python for the demo; ADK agent for skill-card surface.
"""

from __future__ import annotations

import re
from collections import defaultdict

from app.models import DeonticType, Obligation
from app.sub_agents.lenses import LENS_NAMES


def _normalize_action(action: str) -> str:
    """Coarse fingerprint of an action string for dedup purposes.

    Lowercases, strips punctuation, collapses whitespace, drops the
    shortest filler words. Two near-paraphrases of the same obligation
    should collide; genuinely different actions should not. We're
    deliberately permissive — over-merging is the safer error here than
    surfacing two cosmetically-different versions of the same obligation.
    """
    text = action.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    tokens = [t for t in text.split() if len(t) > 3]
    return " ".join(sorted(tokens)[:8])


def _merge_obligations(group: list[tuple[str, Obligation]]) -> Obligation:
    """Merge a group of (lens_name, Obligation) entries into one Obligation."""
    base_lens, base = group[0]
    # Take the union of optional fields — first non-None wins.
    condition = next((o.condition for _, o in group if o.condition), None)
    temporal = next((o.temporal_scope for _, o in group if o.temporal_scope), None)
    owner = next((o.owner_hint for _, o in group if o.owner_hint), None)
    # Per-lens missing_evidence union
    union_evidence: list[str] = []
    for _, o in group:
        for entry in o.missing_evidence:
            if entry not in union_evidence:
                union_evidence.append(entry)

    seen_lenses = sorted({lens for lens, _ in group})
    missed_lenses = [lens for lens in LENS_NAMES if lens not in seen_lenses]
    for lens in missed_lenses:
        marker = f"not_seen_by:{lens}"
        if marker not in union_evidence:
            union_evidence.append(marker)

    # Confidence: average of lens confidences, scaled by agreement factor.
    avg_conf = sum(o.confidence for _, o in group) / len(group)
    agreement_factor = 0.6 + 0.1 * len(seen_lenses)  # 1 lens → 0.7×, 4 → 1.0×
    adjusted = min(1.0, max(0.0, avg_conf * agreement_factor))

    return Obligation(
        id=base.id,
        source_clause_id=base.source_clause_id,
        deontic_type=base.deontic_type,
        subject=base.subject,
        action=base.action,
        condition=condition,
        temporal_scope=temporal,
        owner_hint=owner,
        confidence=adjusted,
        missing_evidence=union_evidence,
    )


def reconcile_obligations(
    lens_outputs: dict[str, list[Obligation]],
) -> list[Obligation]:
    """Merge the per-lens obligation lists into one deduplicated list.

    Args:
        lens_outputs: mapping of lens_name → list[Obligation] produced by
            that lens. Keys are members of ``lenses.LENS_NAMES``.

    Returns:
        A single ``list[Obligation]`` where duplicates across lenses have
        been collapsed and ``confidence`` / ``missing_evidence`` reflect
        cross-lens agreement.
    """
    buckets: dict[tuple[str, str], list[tuple[str, Obligation]]] = defaultdict(list)
    for lens, obls in lens_outputs.items():
        for o in obls:
            key = (o.source_clause_id, _normalize_action(o.action))
            buckets[key].append((lens, o))

    merged: list[Obligation] = [_merge_obligations(group) for group in buckets.values()]
    # Stable sort by source clause id then by action prefix — readable demo output.
    merged.sort(key=lambda o: (o.source_clause_id, o.action))
    return merged


RECONCILER_INSTRUCTION = """You receive four lists of regulatory Obligations
extracted from the *same* amended clause by four different stakeholder
lenses (banker / compliance / auditor / customer-protect). Your job is
to produce one merged, deduplicated list.

Rules:
  * Two obligations describe the same regulatory duty if they share the
    same source_clause_id AND describe the same (subject, action) pair
    in different words. Merge them.
  * Prefer the most specific subject, the most specific action, and the
    most explicit temporal_scope across all entries.
  * Track which lenses contributed each obligation. If only some lenses
    caught it, append "not_seen_by:<lens_name>" entries to that
    obligation's missing_evidence list.
  * Set confidence to a blend of the contributing lenses' confidences
    AND a cross-lens agreement bonus — an obligation all four lenses
    independently extracted is high confidence (>=0.9); an obligation
    only one lens caught is lower confidence (<=0.7).
  * Never invent obligations not present in the input lists. Never drop
    an obligation entirely — if you have doubts, surface it with a
    low confidence and a missing_evidence entry.

Return the merged list as JSON matching the Obligation schema.
"""


def build_agent():  # type: ignore[no-untyped-def]
    """Construct the Reconciler ADK Agent for adk run / A2A surface.

    The demo path uses ``reconcile_obligations`` (Python) directly for
    deterministic, debuggable merging. This agent exists so the skill
    appears in the agent card and judges can browse it.
    """
    from google.adk.agents import Agent
    from google.adk.models import Gemini
    from app.llm import curator_model_name

    return Agent(
        name="reconciler",
        model=Gemini(model=curator_model_name()),
        instruction=RECONCILER_INSTRUCTION,
        description=(
            "Merges the four stakeholder-lens obligation lists into one "
            "deduplicated list with cross-lens-agreement confidence."
        ),
        output_schema=list[Obligation],
        output_key="reconciled_obligations",
    )
