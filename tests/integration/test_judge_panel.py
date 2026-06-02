"""D3 four-critic judge-panel smoke harness.

Mirrors ``test_parallel_smoke.py`` but for the judge side: the same
ParallelAgent / Reconciler / LoopAgent shape, applied to ImpactSummary
critics. Three tests, all gated on ``CURATOR_REAL_LLM=1`` so the
offline tier stays free of GCP calls.

  1. ``test_judge_parallel_agent_returns_per_critic_results``: the
     4-critic ParallelAgent populates 4 distinct state keys under
     ``InMemoryRunner.run_async``.
  2. ``test_real_judge_produces_impact_summary``: ``real_judge`` driven
     by a fixture-derived (obligations, matches, diffs) tuple returns
     an ImpactSummary with confidence set and non-empty
     downstream_effects.
  3. ``test_judge_loop_agent_terminates_via_reflector``: the ADK
     ``build_agent()``-returned LoopAgent runs and terminates within
     ``max_iterations``. Skips on 429 (Vertex per-minute quota),
     mirroring the decompose smoke.
"""

from __future__ import annotations

import os

import pytest

REAL_LLM = os.environ.get("CURATOR_REAL_LLM", "0") == "1"
SKIP_REASON = "Set CURATOR_REAL_LLM=1 to run real-Gemini smoke tests"


@pytest.mark.skipif(not REAL_LLM, reason=SKIP_REASON)
def test_judge_parallel_agent_returns_per_critic_results():
    """The 4-critic ParallelAgent must populate 4 distinct output_keys."""
    import asyncio

    from google.adk.agents import ParallelAgent
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    from app.sub_agents.judge_panel import (
        CRITIC_NAMES,
        CRITIC_STATE_KEYS,
        build_all_critic_agents,
    )

    critics = build_all_critic_agents()
    panel = ParallelAgent(name="judge_quad_panel", sub_agents=critics)
    app_name = "curator-judge-parallel-smoke"

    prompt = (
        "Regulatory Obligations:\n"
        "======================\n"
        "- Obligation ID: obl-test-cap\n"
        "  Subject: bank\n"
        "  Action: maintain CET1 capital buffer of 0.25% RWAs\n"
        "  Deontic Type: must\n"
        "  Owner Hint: CFO\n\n"
        "Policy Coverage Matches:\n"
        "=======================\n"
        "- Obligation ID: obl-test-cap\n"
        "  Policy Section: None\n"
        "  Coverage: missing\n"
        "  Confidence: 0.8\n"
        "  Rationale: No existing climate buffer policy.\n\n"
        "Suggested Diffs:\n"
        "================\n"
        "- Section: POL-CAP-001#s3\n"
        "  Rationale: Add CRCB clause.\n"
        "  Suggested Text snippet: The bank shall maintain a CRCB ...\n"
    )

    async def _drive():
        runner = InMemoryRunner(agent=panel, app_name=app_name)
        session = await runner.session_service.create_session(
            app_name=app_name, user_id="smoke"
        )
        content = types.Content(role="user", parts=[types.Part(text=prompt)])
        events = []
        async for ev in runner.run_async(
            user_id="smoke", session_id=session.id, new_message=content
        ):
            events.append(ev)
        final = await runner.session_service.get_session(
            app_name=app_name, user_id="smoke", session_id=session.id
        )
        return events, final.state

    try:
        events, state = asyncio.run(_drive())
    except Exception as e:
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err.upper():
            pytest.skip(f"Vertex AI rate limit hit: {err[:120]}")
        raise

    expected_keys = [CRITIC_STATE_KEYS[name] for name in CRITIC_NAMES]
    keys_seen = [k for k in expected_keys if k in state]
    assert len(keys_seen) == 4, (
        f"expected all 4 critic output_keys populated in state, "
        f"got {keys_seen}; full state keys: {list(state.keys())}; "
        f"events: {len(events)}"
    )


@pytest.mark.skipif(not REAL_LLM, reason=SKIP_REASON)
def test_real_judge_produces_impact_summary():
    """real_judge on the offline-chain-derived fixture must yield an
    ImpactSummary with confidence set and non-empty downstream_effects."""
    from app.chain import load_demo_amendment
    from app.grounding import MockGroundingBackend
    from app.models import ImpactSummary
    from app.sub_agents.decompose import stub_decompose
    from app.sub_agents.diff import stub_diff
    from app.sub_agents.judge import real_judge
    from app.sub_agents.map_ import stub_map

    _, clauses = load_demo_amendment()
    backend = MockGroundingBackend()
    policies = backend.load_bank_policies()
    obligations = stub_decompose(clauses)
    matches = stub_map(obligations, policies)
    diffs = stub_diff(matches, obligations, policies)

    try:
        impact = real_judge(obligations, matches, diffs)
    except Exception as e:
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err.upper():
            pytest.skip(f"Vertex AI rate limit hit: {err[:120]}")
        raise

    assert isinstance(impact, ImpactSummary)
    assert 0.0 <= impact.confidence <= 1.0
    assert impact.priority in {"low", "medium", "high", "critical"}
    assert impact.downstream_effects, (
        "panel-merged downstream_effects must be non-empty — the 4-critic "
        "fan-out is supposed to surface effects a single judge would miss"
    )


@pytest.mark.skipif(not REAL_LLM, reason=SKIP_REASON)
def test_judge_loop_agent_terminates_via_reflector():
    """The ADK-idiomatic build_agent() returns a LoopAgent. Confirm one
    invocation terminates within max_iterations=3 (D2 Reflector always
    escalates)."""
    import asyncio

    from google.adk.runners import InMemoryRunner
    from google.genai import types

    from app.sub_agents.judge import build_agent

    agent = build_agent()
    app_name = "curator-judge-loop-smoke"

    prompt = (
        "Regulatory Obligations:\n"
        "======================\n"
        "- Obligation ID: obl-test-cap\n"
        "  Subject: bank\n"
        "  Action: maintain CET1 capital buffer of 0.25% RWAs\n"
        "  Deontic Type: must\n"
        "  Owner Hint: CFO\n\n"
        "Policy Coverage Matches:\n"
        "=======================\n"
        "- Obligation ID: obl-test-cap\n"
        "  Policy Section: None\n"
        "  Coverage: missing\n"
        "  Confidence: 0.8\n"
        "  Rationale: No existing climate buffer policy.\n\n"
        "Suggested Diffs:\n"
        "================\n"
        "- Section: POL-CAP-001#s3\n"
        "  Rationale: Add CRCB clause.\n"
        "  Suggested Text snippet: The bank shall maintain a CRCB ...\n"
    )

    async def _drive():
        runner = InMemoryRunner(agent=agent, app_name=app_name)
        session = await runner.session_service.create_session(
            app_name=app_name, user_id="smoke"
        )
        content = types.Content(role="user", parts=[types.Part(text=prompt)])
        events = []
        async for ev in runner.run_async(
            user_id="smoke", session_id=session.id, new_message=content
        ):
            events.append(ev)
        return events

    try:
        events = asyncio.run(_drive())
    except Exception as e:
        # 4 critics + reconciler + reflector in a tight burst hits the
        # Vertex per-minute quota easily. The demo path uses
        # ThreadPoolExecutor in `real_judge` with controlled concurrency,
        # so this is a test-environment issue, not architectural. Skip
        # on 429; the other two tests are the authoritative D3 de-risks.
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err.upper():
            pytest.skip(f"Vertex AI rate limit hit: {err[:120]}")
        raise
    assert events, "LoopAgent emitted no events"
    # 4 critics + reconciler + reflector = ≤6 LLM responses per outer
    # iteration. Generous headroom below; flag a runaway >50.
    assert len(events) < 50, (
        f"LoopAgent produced {len(events)} events; expected single iteration. "
        f"Reflector may not be escalating."
    )
