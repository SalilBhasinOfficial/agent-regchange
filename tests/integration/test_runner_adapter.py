"""Phase 1 Step 1.1 smoke test for app/runners.py.

When ``CURATOR_REAL_LLM=1``, this test issues a real Gemini call against
``gemini-flash-latest`` to decompose one fixture clause and asserts that
the runner adapter returns a schema-validated ``list[Obligation]``. The
test is *skipped* when the flag is unset so the offline tier stays free
of GCP calls.

This is the airlock that proves the adapter works before we start
rewriting the 5 sub-agent ``real_*`` functions in Steps 1.2 and 1.3.
"""

from __future__ import annotations

import os

import pytest

from app.models import Obligation
from app.runners import RunnerError, run_agent

CRCB_CLAUSE = (
    "Clause MD-RBI-CAP-2025#11.5A: Every bank shall maintain an additional "
    "Climate Risk Capital Buffer of 0.25 per cent of RWAs in the form of CET1 "
    "capital, on an ongoing basis. The CRCB shall be phased in at 0.10 per cent "
    "of RWAs from October 1, 2026 and the full 0.25 per cent from April 1, 2027. "
    "The buffer shall be over and above the Capital Conservation Buffer."
)

DECOMPOSE_INSTRUCTION = (
    "Decompose this RBI regulatory clause into atomic Obligations matching the "
    "Obligation pydantic schema. Each Obligation has: id (string), "
    "source_clause_id (string), deontic_type (one of: must, must_not, may, "
    "should), subject (string), action (string), and optional condition, "
    "temporal_scope, owner_hint. Emit ONE obligation per distinct "
    "(subject, action, deadline) tuple — clauses encoding multiple deadlines "
    "MUST fan out into multiple obligations. Return JSON only, no prose."
)


@pytest.mark.skipif(
    os.environ.get("CURATOR_REAL_LLM", "0") != "1",
    reason="Set CURATOR_REAL_LLM=1 to run real-Gemini smoke tests",
)
def test_run_agent_returns_validated_obligation_list():
    """Round-trip an Agent through run_agent and validate the result."""
    from google.adk.agents import Agent
    from google.adk.models import Gemini

    agent = Agent(
        name="decompose_smoke",
        model=Gemini(model="gemini-flash-latest"),
        instruction=DECOMPOSE_INSTRUCTION,
        output_schema=list[Obligation],
    )

    result = run_agent(agent, CRCB_CLAUSE, output_schema=list[Obligation])

    assert isinstance(result, list), f"expected list, got {type(result)}"
    assert len(result) >= 2, (
        f"CRCB clause should fan out to ≥2 obligations (steady-state + "
        f"phase-in), got {len(result)}: {result}"
    )
    for obl in result:
        assert isinstance(obl, Obligation), f"item is not an Obligation: {obl!r}"
        assert obl.subject, "subject must be non-empty"
        assert obl.action, "action must be non-empty"
        assert obl.deontic_type, "deontic_type must be set"


@pytest.mark.skipif(
    os.environ.get("CURATOR_REAL_LLM", "0") != "1",
    reason="Set CURATOR_REAL_LLM=1 to run real-Gemini smoke tests",
)
def test_run_agent_raises_on_unparseable():
    """If we feed an agent without output_schema and pass a strict schema to
    run_agent, the validator should catch garbage. We achieve this by
    intentionally feeding a non-decompose instruction that won't return
    Obligation-shaped JSON; expect a RunnerError."""
    from google.adk.agents import Agent
    from google.adk.models import Gemini

    agent = Agent(
        name="garbage_smoke",
        model=Gemini(model="gemini-flash-latest"),
        instruction="Reply with the single word 'banana'. No JSON.",
    )

    with pytest.raises(RunnerError):
        run_agent(agent, "any prompt", output_schema=list[Obligation])


def test_flag_off_means_real_llm_disabled():
    """Sanity: with the env unset, real_llm_enabled() is False."""
    from app.runners import real_llm_enabled, require_real_llm

    saved = os.environ.pop("CURATOR_REAL_LLM", None)
    try:
        assert real_llm_enabled() is False
        with pytest.raises(RuntimeError, match="CURATOR_REAL_LLM"):
            require_real_llm("decompose")
    finally:
        if saved is not None:
            os.environ["CURATOR_REAL_LLM"] = saved
