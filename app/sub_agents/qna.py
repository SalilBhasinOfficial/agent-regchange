"""Q&A — interactive follow-up over the change-analysis package.

The Q&A agent answers questions about the analysis already produced
(obligations, matches, diffs, impact). It cites obligation ids and
policy section ids in its answers so the user can navigate back to
specifics.
"""

from __future__ import annotations

from app.models import AgentState, QnATurn

QNA_INSTRUCTION = """You are a regulatory analyst answering follow-up
questions about a completed regulatory-change analysis package for an
Indian BFSI compliance team.

You have access, in the JSON state, to:
  * amendment.raw_text          — the FULL text of the new/amending document
  * amended_clauses[].new_text  — the full new clause text (and old_text
                                  where the clause supersedes a prior rule)
  * obligations[]               — the structured obligations decomposed so far
  * policies / matches / diffs  — coverage mapping (may be empty for a
                                  document-vs-document comparison)
  * impact                      — the judge's ImpactSummary

How to answer — READ THE RAW TEXT, do not rely only on the structured fields:
  * The structured obligations may be a partial sample (the chain can run in
    a fast/capped mode). The authoritative source is amendment.raw_text and
    amended_clauses[].new_text/old_text. Always read those before saying
    something is "not covered".
  * QUANTITATIVE questions (e.g. "impact on Pillar-1 CRAR", "risk weight
    change"): find the specific numbers in the text — risk-weight
    percentages, LTV bands, base-rate formulae, capital charges — and give
    a DIRECTIONAL, grounded answer: which exposure classes move, old → new
    value, and the qualitative effect on RWA / CRAR (higher risk weight →
    higher RWA → lower CRAR, all else equal). State explicitly that an exact
    bps impact needs the bank's exposure mix; do not fabricate a number.
  * DATE questions ("when does this come into effect?"): quote the precise
    commencement language from the text (e.g. "with effect from 1 April
    2025", "the date of issue", "for the quarter ending..."). If the text
    only says "date of issue", say so AND give that issue date if present in
    amendment.effective_date or the document header.
  * Cite specific clause ids / obligation ids / policy section ids you used.
  * Only say "the analysis does not address this" when the answer is genuinely
    absent from BOTH the raw text and the structured fields — then say what
    additional document or data would answer it.
  * Do not invent obligations, citations, numbers, or recommendations.

Also emit:
  * confidence       — 0.0 to 1.0, your calibrated trust in this answer.
                       Default 0.7. Lower when the question pushes past
                       what the analysis covers; the Reflector may re-query
                       Spanner Graph for additional context.
  * missing_evidence — short list naming evidence you wanted (e.g.
                       ["full text of clause MD-RBI-CAP-2025#11.5A",
                       "bank's prior ICAAP submission"]). Empty if
                       confident.
"""


def stub_qna(state: AgentState, question: str) -> QnATurn:
    """Deterministic placeholder answer.

    TODO(stage-2): replace with a Gemini call over the structured
    AgentState plus retrieval over the underlying corpus.
    """
    citations = (
        [o.id for o in state.obligations[:3]]
        + [m.policy_section_id for m in state.matches[:3] if m.policy_section_id]
    )
    answer = (
        f"(stub answer) {len(state.obligations)} obligations are in scope. "
        f"{sum(1 for m in state.matches if m.coverage == 'missing')} have "
        f"no internal policy coverage. Ask the judge_agent for impact."
    )
    return QnATurn(question=question, answer=answer, citations=citations, confidence=1.0)


def real_qna(state: AgentState, question: str) -> QnATurn:
    """Gemini-driven interactive Q&A over the completed change-analysis state.

    When ``CURATOR_A2A_BEARER`` is set, the prompt is enriched with snippets
    from the remote A2A regulatory-corpus gateway. Offline-safe: with the
    env var unset (the default), enrichment is a no-op and the prompt
    composition matches the pre-D7.5 behavior.
    """
    from app.runners import require_real_llm, run_agent
    from app.tools.a2a_enrichment_client import is_enabled, regulatory_deep_lookup
    require_real_llm("qna")

    agent = build_agent()

    state_json = state.model_dump_json(indent=2)

    enrichment_block = ""
    if is_enabled():
        snippets = regulatory_deep_lookup(question, k=5)
        if snippets:
            enrichment_block = (
                "\nA2A Enrichment (external regulatory corpus, cite as [ext#N]):\n"
                "==============================================================\n"
                + "\n".join(
                    f"[ext#{i+1}] {s.get('title', 'untitled')} — {s.get('source_url', '')}\n"
                    f"  {s.get('snippet', '')}"
                    for i, s in enumerate(snippets)
                )
                + "\n"
            )

    prompt = (
        f"Completed Change Analysis Package State (JSON):\n"
        f"===========================================\n"
        f"{state_json}\n"
        f"{enrichment_block}\n"
        f"User Question:\n"
        f"=============="
        f"{question}\n"
    )

    res = run_agent(agent, prompt, output_schema=QnATurn)
    res.question = question
    return res


def build_agent():  # type: ignore[no-untyped-def]
    from google.adk.agents import Agent
    from google.adk.models import Gemini
    from app.llm import curator_generation_config, curator_model_name

    return Agent(
        name="qna_agent",
        model=Gemini(model=curator_model_name()),
        generate_content_config=curator_generation_config(),
        instruction=QNA_INSTRUCTION,
        description=(
            "Answers follow-up questions about a completed regulatory-"
            "change analysis package, with citations."
        ),
        output_schema=QnATurn,
    )
