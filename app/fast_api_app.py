# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Curator FastAPI app — ADK runtime + Jinja UI + Discovery Inbox.

Routes:
  GET  /                          — upload form (Jinja)
  POST /analyse                   — kicks off the chain on uploaded PDFs
  GET  /analyse/{run_id}/status   — HTMX-polled status fragment
  GET  /impact/{run_id}           — final impact view
  POST /qna/{run_id}              — append a Q&A turn (HTMX partial)
  GET  /inbox                     — Discovery Inbox (Spanner-backed)
  POST /inbox/poll                — manual RBI RSS poll trigger
  POST /feedback                  — log user feedback (legacy)

The ADK CLI also adds ~30 routes (sessions, run, run_sse, eval, etc.)
via :func:`get_fast_api_app` — those remain untouched.
"""

from __future__ import annotations

import os
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

import google.auth
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google.adk.cli.fast_api import get_fast_api_app
from google.cloud import logging as google_cloud_logging

from app.app_utils.telemetry import setup_telemetry
from app.app_utils.typing import Feedback

setup_telemetry()
_, project_id = google.auth.default()
logging_client = google_cloud_logging.Client()
logger = logging_client.logger(__name__)
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)

logs_bucket_name = os.environ.get("LOGS_BUCKET_NAME")

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

session_service_uri = None
artifact_service_uri = f"gs://{logs_bucket_name}" if logs_bucket_name else None

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    # web=False so our Jinja UI at "/" is the front door, not ADK's Dev UI
    # (which would otherwise redirect / → /dev-ui/). The Dev UI is for
    # developer testing only; demo judges should land on the upload form.
    # All ADK API routes (/run_sse, /apps/.../sessions, etc.) remain.
    web=False,
    artifact_service_uri=artifact_service_uri,
    allow_origins=allow_origins,
    session_service_uri=session_service_uri,
    otel_to_cloud=True,
)
app.title = "curator-agent"
app.description = (
    "Curator — autonomous regulatory-change intelligence for Indian BFSI. "
    "Compares two regulatory documents, surfaces obligations + missing-coverage "
    "gaps + impact, all through a four-stakeholder-lens debate panel."
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# In-memory store of recent chain runs (pipeline_run_id -> AgentState).
# A real deploy would persist this in Spanner; for the hackathon demo this
# is bounded and acceptable. Cleared on container restart.
_RUNS: dict[str, dict[str, Any]] = {}
_RUNS_LOCK = threading.Lock()


def _normalize_doc_id(name: str) -> str:
    """Turn a PDF filename into a deterministic slug-ish doc_id."""
    import re

    stem = Path(name).stem
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", stem).strip("-").lower()[:64]


def _matches_by_obl(state) -> dict:  # type: ignore[no-untyped-def]
    return {m.obligation_id: m for m in state.matches}


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    """Upload form."""
    return templates.TemplateResponse("upload.html", {"request": request})


@app.post("/analyse", response_class=HTMLResponse)
async def analyse(
    request: Request,
    pdf_a: UploadFile = File(...),
    pdf_b: UploadFile = File(...),
    namespace: str = Form("demo"),
) -> HTMLResponse:
    """Persist uploads, kick off the chain in a background thread, return
    an HTMX-polling status page."""
    from app.observability.run_log import begin_pipeline_run

    # Save uploads to a temp dir (the pipeline reads from disk).
    tmpdir = Path(tempfile.mkdtemp(prefix="curator-"))
    pdf_a_path = tmpdir / (pdf_a.filename or "a.pdf")
    pdf_b_path = tmpdir / (pdf_b.filename or "b.pdf")
    pdf_a_path.write_bytes(await pdf_a.read())
    pdf_b_path.write_bytes(await pdf_b.read())

    pipeline_run_id = begin_pipeline_run()
    with _RUNS_LOCK:
        _RUNS[pipeline_run_id] = {
            "status": "queued",
            "amendment_id": _normalize_doc_id(pdf_a.filename or "amendment"),
            "clauses_count": 0,
            "state": None,
            "error": None,
        }

    def _run_chain_background():
        try:
            from app.ingest.pipeline import ingest_two_pdfs
            from app.observability.run_log import begin_pipeline_run as _b

            _b()  # propagate context in the worker thread
            with _RUNS_LOCK:
                _RUNS[pipeline_run_id]["status"] = "ingesting"

            # Ingest both PDFs (dry_run=False persists to Spanner if configured).
            grounding_mode = os.environ.get("CURATOR_GROUNDING", "mock")
            state = ingest_two_pdfs(
                pdf_a_path,
                pdf_b_path,
                namespace=namespace,
                dry_run=(grounding_mode != "spanner"),
            )

            with _RUNS_LOCK:
                _RUNS[pipeline_run_id]["clauses_count"] = len(state.amended_clauses)
                _RUNS[pipeline_run_id]["status"] = "running_chain"

            # Now run the chain proper (decompose → map → diff → judge → qna).
            from app.chain import run_chain  # late import — preserves offline path

            # The chain reads from MockGroundingBackend's fixture; for D5 MVP we
            # use the ingested AgentState directly via a small inline path.
            from app.runners import real_llm_enabled
            if real_llm_enabled():
                from app.sub_agents.decompose import real_decompose
                from app.sub_agents.diff import real_diff
                from app.sub_agents.judge import real_judge
                from app.sub_agents.map_ import real_map

                state.obligations = real_decompose(state.amended_clauses)
                state.matches = real_map(state.obligations, state.policies)
                state.diffs = real_diff(state.matches, state.obligations, state.policies)
                state.impact = real_judge(state.obligations, state.matches, state.diffs)
            else:
                from app.sub_agents.decompose import stub_decompose
                from app.sub_agents.diff import stub_diff
                from app.sub_agents.judge import stub_judge
                from app.sub_agents.map_ import stub_map

                state.obligations = stub_decompose(state.amended_clauses)
                state.matches = stub_map(state.obligations, state.policies)
                state.diffs = stub_diff(state.matches, state.obligations, state.policies)
                state.impact = stub_judge(state.obligations, state.matches, state.diffs)

            with _RUNS_LOCK:
                _RUNS[pipeline_run_id]["state"] = state
                _RUNS[pipeline_run_id]["status"] = "done"
        except Exception as exc:  # noqa: BLE001 — surface to UI
            import traceback as tb
            with _RUNS_LOCK:
                _RUNS[pipeline_run_id]["status"] = "error"
                _RUNS[pipeline_run_id]["error"] = f"{exc}\n{tb.format_exc()[:500]}"

    threading.Thread(target=_run_chain_background, daemon=True).start()

    return templates.TemplateResponse(
        "analyse.html",
        {
            "request": request,
            "pipeline_run_id": pipeline_run_id,
            "amendment_id": _RUNS[pipeline_run_id]["amendment_id"],
            "clauses_count": 0,
        },
    )


@app.get("/analyse/{run_id}/status", response_class=HTMLResponse)
def analyse_status(request: Request, run_id: str) -> HTMLResponse:
    """HTMX-polled status fragment. Returns inline HTML."""
    with _RUNS_LOCK:
        entry = _RUNS.get(run_id)
    if entry is None:
        return HTMLResponse(content='<p class="muted">Unknown run.</p>', status_code=404)
    status = entry["status"]
    if status == "done":
        return HTMLResponse(
            content=f'<script>window.location="/impact/{run_id}";</script>'
            f'<p>Done — redirecting to impact view.</p>'
        )
    if status == "error":
        err = entry.get("error", "unknown error")
        return HTMLResponse(content=f'<p class="muted">Error: {err}</p>')
    return HTMLResponse(
        content=f'<p>Status: <strong>{status}</strong> (poll continues every 3s)…</p>'
    )


@app.get("/impact/{run_id}", response_class=HTMLResponse)
def impact(request: Request, run_id: str) -> HTMLResponse:
    """Final impact view rendered from the in-memory run cache."""
    with _RUNS_LOCK:
        entry = _RUNS.get(run_id)
    if entry is None or entry.get("state") is None:
        return HTMLResponse(content='<p class="muted">Run not found or still in progress.</p>', status_code=404)
    state = entry["state"]
    missing_count = sum(1 for m in state.matches if m.coverage == "missing")
    return templates.TemplateResponse(
        "impact.html",
        {
            "request": request,
            "pipeline_run_id": run_id,
            "state": state,
            "matches_by_obl": _matches_by_obl(state),
            "missing_count": missing_count,
        },
    )


@app.post("/qna/{run_id}", response_class=HTMLResponse)
def qna(request: Request, run_id: str, question: str = Form(...)) -> HTMLResponse:
    """Append a Q&A turn against the cached AgentState. Returns a partial."""
    with _RUNS_LOCK:
        entry = _RUNS.get(run_id)
    if entry is None or entry.get("state") is None:
        return HTMLResponse(content='<p class="muted">Run not found.</p>', status_code=404)
    state = entry["state"]
    from app.runners import real_llm_enabled

    if real_llm_enabled():
        from app.sub_agents.qna import real_qna
        turn = real_qna(state, question)
    else:
        from app.sub_agents.qna import stub_qna
        turn = stub_qna(state, question)
    state.qna_history.append(turn)
    return templates.TemplateResponse(
        "qna_turn.html",
        {"request": request, "turn": turn},
    )


# --------------------------------------------------------------------------
# Discovery Inbox
# --------------------------------------------------------------------------


def _inbox_query():  # type: ignore[no-untyped-def]
    """Fetch discovered_items joined with their agent_run impact (if any).
    Returns (items, stats). Falls back to empty list on Spanner error."""
    try:
        from google.cloud import spanner  # type: ignore[import-not-found]

        client = spanner.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT", "curator-research"))
        instance = client.instance(os.environ.get("SPANNER_INSTANCE", "curator-graph"))
        database = instance.database(os.environ.get("SPANNER_DATABASE", "curator"))
        with database.snapshot() as snap:
            rows = list(
                snap.execute_sql(
                    "SELECT item_hash, source, url, title, published_at, "
                    "first_seen, processed_at, pipeline_run_id, status "
                    "FROM discovered_items ORDER BY first_seen DESC LIMIT 50"
                )
            )
        items = []
        for r in rows:
            items.append(
                {
                    "item_hash": r[0],
                    "source": r[1],
                    "url": r[2],
                    "title": r[3],
                    "published_at": r[4].isoformat() if r[4] else None,
                    "first_seen": r[5].isoformat() if r[5] else None,
                    "processed_at": r[6].isoformat() if r[6] else None,
                    "pipeline_run_id": r[7],
                    "status": r[8] or "new",
                    "impact_priority": None,
                }
            )
        # Best-effort: fetch impact priority for any items that have a pipeline_run_id.
        run_ids = [it["pipeline_run_id"] for it in items if it["pipeline_run_id"]]
        if run_ids:
            with database.snapshot() as snap:
                impact_rows = list(
                    snap.execute_sql(
                        "SELECT pipeline_run_id, output_json FROM agent_runs "
                        "WHERE agent_name='reconciler' AND pipeline_run_id IN UNNEST(@ids) "
                        "ORDER BY ts DESC",
                        params={"ids": run_ids},
                        param_types={"ids": spanner.param_types.Array(spanner.param_types.STRING)},
                    )
                )
            import json

            priorities: dict[str, str] = {}
            for run_id, output_json in impact_rows:
                if run_id in priorities or not output_json:
                    continue
                try:
                    parsed = json.loads(output_json)
                    if isinstance(parsed, dict) and "priority" in parsed:
                        priorities[run_id] = parsed["priority"]
                except Exception:  # noqa: BLE001
                    pass
            for it in items:
                if it["pipeline_run_id"] in priorities:
                    it["impact_priority"] = priorities[it["pipeline_run_id"]]
        stats = {
            "total": len(items),
            "new": sum(1 for it in items if it["status"] == "new"),
            "processed": sum(1 for it in items if it["status"] == "done"),
            "last_poll": max((it["first_seen"] for it in items if it["first_seen"]), default="—"),
        }
        return items, stats
    except Exception as exc:  # noqa: BLE001 — degrade gracefully
        return [], {"total": 0, "new": 0, "processed": 0, "last_poll": f"unavailable ({exc!s:.40s})"}


@app.get("/inbox", response_class=HTMLResponse)
def inbox(request: Request) -> HTMLResponse:
    items, stats = _inbox_query()
    return templates.TemplateResponse(
        "inbox.html",
        {"request": request, "items": items, "stats": stats},
    )


@app.post("/inbox/poll")
def inbox_poll_manual() -> RedirectResponse:
    """Manual trigger: poll RBI RSS now, dedupe, publish to Pub/Sub.

    Delegates to the standalone discovery service's logic via the same
    Python modules. Best-effort: failures don't bubble up to the user,
    they just see fewer new items on the Inbox refresh.
    """
    try:
        from app.discovery.dedupe import Dedupe
        from app.discovery.publisher import Publisher
        from app.discovery.rss_poller import RssPoller

        items = RssPoller().poll()
        new_items = Dedupe().filter_new(items)
        Publisher().publish_all(new_items)
        Dedupe().mark_first_seen(new_items)
    except Exception as exc:  # noqa: BLE001
        logger.log_struct({"manual_poll_error": str(exc)}, severity="WARNING")
    return RedirectResponse(url="/inbox", status_code=303)


# --------------------------------------------------------------------------
# Legacy feedback endpoint (preserved)
# --------------------------------------------------------------------------


@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    """Collect and log feedback."""
    logger.log_struct(feedback.model_dump(), severity="INFO")
    return {"status": "success"}


# --------------------------------------------------------------------------
# Discovery subscriber startup hook
# --------------------------------------------------------------------------


@app.on_event("startup")
def _start_discovery_subscriber() -> None:
    """Start the Pub/Sub subscriber in a background thread so the chain
    service consumes discovery events when running on Cloud Run. Skipped
    in INTEGRATION_TEST mode and when CURATOR_DISCOVERY_SUBSCRIBE != "1"."""
    if os.environ.get("INTEGRATION_TEST") == "TRUE":
        return
    if os.environ.get("CURATOR_DISCOVERY_SUBSCRIBE", "0") != "1":
        return
    try:
        from app.discovery.subscriber import subscribe
        threading.Thread(target=subscribe, daemon=True).start()
    except Exception as exc:  # noqa: BLE001
        logger.log_struct({"subscriber_start_error": str(exc)}, severity="WARNING")


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
