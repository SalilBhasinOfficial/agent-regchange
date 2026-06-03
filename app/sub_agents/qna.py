"""Q&A — interactive follow-up over the change-analysis package.

The Q&A agent answers questions about the analysis already produced
(obligations, matches, diffs, impact). It cites obligation ids and
policy section ids in its answers so the user can navigate back to
specifics.
"""

from __future__ import annotations

from app.models import AgentState, QnATurn

QNA_INSTRUCTION = """You answer follow-up questions about a completed
regulatory-change analysis package.

You have access to:
  * the original Amendment input
  * the AmendedClauses extracted from it
  * the Obligations decomposed from those clauses
  * the bank's PolicyDocuments
  * the PolicyMatches and PolicyDiffs produced by the chain
  * the ImpactSummary produced by the judge

When answering:
  * Cite obligation ids (e.g. obl-c12-0) and policy section ids
    (e.g. POL-LIQ-001#s2) in your answers.
  * If the user asks a question the analysis does not address, say so
    plainly and recommend re-running the chain.
  * Do not invent obligations, citations, or recommendations.

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

    When ``BBB_MCP_BEARER`` is set, the prompt is enriched with snippets
    from the remote A2A regulatory-corpus gateway. Offline-safe: with the
    env var unset (the default), enrichment is a no-op and the prompt
    composition matches the pre-D7.5 behavior.
    """
    from app.runners import require_real_llm, run_agent
    from app.tools.bbb_a2a_client import is_enabled, regulatory_deep_lookup
    require_real_llm("qna")

    agent = build_agent()

    state_json = state.model_dump_json(indent=2)

    enrichment_block = ""
    if is_enabled():
        snippets = regulatory_deep_lookup(question, k=5)
        if snippets:
            enrichment_block = (
                "\nA2A Enrichment (external regulatory corpus, cite as [bbb#N]):\n"
                "==============================================================\n"
                + "\n".join(
                    f"[bbb#{i+1}] {s.get('title', 'untitled')} — {s.get('source_url', '')}\n"
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

    return Agent(
        name="qna_agent",
        model=Gemini(model="gemini-flash-latest"),
        instruction=QNA_INSTRUCTION,
        description=(
            "Answers follow-up questions about a completed regulatory-"
            "change analysis package, with citations."
        ),
        output_schema=QnATurn,
    )
