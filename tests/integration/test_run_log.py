"""Tests for the agent_runs observability writer.

Three tests, two of which run fully offline (the airlock for D4):

  * ``test_log_run_disabled_no_op`` — with ``CURATOR_AGENT_RUN_LOG``
    unset, ``log_run`` returns ``None`` without touching Spanner.
  * ``test_log_run_threadlocal_propagation`` — ``ContextVar`` is correctly
    inherited by ThreadPoolExecutor workers, so every panel call shares
    a single ``pipeline_run_id``.
  * ``test_log_run_live`` — opt-in (``CURATOR_AGENT_RUN_LOG=1`` AND
    ``CURATOR_LIVE_GCP=1``). Round-trips a real row into Spanner.
    Hard-skipped otherwise so CI stays free of GCP credentials.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.observability import run_log
from app.observability.run_log import (
    ENV_ENABLE,
    begin_pipeline_run,
    current_pipeline_run_id,
    log_run,
)


def test_log_run_disabled_no_op(monkeypatch):
    """Default offline path: flag unset → log_run returns None, no client."""
    monkeypatch.delenv(ENV_ENABLE, raising=False)

    # Reset the module-level cache to make sure no prior test polluted it.
    monkeypatch.setattr(run_log, "_database", None, raising=False)
    monkeypatch.setattr(run_log, "_client_init_failed", False, raising=False)

    # Tripwire: if anything tries to construct a Spanner Database, fail.
    def _explode(*_a, **_kw):
        raise AssertionError(
            "log_run must not construct a Spanner client when the env flag is off"
        )

    monkeypatch.setattr(run_log, "_get_database", _explode)

    result = log_run(
        agent_name="test_agent",
        input_text="hello",
        output_text="world",
    )
    assert result is None, "log_run with flag off must return None"


def test_log_run_threadlocal_propagation(monkeypatch):
    """ContextVar must propagate ``pipeline_run_id`` into pool workers."""
    monkeypatch.setenv(ENV_ENABLE, "1")

    # Replace the Spanner write with an in-memory recorder so we can assert
    # what *would* have been written without touching GCP.
    recorded: list[dict] = []

    def _fake_get_database():
        return object()  # truthy sentinel — the real write is replaced below.

    def _fake_log_run(
        *,
        agent_name,
        input_text,
        output_text,
        lens=None,
        confidence=None,
        latency_ms=None,
        cost_usd_estimated=None,
        parent_run_id=None,
        error=None,
    ):
        # Use the real ContextVar lookup — that's the behaviour under test.
        recorded.append(
            {
                "agent_name": agent_name,
                "lens": lens,
                "pipeline_run_id": current_pipeline_run_id(),
            }
        )
        return "fake-run-id"

    monkeypatch.setattr(run_log, "_get_database", _fake_get_database)
    monkeypatch.setattr(run_log, "log_run", _fake_log_run)

    # Begin a pipeline run on the *parent* thread.
    pid = begin_pipeline_run()
    assert current_pipeline_run_id() == pid

    # Fan out 4 calls via ThreadPoolExecutor. Python's stdlib executor
    # captures the active contextvars.Context when the task is submitted,
    # so each worker should see the same pipeline_run_id.
    def _worker(i: int):
        return run_log.log_run(
            agent_name=f"worker_{i}",
            input_text=f"in_{i}",
            output_text=f"out_{i}",
            lens=f"lens_{i}",
        )

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(_worker, range(4)))

    assert all(r == "fake-run-id" for r in results), "all workers should succeed"
    assert len(recorded) == 4, f"expected 4 recorded calls, got {len(recorded)}"
    pipeline_ids = {r["pipeline_run_id"] for r in recorded}
    assert pipeline_ids == {pid}, (
        f"every worker must see the parent pipeline_run_id; got {pipeline_ids}"
    )
    # Sanity: lens propagation works.
    assert {r["lens"] for r in recorded} == {f"lens_{i}" for i in range(4)}


@pytest.mark.skipif(
    os.environ.get("CURATOR_AGENT_RUN_LOG", "0") != "1"
    or os.environ.get("CURATOR_LIVE_GCP", "0") != "1",
    reason="Live Spanner test — set CURATOR_AGENT_RUN_LOG=1 and CURATOR_LIVE_GCP=1",
)
def test_log_run_live():
    """Round-trip one real row into agent_runs. Opt-in only."""
    from google.cloud import spanner  # type: ignore[import-not-found]

    pid = begin_pipeline_run()
    run_id = log_run(
        agent_name="d4_track2_smoke",
        input_text="live agent_runs writer test",
        output_text="ok",
        lens="smoke",
        confidence=0.9,
        latency_ms=42,
    )
    assert run_id is not None, "live write should return a run_id"

    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "curator-research")
    instance = os.environ.get("SPANNER_INSTANCE", "curator-graph")
    database = os.environ.get("SPANNER_DATABASE", "curator")

    client = spanner.Client(project=project)
    db = client.instance(instance).database(database)
    with db.snapshot() as snap:
        rows = list(
            snap.execute_sql(
                "SELECT run_id, agent_name, lens, pipeline_run_id "
                "FROM agent_runs WHERE run_id = @rid",
                params={"rid": run_id},
                param_types={"rid": spanner.param_types.STRING},
            )
        )
    assert len(rows) == 1, f"expected 1 row for run_id={run_id}, got {len(rows)}"
    got_run_id, got_agent, got_lens, got_pid = rows[0]
    assert got_run_id == run_id
    assert got_agent == "d4_track2_smoke"
    assert got_lens == "smoke"
    assert got_pid == pid
