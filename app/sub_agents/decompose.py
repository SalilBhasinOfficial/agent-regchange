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


def real_decompose(clauses: list[AmendedClause]) -> list[Obligation]:
    """Gemini-driven decomposition of amended clauses into atomic obligations."""
    from app.runners import require_real_llm, run_agent
    require_real_llm("decompose")

    agent = build_agent()
    
    out: list[Obligation] = []
    for c in clauses:
        prompt = (
            f"Clause ID: {c.clause_id}\n"
            f"Heading: {c.heading or 'N/A'}\n"
            f"Old Text: {c.old_text or 'None'}\n"
            f"New Text: {c.new_text}"
        )
        res = run_agent(agent, prompt, output_schema=list[Obligation])
        # Force correct metadata linkage and unique IDs
        for i, obl in enumerate(res):
            obl.source_clause_id = c.clause_id
            if not obl.id or obl.id == "NEW" or not obl.id.startswith("obl-"):
                # suffix based on subject/action uniqueness or index
                suffix = "steady" if "steady" in obl.action.lower() or "0.25" in obl.action else ("phasein" if "phase" in obl.action.lower() or "0.10" in obl.action else str(i))
                obl.id = f"obl-{c.clause_id}-{suffix}"
            out.append(obl)
    return out


def build_agent():  # type: ignore[no-untyped-def]
    """Construct the ADK Agent. Lazy — keeps import-time GCP-free."""
    from google.adk.agents import Agent
    from google.adk.models import Gemini

    return Agent(
        name="decompose_agent",
        model=Gemini(model="gemini-flash-latest"),
        instruction=DECOMPOSE_INSTRUCTION,
        description=(
            "Decomposes amended RBI clauses into atomic obligations. One "
            "clause can yield several obligations with distinct owners "
            "and timelines."
        ),
        output_schema=list[Obligation],
    )
