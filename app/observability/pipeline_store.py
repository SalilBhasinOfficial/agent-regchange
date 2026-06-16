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

import base64
import gzip
import json
import logging
import os
from typing import Any

LOGGER = logging.getLogger(__name__)

# Spanner STRING(MAX)/BYTES(MAX) hard cap is ~2.5 MiB per value. Compressed
# payloads (parse cache, run checkpoints) are guarded against it.
_BLOB_LIMIT = 2_500_000

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
    """Persist one completed (or errored) pipeline run. Best-effort, no raise.

    Retries transient Spanner errors a few times — a single transient failure
    (e.g. a credential-refresh blip or "Failed to initialize transaction")
    otherwise loses a completed run permanently, since this is the only durable
    write. The state_json column has a hard 2.5MB limit; if the payload is
    over, the caller is expected to have trimmed it, but we surface that error
    clearly rather than retrying it (a retry won't help an oversized value).
    """
    database = _get_database()
    if database is None:
        return
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

    import time as _time

    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            database.run_in_transaction(_txn)
            return
        except Exception as e:  # noqa: BLE001
            last_exc = e
            msg = str(e)
            # An oversized value won't succeed on retry — fail fast and loud.
            if "exceeds the maximum size" in msg:
                LOGGER.error("save_pipeline_run oversized (%s): %s", pipeline_run_id, e)
                return
            LOGGER.warning(
                "save_pipeline_run attempt %d/4 failed (%s): %s",
                attempt + 1,
                pipeline_run_id,
                e,
            )
            if attempt < 3:
                _time.sleep(1.5 * (attempt + 1))
    LOGGER.error("save_pipeline_run gave up after retries (%s): %s", pipeline_run_id, last_exc)


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


def list_done_runs(limit: int = 50) -> list[dict[str, Any]]:
    """Recent completed runs for the public gallery, newest first.

    Returns one row per *latest* completed run per amendment_id (so the same
    document analysed twice shows once). Best-effort: returns [] when Spanner
    is unavailable.

    Note: there is no per-tenant namespace column yet, so this lists every
    completed run. For multi-tenant production the gallery must filter to a
    public/published namespace — today all rows are curated RBI analyses.
    """
    database = _get_database()
    if database is None:
        return []
    try:
        with database.snapshot() as snap:
            rows = list(
                snap.execute_sql(
                    "SELECT pipeline_run_id, ts, amendment_id, clauses_count, "
                    "total_cost_usd, stats_json FROM pipeline_runs "
                    "WHERE status='done' ORDER BY ts DESC LIMIT @lim",
                    params={"lim": limit},
                    param_types=_int_param_types("lim"),
                )
            )
    except Exception as e:  # noqa: BLE001
        LOGGER.warning("list_done_runs failed: %s", e)
        return []
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        amendment_id = r[2]
        if amendment_id in seen:
            continue
        seen.add(amendment_id)
        out.append(
            {
                "pipeline_run_id": r[0],
                "ts": r[1].isoformat() if r[1] else None,
                "amendment_id": amendment_id,
                "clauses_count": r[3],
                "total_cost_usd": r[4],
                "stats_json": r[5] if len(r) > 5 else None,
            }
        )
    return out


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


# ---------------------------------------------------------------------------
# Doc AI parse cache — key on the PDF's sha256 so a re-run (or the same master
# direction reused across amendments) skips the slow/paid Doc AI re-parse.
# Stores the parsed chunks as gzipped JSON. Best-effort: any failure falls back
# to a live parse.
# ---------------------------------------------------------------------------


def parse_cache_get(pdf_sha256: str) -> list[dict] | None:
    """Return cached parsed-chunk dicts for a PDF sha256, or None on miss."""
    database = _get_database()
    if database is None:
        return None
    try:
        with database.snapshot() as snap:
            rows = list(
                snap.execute_sql(
                    "SELECT chunk_b64 FROM parsed_chunks WHERE pdf_sha256=@h",
                    params={"h": pdf_sha256},
                    param_types=_string_param_types("h"),
                )
            )
        if not rows or rows[0][0] is None:
            return None
        return json.loads(gzip.decompress(base64.b64decode(rows[0][0])).decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        LOGGER.warning("parse_cache_get failed (%s): %s", pdf_sha256[:12], e)
        return None


def parse_cache_put(
    pdf_sha256: str, doc_id: str, page_count: int, chunk_dicts: list[dict]
) -> None:
    """Store parsed-chunk dicts under a PDF sha256. Best-effort, no raise."""
    database = _get_database()
    if database is None:
        return
    try:
        blob = base64.b64encode(
            gzip.compress(json.dumps(chunk_dicts, default=str).encode("utf-8"))
        ).decode("ascii")
        if len(blob) > _BLOB_LIMIT:
            LOGGER.warning(
                "parse_cache_put skipped — gzip %d > limit (%s)", len(blob), pdf_sha256[:12]
            )
            return
        from google.cloud import spanner  # type: ignore[import-not-found]

        def _txn(transaction) -> None:
            transaction.insert_or_update(
                table="parsed_chunks",
                columns=(
                    "pdf_sha256",
                    "doc_id",
                    "n_chunks",
                    "page_count",
                    "chunk_b64",
                    "parsed_at",
                ),
                values=[
                    (
                        pdf_sha256,
                        doc_id,
                        len(chunk_dicts),
                        page_count,
                        blob,
                        spanner.COMMIT_TIMESTAMP,
                    )
                ],
            )

        database.run_in_transaction(_txn)
    except Exception as e:  # noqa: BLE001
        LOGGER.warning("parse_cache_put failed (%s): %s", pdf_sha256[:12], e)


# ---------------------------------------------------------------------------
# Run checkpoints — persist partial chain state keyed on a content hash of the
# inputs so a failed/stuck run can be resumed past already-completed stages.
# Cleared on successful completion (so only failed runs leave a resumable
# checkpoint). state is gzipped to fit the column limit without trimming.
# ---------------------------------------------------------------------------


def load_run_checkpoint(resume_key: str) -> dict | None:
    """Return {stages: list[str], state_json: str, pipeline_run_id} or None."""
    database = _get_database()
    if database is None:
        return None
    try:
        with database.snapshot() as snap:
            rows = list(
                snap.execute_sql(
                    "SELECT stages, state_b64, pipeline_run_id "
                    "FROM run_checkpoints WHERE resume_key=@k",
                    params={"k": resume_key},
                    param_types=_string_param_types("k"),
                )
            )
        if not rows or rows[0][1] is None:
            return None
        stages_csv, state_b64, prid = rows[0]
        return {
            "stages": [s for s in (stages_csv or "").split(",") if s],
            "state_json": gzip.decompress(base64.b64decode(state_b64)).decode("utf-8"),
            "pipeline_run_id": prid,
        }
    except Exception as e:  # noqa: BLE001
        LOGGER.warning("load_run_checkpoint failed (%s): %s", resume_key[:12], e)
        return None


def save_run_checkpoint(
    resume_key: str, stages: list[str], state_json: str, pipeline_run_id: str
) -> None:
    """Persist partial state for a resume_key after a stage. Best-effort."""
    database = _get_database()
    if database is None:
        return
    try:
        blob = base64.b64encode(gzip.compress(state_json.encode("utf-8"))).decode("ascii")
        if len(blob) > _BLOB_LIMIT:
            LOGGER.warning(
                "save_run_checkpoint skipped — gzip %d > limit (%s)",
                len(blob),
                resume_key[:12],
            )
            return
        from google.cloud import spanner  # type: ignore[import-not-found]

        def _txn(transaction) -> None:
            transaction.insert_or_update(
                table="run_checkpoints",
                columns=(
                    "resume_key",
                    "stages",
                    "state_b64",
                    "pipeline_run_id",
                    "updated_at",
                ),
                values=[
                    (
                        resume_key,
                        ",".join(stages),
                        blob,
                        pipeline_run_id,
                        spanner.COMMIT_TIMESTAMP,
                    )
                ],
            )

        database.run_in_transaction(_txn)
    except Exception as e:  # noqa: BLE001
        LOGGER.warning("save_run_checkpoint failed (%s): %s", resume_key[:12], e)


def clear_run_checkpoint(resume_key: str) -> None:
    """Delete a run checkpoint (called on successful completion). Best-effort."""
    database = _get_database()
    if database is None:
        return
    try:

        def _txn(transaction) -> None:
            transaction.execute_update(
                "DELETE FROM run_checkpoints WHERE resume_key=@k",
                params={"k": resume_key},
                param_types=_string_param_types("k"),
            )

        database.run_in_transaction(_txn)
    except Exception as e:  # noqa: BLE001
        LOGGER.warning("clear_run_checkpoint failed (%s): %s", resume_key[:12], e)


__all__ = [
    "save_pipeline_run",
    "load_pipeline_run",
    "latest_done_run",
    "cost_summary",
    "stage_breakdown",
    "parse_cache_get",
    "parse_cache_put",
    "load_run_checkpoint",
    "save_run_checkpoint",
    "clear_run_checkpoint",
]
