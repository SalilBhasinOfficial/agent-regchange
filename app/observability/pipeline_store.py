"""Spanner-backed persistence for completed pipeline runs.

The FastAPI app uses an in-process ``_RUNS`` dict for live polling
status, but that dict evaporates when the Cloud Run container scales
to zero. This module persists the final :class:`AgentState` JSON so
``/impact/<run_id>`` and ``/qna/<run_id>`` work across restarts and
across multiple container instances.

Read-through cache pattern:
  * Live polling reads only from ``_RUNS`` (the in-process dict —
    that's still the source of truth while the chain is mid-flight).
  * On chain completion, write one row to ``pipeline_runs``.
  * ``/impact`` first checks ``_RUNS``; if absent, falls back here.

Error policy mirrors :mod:`app.observability.run_log` — every public
call is best-effort and returns ``None`` on any failure (Spanner
unreachable, schema drift, JSON serialise error). The UI degrades
gracefully to "Run not found" rather than 500-ing.
"""

from __future__ import annotations

import logging
import os
from typing import Any

LOGGER = logging.getLogger(__name__)

ENV_PROJECT = "GOOGLE_CLOUD_PROJECT"
ENV_INSTANCE = "SPANNER_INSTANCE"
ENV_DATABASE = "SPANNER_DATABASE"

DEFAULT_PROJECT = "curator-research"
DEFAULT_INSTANCE = "curator-graph"
DEFAULT_DATABASE = "curator"

_database = None
_client_init_failed = False


def _get_database():
    global _database, _client_init_failed
    if _database is not None:
        return _database
    if _client_init_failed:
        return None
    try:
        from google.cloud import spanner  # type: ignore[import-not-found]

        client = spanner.Client(project=os.environ.get(ENV_PROJECT, DEFAULT_PROJECT))
        instance = client.instance(os.environ.get(ENV_INSTANCE, DEFAULT_INSTANCE))
        _database = instance.database(os.environ.get(ENV_DATABASE, DEFAULT_DATABASE))
        return _database
    except Exception as e:  # noqa: BLE001
        LOGGER.warning("pipeline_store Spanner client init failed: %s", e)
        _client_init_failed = True
        return None


def save_pipeline_run(
    *,
    pipeline_run_id: str,
    amendment_id: str | None,
    status: str,
    clauses_count: int,
    state_json: str | None = None,
    error: str | None = None,
    total_cost_usd: float | None = None,
    stats_json: str | None = None,
) -> None:
    """Persist one completed (or errored) pipeline run. Best-effort, no raise."""
    database = _get_database()
    if database is None:
        return
    try:
        from google.cloud import spanner  # type: ignore[import-not-found]

        def _txn(transaction) -> None:
            transaction.insert_or_update(
                table="pipeline_runs",
                columns=(
                    "pipeline_run_id",
                    "ts",
                    "amendment_id",
                    "status",
                    "clauses_count",
                    "state_json",
                    "error",
                    "total_cost_usd",
                    "stats_json",
                ),
                values=[
                    (
                        pipeline_run_id,
                        spanner.COMMIT_TIMESTAMP,
                        amendment_id,
                        status,
                        clauses_count,
                        state_json,
                        error,
                        total_cost_usd,
                        stats_json,
                    )
                ],
            )

        database.run_in_transaction(_txn)
    except Exception as e:  # noqa: BLE001
        LOGGER.warning("save_pipeline_run failed (%s): %s", pipeline_run_id, e)


def load_pipeline_run(pipeline_run_id: str) -> dict[str, Any] | None:
    """Load a previously persisted run, or None if missing/unavailable."""
    database = _get_database()
    if database is None:
        return None
    try:
        with database.snapshot() as snap:
            rows = list(
                snap.execute_sql(
                    "SELECT pipeline_run_id, ts, amendment_id, status, "
                    "clauses_count, state_json, error, total_cost_usd, stats_json "
                    "FROM pipeline_runs WHERE pipeline_run_id=@pid",
                    params={"pid": pipeline_run_id},
                    param_types=_string_param_types("pid"),
                )
            )
    except Exception as e:  # noqa: BLE001
        LOGGER.warning("load_pipeline_run failed (%s): %s", pipeline_run_id, e)
        return None
    if not rows:
        return None
    r = rows[0]
    return {
        "pipeline_run_id": r[0],
        "ts": r[1].isoformat() if r[1] else None,
        "amendment_id": r[2],
        "status": r[3],
        "clauses_count": r[4],
        "state_json": r[5],
        "error": r[6],
        "total_cost_usd": r[7],
        "stats_json": r[8] if len(r) > 8 else None,
    }


def latest_done_run(amendment_id: str) -> str | None:
    """Most-recent completed pipeline_run_id for an amendment_id, or None."""
    database = _get_database()
    if database is None:
        return None
    try:
        with database.snapshot() as snap:
            rows = list(
                snap.execute_sql(
                    "SELECT pipeline_run_id FROM pipeline_runs "
                    "WHERE amendment_id=@aid AND status='done' "
                    "ORDER BY ts DESC LIMIT 1",
                    params={"aid": amendment_id},
                    param_types=_string_param_types("aid"),
                )
            )
        return rows[0][0] if rows else None
    except Exception as e:  # noqa: BLE001
        LOGGER.warning("latest_done_run failed (%s): %s", amendment_id, e)
        return None


def cost_summary(days: int = 7) -> dict[str, Any]:
    """Aggregate spend by agent + total over the last N days from agent_runs."""
    database = _get_database()
    if database is None:
        return {"available": False, "reason": "spanner unavailable"}
    try:
        with database.snapshot() as snap:
            rows = list(
                snap.execute_sql(
                    "SELECT agent_name, "
                    "       COUNT(*) AS calls, "
                    "       ROUND(SUM(COALESCE(cost_usd_estimated, 0)), 4) AS cost_usd, "
                    "       ROUND(AVG(latency_ms), 0) AS avg_latency_ms "
                    "FROM agent_runs "
                    "WHERE ts > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY) "
                    "GROUP BY agent_name ORDER BY cost_usd DESC",
                    params={"days": days},
                    param_types=_int_param_types("days"),
                )
            )
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": str(e)[:200]}
    per_agent = [
        {"agent": r[0], "calls": r[1], "cost_usd": float(r[2] or 0.0),
         "avg_latency_ms": int(r[3] or 0)}
        for r in rows
    ]
    return {
        "available": True,
        "days": days,
        "total_calls": sum(p["calls"] for p in per_agent),
        "total_cost_usd": round(sum(p["cost_usd"] for p in per_agent), 4),
        "per_agent": per_agent,
    }


# Maps agent_name → human pipeline stage for the per-stage breakdown.
_STAGE_OF = {
    "banker_lens": "1. Decompose (4-lens debate)",
    "compliance_lens": "1. Decompose (4-lens debate)",
    "auditor_lens": "1. Decompose (4-lens debate)",
    "customer_protect_lens": "1. Decompose (4-lens debate)",
    "reconciler": "1. Decompose (reconcile)",
    "map_agent": "2. Map (coverage)",
    "diff_agent": "3. Diff (suggested edits)",
    "judge_impact_critic": "4. Judge (4-critic panel)",
    "judge_icaap_critic": "4. Judge (4-critic panel)",
    "judge_pillar3_critic": "4. Judge (4-critic panel)",
    "judge_ops_risk_critic": "4. Judge (4-critic panel)",
    "qna_agent": "5. Q&A",
}


def stage_breakdown(pipeline_run_id: str) -> dict[str, Any]:
    """Per-stage timing + cost breakdown for one run, from agent_runs.

    Returns a dict with ``available``, ``stages`` (list of
    {stage, calls, total_ms, avg_ms, cost_usd}), ``totals``, and
    ``chain_wall_clock_s`` (span from first to last LLM call). No schema
    change required — reads the latency_ms / cost columns already
    written by run_agent. Best-effort: ``available=False`` on error.
    """
    database = _get_database()
    if database is None:
        return {"available": False, "reason": "spanner unavailable"}
    try:
        # Spanner single-use snapshots can't be reused across execute_sql
        # calls — open one per query.
        with database.snapshot() as snap:
            rows = list(
                snap.execute_sql(
                    "SELECT agent_name, "
                    "       COUNT(*) AS calls, "
                    "       SUM(COALESCE(latency_ms,0)) AS total_ms, "
                    "       SUM(COALESCE(cost_usd_estimated,0)) AS cost_usd "
                    "FROM agent_runs WHERE pipeline_run_id=@pid "
                    "GROUP BY agent_name",
                    params={"pid": pipeline_run_id},
                    param_types=_string_param_types("pid"),
                )
            )
        with database.snapshot() as snap2:
            span = list(
                snap2.execute_sql(
                    "SELECT TIMESTAMP_DIFF(MAX(ts), MIN(ts), SECOND) "
                    "FROM agent_runs WHERE pipeline_run_id=@pid",
                    params={"pid": pipeline_run_id},
                    param_types=_string_param_types("pid"),
                )
            )
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": str(e)[:200]}

    # Roll agent rows up into the 5 named stages.
    agg: dict[str, dict[str, float]] = {}
    for agent_name, calls, total_ms, cost_usd in rows:
        stage = _STAGE_OF.get(agent_name, f"other: {agent_name}")
        s = agg.setdefault(stage, {"calls": 0, "total_ms": 0, "cost_usd": 0.0})
        s["calls"] += int(calls or 0)
        s["total_ms"] += int(total_ms or 0)
        s["cost_usd"] += float(cost_usd or 0.0)

    stages = []
    for stage in sorted(agg):
        s = agg[stage]
        calls = int(s["calls"])
        stages.append({
            "stage": stage,
            "calls": calls,
            "total_ms": int(s["total_ms"]),
            "avg_ms": int(s["total_ms"] / calls) if calls else 0,
            "cost_usd": round(s["cost_usd"], 5),
        })
    total_calls = sum(st["calls"] for st in stages)
    total_ms = sum(st["total_ms"] for st in stages)
    return {
        "available": True,
        "pipeline_run_id": pipeline_run_id,
        "stages": stages,
        "totals": {
            "calls": total_calls,
            "summed_call_ms": total_ms,
            "cost_usd": round(sum(st["cost_usd"] for st in stages), 5),
        },
        "chain_wall_clock_s": int(span[0][0]) if span and span[0][0] is not None else None,
    }


def _string_param_types(name: str) -> dict[str, Any]:
    from google.cloud import spanner  # type: ignore[import-not-found]

    return {name: spanner.param_types.STRING}


def _int_param_types(name: str) -> dict[str, Any]:
    from google.cloud import spanner  # type: ignore[import-not-found]

    return {name: spanner.param_types.INT64}


__all__ = [
    "save_pipeline_run",
    "load_pipeline_run",
    "latest_done_run",
    "cost_summary",
    "stage_breakdown",
]
