"""Mapper — Obligation × PolicyDocument → PolicyMatch.

For every obligation produced by the decomposer, find the bank's
internal policy section(s) that address it. ``missing`` is a valid
(and often the most actionable) coverage value.
"""

from __future__ import annotations

import os

from app.models import Obligation, PolicyDocument, PolicyMatch

MAP_INSTRUCTION = """You map regulatory obligations to a bank's internal
policies and SOPs.

For each Obligation you receive, search the supplied PolicyDocuments
and decide the best-matching PolicySection. Output exactly one
PolicyMatch per obligation, with:

  * coverage — one of:
      full        — the section fully addresses the obligation as worded
      partial     — the section addresses part of it
      missing     — no internal policy section addresses this obligation
                    (set policy_section_id to None)
      stale       — the section addresses an older version of the rule
                    and is now out of date
      contradicts — the section actively conflicts with the obligation
  * confidence — 0.0–1.0, your calibrated confidence in the mapping
  * rationale  — one short sentence justifying the call

Be strict about 'full' — partial coverage is the more common honest
answer for a real RBI amendment, and surfacing it is the whole point.

For EACH PolicyMatch also emit:
  * missing_evidence — short list of strings naming evidence you wanted
                       but couldn't find in the supplied PolicySections
                       (e.g. ["scope statement", "applicability to retail
                       portfolio"]). Empty list if no gap. The Reflector
                       reads this list to drive a targeted Spanner re-query.
"""


# Distinctive tokens the stub treats as "novel concepts" — if the
# obligation mentions one and the candidate section does not, the
# stub downgrades coverage. Keeps the climate-buffer fan-out demo
# honest without needing real semantic search.
_NOVEL_TOKENS = {"climate", "quarterly", "quarter"}


def stub_map(
    obligations: list[Obligation], policies: list[PolicyDocument]
) -> list[PolicyMatch]:
    """Deterministic token-overlap mapping for stage-1 fixtures.

    TODO(stage-2): replace with Gemini reasoning grounded in retrieval
    over the bank's policy corpus via Vertex AI RAG Engine.
    """
    out: list[PolicyMatch] = []
    sections = [s for p in policies for s in p.sections]
    for obl in obligations:
        action_lc = obl.action.lower()
        terms = {w.lower() for w in obl.action.split() if len(w) > 4}
        best_section = None
        best_score = 0
        for s in sections:
            score = sum(1 for t in terms if t in s.text.lower())
            if score > best_score:
                best_score = score
                best_section = s

        novel_in_obligation = {t for t in _NOVEL_TOKENS if t in action_lc}
        novel_in_section = (
            {t for t in novel_in_obligation if t in best_section.text.lower()}
            if best_section
            else set()
        )
        novel_gap = bool(novel_in_obligation - novel_in_section)

        if best_section is None or best_score < 2 or (
            novel_gap and best_score < 5
        ):
            out.append(
                PolicyMatch(
                    obligation_id=obl.id,
                    policy_section_id=None,
                    coverage="missing",
                    confidence=0.7 if novel_gap else 0.5,
                    rationale=(
                        "No internal section addresses the novel concept(s): "
                        f"{sorted(novel_in_obligation)} (stub)."
                        if novel_gap
                        else "No overlapping internal section found (stub)."
                    ),
                )
            )
            continue

        coverage = "full" if best_score >= 5 else "partial"
        out.append(
            PolicyMatch(
                obligation_id=obl.id,
                policy_section_id=best_section.policy_section_id,
                coverage=coverage,
                confidence=min(0.4 + 0.1 * best_score, 0.95),
                rationale=f"Token overlap with '{best_section.heading}' (stub).",
            )
        )
    return out


def real_map(
    obligations: list[Obligation], policies: list[PolicyDocument]
) -> list[PolicyMatch]:
    """Gemini-driven classification of obligation coverage against bank policies.

    D5 speed-lift: obligations are now mapped concurrently via a
    ThreadPoolExecutor (up to ``CURATOR_MAP_CONCURRENCY`` workers,
    default 8). Each obligation is still one Gemini call; the parallel
    fan-out drops wall-clock from O(N) to O(N/8) for the typical
    20-obligation chain.
    """
    from concurrent.futures import ThreadPoolExecutor
    from app.runners import require_real_llm, run_agent
    require_real_llm("map")

    agent = build_agent()

    # Flatten sections from all policies (built once, reused per prompt).
    sections = [s for p in policies for s in p.sections]
    sections_text = "\n".join(
        f"Section ID: {s.policy_section_id}\nHeading: {s.heading}\nText: {s.text}\n---"
        for s in sections
    )

    def _format_prompt(obl: Obligation) -> str:
        return (
            f"Candidate Internal Policy Sections:\n"
            f"===================================\n"
            f"{sections_text}\n\n"
            f"Regulatory Obligation to Map:\n"
            f"============================\n"
            f"Obligation ID: {obl.id}\n"
            f"Source Clause ID: {obl.source_clause_id}\n"
            f"Subject: {obl.subject}\n"
            f"Action: {obl.action}\n"
            f"Deontic Type: {obl.deontic_type.value}\n"
            f"Temporal Scope: {obl.temporal_scope or 'None'}\n"
        )

    def _map_one(obl: Obligation) -> PolicyMatch:
        res = run_agent(agent, _format_prompt(obl), output_schema=PolicyMatch)
        res.obligation_id = obl.id
        if res.coverage == "missing":
            res.policy_section_id = None
        return res

    max_workers = int(os.environ.get("CURATOR_MAP_CONCURRENCY", "8"))
    out: list[PolicyMatch] = [None] * len(obligations)  # type: ignore[list-item]
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for i, fut in enumerate(ex.map(_map_one, obligations)):
                out[i] = fut
    except Exception:  # pragma: no cover - degraded path; sequential fallback
        out = [_map_one(obl) for obl in obligations]
    return out


def build_agent():  # type: ignore[no-untyped-def]
    from google.adk.agents import Agent
    from google.adk.models import Gemini
    from app.llm import curator_model_name

    return Agent(
        name="map_agent",
        model=Gemini(model=curator_model_name()),
        instruction=MAP_INSTRUCTION,
        description=(
            "Maps each obligation to the best-matching internal policy "
            "section and labels coverage."
        ),
        output_schema=PolicyMatch,
    )
