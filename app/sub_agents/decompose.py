"""Decomposer — amendment text → atomic obligations.

A single amended clause routinely fans out into several distinct
obligations (different actors, different timelines, different cadences).
That fan-out is the demo's key moment, so the decomposer is the first
node in the chain and its output drives everything downstream.
"""

from __future__ import annotations

from app.models import AmendedClause, DeonticType, Obligation

DECOMPOSE_INSTRUCTION = """You decompose RBI Master Direction amendments into
atomic regulatory obligations.

For each amended clause you receive, emit one Obligation per distinct
(subject, action) pair. Different cadences, different deadlines, and
different responsible owners are all signals that a clause has fanned
out and should produce more than one obligation.

For each Obligation:
  * subject       — the regulated entity ("bank", "board of directors",
                    "Risk Management Committee", etc.). Be specific.
  * action        — a single verb phrase describing what is required.
  * deontic_type  — MUST / MUST_NOT / MAY / SHOULD, based on the modal
                    verb ("shall" → MUST, "shall not" → MUST_NOT,
                    "may" → MAY, "should/is encouraged to" → SHOULD).
  * condition     — any triggering condition. None if unconditional.
  * temporal_scope — deadlines or cadences ("within 30 days of …",
                    "quarterly", "at each board meeting").
  * owner_hint    — likely internal owner (CFO, CRO, Compliance,
                    Board, ICAAP committee). None if not derivable.

Return obligations as a JSON list matching the Obligation schema.
Do not paraphrase the source clause — extract, don't invent.

For EACH Obligation also emit:
  * confidence       — 0.0 to 1.0, your calibrated trust in the extraction.
                       Below 0.6 will trigger the Reflector to re-query.
                       Default to 0.7; raise to 0.9+ for clear, unambiguous
                       extractions; lower for ambiguous or fan-out-uncertain.
  * missing_evidence — a short list of strings naming evidence you wanted
                       but couldn't find (e.g. ["effective date", "owner",
                       "implementation guidance"]). Empty list if fully
                       confident. The Reflector reads this list to drive
                       a targeted re-query of the regulatory graph.

Example 1:
Input clause:
{
  "clause_id": "MD-RBI-CAP-2025#11.5A",
  "heading": "Climate Risk Capital Buffer",
  "new_text": "Every bank shall maintain an additional Climate Risk Capital Buffer of 0.25 per cent of RWAs in the form of CET1 capital, on an ongoing basis. The CRCB shall be phased in at 0.10 per cent of RWAs from October 1, 2026 and the full 0.25 per cent from April 1, 2027. The buffer shall be over and above the Capital Conservation Buffer."
}
Expected Output:
[
  {
    "id": "obl-MD-RBI-CAP-2025#11.5A-phasein",
    "source_clause_id": "MD-RBI-CAP-2025#11.5A",
    "deontic_type": "must",
    "subject": "bank",
    "action": "phase in Climate Risk Capital Buffer at 0.10 per cent of RWAs",
    "condition": null,
    "temporal_scope": "from October 1, 2026 to March 31, 2027",
    "owner_hint": "CFO"
  },
  {
    "id": "obl-MD-RBI-CAP-2025#11.5A-steady",
    "source_clause_id": "MD-RBI-CAP-2025#11.5A",
    "deontic_type": "must",
    "subject": "bank",
    "action": "maintain additional Climate Risk Capital Buffer of 0.25 per cent of RWAs in the form of CET1 capital over and above the Capital Conservation Buffer",
    "condition": null,
    "temporal_scope": "on an ongoing basis from April 1, 2027",
    "owner_hint": "CFO"
  }
]
"""


def stub_decompose(clauses: list[AmendedClause]) -> list[Obligation]:
    """Deterministic placeholder decomposition.

    Most clauses fan out 1:1 in the stub, but two clauses in the demo
    fixture are recognised by heading and forced to fan out:

      * "Climate Risk Capital Buffer" → 2 obligations (steady-state +
        phase-in transition) — the demo's signature fan-out moment.
      * "Pillar 3 disclosure for the CRCB" → 2 obligations (policy
        update + quantitative breakdown by exposure class).

    TODO(stage-2): replace with a Gemini-driven extraction. The
    real path will fan out from clause semantics rather than headings.
    """
    out: list[Obligation] = []
    for c in clauses:
        heading = (c.heading or "").lower()
        if "climate risk capital buffer" in heading:
            out.append(
                Obligation(
                    id=f"obl-{c.clause_id}-steady",
                    source_clause_id=c.clause_id,
                    deontic_type=DeonticType.MUST,
                    subject="bank",
                    action=(
                        "maintain Climate Risk Capital Buffer of 0.25% of "
                        "RWAs in CET1 capital on an ongoing basis"
                    ),
                    condition=None,
                    temporal_scope="from 2027-04-01 onwards",
                    owner_hint="CFO",
                    confidence=1.0,
                )
            )
            out.append(
                Obligation(
                    id=f"obl-{c.clause_id}-phasein",
                    source_clause_id=c.clause_id,
                    deontic_type=DeonticType.MUST,
                    subject="bank",
                    action=(
                        "phase in Climate Risk Capital Buffer at 0.10% of "
                        "RWAs from 2026-10-01"
                    ),
                    condition=None,
                    temporal_scope="2026-10-01 to 2027-03-31",
                    owner_hint="CFO",
                    confidence=1.0,
                )
            )
            continue
        if "pillar 3 disclosure for the crcb" in heading:
            out.append(
                Obligation(
                    id=f"obl-{c.clause_id}-policy",
                    source_clause_id=c.clause_id,
                    deontic_type=DeonticType.MUST,
                    subject="bank",
                    action="update Pillar 3 disclosure policy to include CRCB",
                    temporal_scope="from FY 2027-28",
                    owner_hint="Investor Relations",
                    confidence=1.0,
                )
            )
            out.append(
                Obligation(
                    id=f"obl-{c.clause_id}-template",
                    source_clause_id=c.clause_id,
                    deontic_type=DeonticType.MUST,
                    subject="bank",
                    action=(
                        "disclose Climate Risk Capital Buffer with "
                        "quantitative breakdown by exposure class"
                    ),
                    temporal_scope="annually from FY 2027-28",
                    owner_hint="Investor Relations",
                    confidence=1.0,
                )
            )
            continue
        # default 1:1 fall-through
        out.append(
            Obligation(
                id=f"obl-{c.clause_id}",
                source_clause_id=c.clause_id,
                deontic_type=DeonticType.MUST,
                subject="bank",
                action=c.new_text[:120],
                condition=None,
                temporal_scope=None,
                owner_hint=None,
                confidence=1.0,
            )
        )
    return out


def _format_clause_prompt(c: AmendedClause) -> str:
    return (
        f"Clause ID: {c.clause_id}\n"
        f"Heading: {c.heading or 'N/A'}\n"
        f"Old Text: {c.old_text or 'None'}\n"
        f"New Text: {c.new_text}"
    )


def _force_canonical_ids(obls: list[Obligation], c: AmendedClause) -> list[Obligation]:
    """Stage-1-compatible ID normalisation. Demo expects ``obl-<clause>-<suffix>``."""
    for i, obl in enumerate(obls):
        obl.source_clause_id = c.clause_id
        if not obl.id or obl.id == "NEW" or not obl.id.startswith("obl-"):
            act_lc = obl.action.lower()
            if "steady" in act_lc or "0.25" in obl.action:
                suffix = "steady"
            elif "phase" in act_lc or "0.10" in obl.action:
                suffix = "phasein"
            else:
                suffix = str(i)
            obl.id = f"obl-{c.clause_id}-{suffix}"
    return obls


def _real_decompose_single_shot(clauses: list[AmendedClause]) -> list[Obligation]:
    """Legacy single-agent path. Retained as the GEPA baseline reference and
    for the ``CURATOR_DECOMPOSE_MODE=single`` fallback. The default path is
    the four-lens panel (:func:`real_decompose`)."""
    from app.runners import run_agent

    agent = _build_single_decompose_agent()
    out: list[Obligation] = []
    for c in clauses:
        res = run_agent(agent, _format_clause_prompt(c), output_schema=list[Obligation])
        out.extend(_force_canonical_ids(res, c))
    return out


def real_decompose(clauses: list[AmendedClause]) -> list[Obligation]:
    """Four-lens debate-panel decomposition with reconciliation + reflection.

    Demo path (D2+). Each clause is decomposed by four lenses concurrently
    (banker / compliance / auditor / customer-protect). The Reconciler
    merges the four obligation lists by (source_clause_id, action), and
    the Reflector inspects aggregate confidence (D2 stub: always
    terminates; D4 wires Spanner re-query for low-confidence cases).

    Set ``CURATOR_DECOMPOSE_MODE=single`` to force the legacy single-shot
    agent (kept for GEPA baseline runs and quick comparison demos).
    """
    import os
    from app.runners import require_real_llm

    require_real_llm("decompose")

    mode = os.environ.get("CURATOR_DECOMPOSE_MODE", "panel").strip().lower()
    if mode == "single":
        return _real_decompose_single_shot(clauses)

    # Lazy imports — keep this file importable without ADK installed.
    from app.sub_agents.lenses import LENS_NAMES, build_all_lens_agents
    from app.sub_agents.reconciler import reconcile_obligations
    from app.sub_agents.reflector import reflect

    lens_agents = build_all_lens_agents()

    out: list[Obligation] = []
    for c in clauses:
        lens_outputs = _run_panel(lens_agents, _format_clause_prompt(c))
        # Force IDs *before* reconciliation so dedup keys are consistent.
        for lens_name in LENS_NAMES:
            lens_outputs[lens_name] = _force_canonical_ids(
                lens_outputs[lens_name], c
            )
        merged = reconcile_obligations(lens_outputs)
        decision = reflect(merged)
        # D2: decision.escalate is always True (no Spanner re-query yet).
        # The decision is *logged* implicitly via the obligations'
        # missing_evidence + confidence; D4 will branch here.
        if not decision.escalate:  # pragma: no cover - D4 path
            # placeholder for the D4 Spanner re-query branch.
            pass
        out.extend(merged)
    return out


def _run_panel(lens_agents, prompt: str) -> dict[str, list[Obligation]]:
    """Execute the four lens agents concurrently against the same prompt.

    Uses ThreadPoolExecutor so each lens call goes through the existing
    ``run_agent`` (which manages its own event loop). Falls back to
    sequential execution if the executor errors — better a slow correct
    panel than a flaky one.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from app.runners import run_agent

    results: dict[str, list[Obligation]] = {}
    try:
        with ThreadPoolExecutor(max_workers=len(lens_agents)) as ex:
            fut_to_name = {
                ex.submit(
                    run_agent, agent, prompt, list[Obligation], lens=agent.name
                ): agent.name
                for agent in lens_agents
            }
            for fut in as_completed(fut_to_name):
                results[fut_to_name[fut]] = fut.result()
    except Exception:  # pragma: no cover - degraded path
        # Sequential fallback. Same return shape.
        results = {}
        for agent in lens_agents:
            results[agent.name] = run_agent(
                agent, prompt, list[Obligation], lens=agent.name
            )
    return results


def _build_single_decompose_agent():  # type: ignore[no-untyped-def]
    """The legacy one-shot decompose agent. Used for the single-mode fallback."""
    from google.adk.agents import Agent
    from google.adk.models import Gemini
    from app.llm import curator_model_name

    return Agent(
        name="decompose_agent_single",
        model=Gemini(model=curator_model_name()),
        instruction=DECOMPOSE_INSTRUCTION,
        description=(
            "Single-agent decomposition of amended RBI clauses (legacy/GEPA "
            "baseline). The default demo path is the four-lens panel."
        ),
        output_schema=list[Obligation],
    )


def build_agent():  # type: ignore[no-untyped-def]
    """Construct the ADK-idiomatic debate-panel decompose graph.

    Returns ``SequentialAgent(ParallelAgent(4 lenses), Reconciler)`` —
    the Reconciler is the last sub-agent so its ``list[Obligation]``
    output is what bubbles up as the final response to ``adk run`` / the
    A2A agent card / ``adk eval``.

    The Reflector deliberately does NOT live in this ADK graph. It runs
    in the Python demo path (:func:`real_decompose`) where it controls
    optional Spanner re-query (D4+). Surfacing the Reflector as the
    last sub-agent inside a ``LoopAgent`` would cause the parent to see
    the Reflector's ``ReflectionDecision`` JSON as the final response
    instead of the obligations — verified by the D3 Gate-1 eval where
    that exact failure mode produced rubric scores of 0.0. The
    Reflector still exists as a standalone ADK Agent factory in
    ``app/sub_agents/reflector.py`` for A2A skill discoverability.

    Falls back to the single-agent shape when
    ``CURATOR_DECOMPOSE_MODE=single`` is set.
    """
    import os

    mode = os.environ.get("CURATOR_DECOMPOSE_MODE", "panel").strip().lower()
    if mode == "single":
        return _build_single_decompose_agent()

    from google.adk.agents import ParallelAgent, SequentialAgent

    from app.sub_agents.lenses import build_all_lens_agents
    from app.sub_agents.reconciler import build_agent as build_reconciler

    panel = ParallelAgent(
        name="decompose_panel",
        sub_agents=build_all_lens_agents(),
        description=(
            "Four-lens stakeholder panel that decomposes the amended clause "
            "from banker / compliance / auditor / customer-protect angles."
        ),
    )
    return SequentialAgent(
        name="decompose_agent",
        sub_agents=[panel, build_reconciler()],
        description=(
            "Debate-panel decompose: 4-lens fan-out → Reconciler. The "
            "Python demo path (real_decompose) additionally runs the "
            "Reflector for optional Spanner re-query (D4+)."
        ),
    )
