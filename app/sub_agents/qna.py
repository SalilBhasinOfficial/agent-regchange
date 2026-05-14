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
    return QnATurn(question=question, answer=answer, citations=citations)


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
    )
