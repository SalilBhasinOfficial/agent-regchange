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
AGENT_CARD_PATH = Path(__file__).parent / "agent.json"


def _templatize_agent_card() -> None:
    """Rewrite ``agent.json``'s ``url`` field from ``CURATOR_PUBLIC_URL``.

    ADK reads ``agent.json`` once at startup to build the A2A AgentCard;
    the file in the repo carries a placeholder URL so it doesn't lie
    when redeployed under a different domain. Cloud Run automatically
    exposes its own URL via the standard ``K_SERVICE`` env var dance,
    but the public ingress URL is what the card should advertise.

    Resolution order for the URL written into the card:
      1. ``CURATOR_PUBLIC_URL`` (explicit override).
      2. ``https://${K_SERVICE}-${PROJECT_NUMBER}.${K_LOCATION}.run.app``
         when running under Cloud Run (best-effort heuristic).
      3. Whatever the file already says (no-op).

    Run before ``get_fast_api_app(a2a=True)`` mounts the card route.
    Fail-quiet: any error leaves the file untouched.
    """
    import json

    try:
        if not AGENT_CARD_PATH.exists():
            return
        data = json.loads(AGENT_CARD_PATH.read_text())
        override = os.environ.get("CURATOR_PUBLIC_URL", "").strip()
        if not override:
            k_service = os.environ.get("K_SERVICE", "").strip()
            k_location = os.environ.get("K_REVISION", "")  # presence implies Cloud Run
            project_number = os.environ.get("GOOGLE_CLOUD_PROJECT_NUMBER", "").strip()
            region = os.environ.get("CURATOR_RUN_REGION", "asia-south1").strip()
            if k_service and project_number and k_location:
                override = f"https://{k_service}-{project_number}.{region}.run.app"
        if override and data.get("url") != override:
            data["url"] = override
            AGENT_CARD_PATH.write_text(json.dumps(data, indent=2))
    except Exception:  # noqa: BLE001 — best-effort
        pass


_templatize_agent_card()

session_service_uri = None
artifact_service_uri = f"gs://{logs_bucket_name}" if logs_bucket_name else None

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    # web=False so our Jinja UI at "/" is the front door, not ADK's Dev UI
    # (which would otherwise redirect / → /dev-ui/). The Dev UI is for
    # developer testing only; demo judges should land on the upload form.
    # All ADK API routes (/run_sse, /apps/.../sessions, etc.) remain.
    web=False,
    a2a=True,  # mounts /.well-known/agent.json — Track-3 mandate
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


def _pdf_pages(path: Path) -> int | None:
    """Best-effort page count of a PDF. None if pypdf can't read it."""
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(path)).pages)
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    """Upload form."""
    return templates.TemplateResponse("upload.html", {"request": request})


def launch_chain_run(
    pdf_a_path: Path,
    pdf_b_path: Path,
    *,
    namespace: str = "demo",
    amendment_id: str | None = None,
) -> str:
    """Kick off the full chain on a PDF pair in a background thread.

    Shared by the upload route (``/analyse``) and the curated demos
    (``/demos/{id}/run``). Returns the ``pipeline_run_id`` immediately;
    the caller polls ``/analyse/{id}/status``.
    """
    from app.observability.run_log import begin_pipeline_run

    pages_a = _pdf_pages(pdf_a_path)
    pages_b = _pdf_pages(pdf_b_path)
    amendment_id = amendment_id or _normalize_doc_id(pdf_a_path.name)

    import time as _time

    pipeline_run_id = begin_pipeline_run()
    with _RUNS_LOCK:
        _RUNS[pipeline_run_id] = {
            "status": "queued",
            "amendment_id": amendment_id,
            "clauses_count": 0,
            "state": None,
            "error": None,
            "pages_a": pages_a,
            "pages_b": pages_b,
            "started_at": _time.time(),
        }

    def _run_chain_background():
        import time as _time

        _t0 = _time.monotonic()
        _t_ingest = None
        try:
            from app.ingest.pipeline import ingest_two_pdfs
            from app.observability.run_log import bind_pipeline_run

            # Re-bind the parent's pipeline_run_id into THIS thread's
            # ContextVar + the cross-thread mirror, so every agent_runs
            # row written by the chain (including from ThreadPoolExecutor
            # workers in map/diff/lens panels) is tagged with the id the
            # user/UI sees (B2 fix, 2026-06-05).
            bind_pipeline_run(pipeline_run_id)
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

            _t_ingest = _time.monotonic()
            # Full document is ingested + persisted to Spanner above. In
            # fast-mode the debate panel processes a bounded sample of the
            # amended clauses so an interactive/cached demo stays snappy;
            # "re-run live" (CURATOR_FAST_MODE unset) decomposes them all.
            _clauses_total = len(state.amended_clauses)
            # Pre-diff clause filter: drop clauses byte-identical to the prior
            # document before the per-clause four-lens fan-out (~4 LLM calls
            # each). Exact-match only — any numeric change survives. Runs ahead
            # of the fast-mode cap. Disable with CURATOR_PREDIFF_FILTER_CLAUSES=0.
            if os.environ.get("CURATOR_PREDIFF_FILTER_CLAUSES", "1") != "0":
                from app.ingest.prediff import filter_unchanged_clauses

                _kept, _dropped = filter_unchanged_clauses(
                    state.amended_clauses, state.comparison_text
                )
                if _dropped:
                    state.amended_clauses = _kept
            _fast_clauses = os.environ.get("CURATOR_FAST_MODE", "0").strip().lower() in {
                "1", "true", "yes", "on"
            }
            _clause_cap = int(os.environ.get("CURATOR_FAST_MAX_CLAUSES", "10"))
            if _fast_clauses and len(state.amended_clauses) > _clause_cap:
                state.amended_clauses = state.amended_clauses[:_clause_cap]
            with _RUNS_LOCK:
                _RUNS[pipeline_run_id]["clauses_count"] = len(state.amended_clauses)
                _RUNS[pipeline_run_id]["clauses_total"] = _clauses_total
                _RUNS[pipeline_run_id]["status"] = "running_chain"
            try:
                from app.observability import progress as _prog

                _prog.set_stage(
                    "Four-lens debate panel",
                    total=len(state.amended_clauses),
                    unit="clause",
                )
            except Exception:  # noqa: BLE001
                pass

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
                from app.sub_agents.param_diff import real_param_diff

                # Parameter-diff: the quantitative old→new comparison between
                # the two frameworks (Doc A new vs Doc B prior). This is the
                # core change-analysis output — runs even in fast-mode since
                # it is a single large-context call, not a per-clause fan-out.
                state.param_changes = real_param_diff(
                    state.amended_clauses,
                    new_title=state.amendment.title,
                    new_text=state.amendment.raw_text,
                    comparison_title=state.comparison_title,
                    comparison_text=state.comparison_text,
                )
                state.obligations = real_decompose(state.amended_clauses)
                # CURATOR_FAST_MODE caps obligation fan-out before the
                # map/diff/judge tail so an interactive demo finishes
                # quickly under free-tier Vertex quota. Full panel remains
                # the default when the flag is unset.
                _fast = os.environ.get("CURATOR_FAST_MODE", "0").strip().lower() in {
                    "1", "true", "yes", "on"
                }
                _cap = int(os.environ.get("CURATOR_FAST_MAX_OBLIGATIONS", "5"))
                if _fast and len(state.obligations) > _cap:
                    state.obligations = state.obligations[:_cap]
                state.matches = real_map(state.obligations, state.policies)
                state.diffs = real_diff(state.matches, state.obligations, state.policies)
                state.impact = real_judge(
                    state.obligations, state.matches, state.diffs, state.param_changes
                )
                # Compliance + internal-audit control gate before publishing.
                try:
                    from app.sub_agents.audit import real_audit

                    with _RUNS_LOCK:
                        _RUNS[pipeline_run_id]["status"] = "auditing"
                    try:
                        from app.observability import progress as _prog

                        _prog.set_stage("Compliance + internal-audit review", total=1, unit="review")
                    except Exception:  # noqa: BLE001
                        pass
                    state.audit = real_audit(state)
                    try:
                        _prog.bump()
                    except Exception:  # noqa: BLE001
                        pass
                except Exception:  # noqa: BLE001 — audit is a gate, never fail the run
                    import logging as _logging

                    _logging.getLogger(__name__).warning("audit stage failed; continuing")
            else:
                from app.sub_agents.audit import stub_audit
                from app.sub_agents.decompose import stub_decompose
                from app.sub_agents.diff import stub_diff
                from app.sub_agents.judge import stub_judge
                from app.sub_agents.map_ import stub_map

                state.obligations = stub_decompose(state.amended_clauses)
                state.matches = stub_map(state.obligations, state.policies)
                state.diffs = stub_diff(state.matches, state.obligations, state.policies)
                state.impact = stub_judge(state.obligations, state.matches, state.diffs)
                state.audit = stub_audit(state)

            _t_done = _time.monotonic()
            with _RUNS_LOCK:
                _RUNS[pipeline_run_id]["state"] = state
                _RUNS[pipeline_run_id]["status"] = "done"
            # Performance stats for the /stats endpoint + impact panel.
            import json as _json
            from app.llm import curator_model_name
            stats = {
                "pages_a": pages_a,
                "pages_b": pages_b,
                "clauses": len(state.amended_clauses),
                "clauses_total": _RUNS[pipeline_run_id].get("clauses_total", len(state.amended_clauses)),
                "obligations": len(state.obligations),
                "param_changes": len(state.param_changes),
                "matches": len(state.matches),
                "diffs": len(state.diffs),
                "audit_verdict": state.audit.verdict if state.audit else None,
                "audit_findings": len(state.audit.findings) if state.audit else 0,
                "ingest_seconds": round((_t_ingest - _t0), 1) if _t_ingest else None,
                "chain_seconds": round((_t_done - _t_ingest), 1) if _t_ingest else None,
                "total_seconds": round((_t_done - _t0), 1),
                "model": curator_model_name(),
            }
            with _RUNS_LOCK:
                _RUNS[pipeline_run_id]["stats"] = stats
            # Persist to Spanner so /impact/<id> survives container
            # scale-to-zero (audit bonus bug fix, 2026-06-05).
            try:
                from app.observability.pipeline_store import save_pipeline_run

                # The analysis (param_changes, obligations, clauses, impact)
                # is ALWAYS persisted in full — it is never trimmed. Only the
                # raw prior-framework input text (Doc B) is capped, and only
                # as a backstop against Spanner's ~2.5MB STRING(MAX) limit;
                # 800K keeps near-complete context for Q&A reload while
                # leaving headroom for the full analysis payload.
                _persist = state.model_copy(
                    update={
                        "comparison_text": (state.comparison_text or "")[:800000] or None
                    }
                )
                save_pipeline_run(
                    pipeline_run_id=pipeline_run_id,
                    amendment_id=_RUNS[pipeline_run_id]["amendment_id"],
                    status="done",
                    clauses_count=_RUNS[pipeline_run_id]["clauses_count"],
                    state_json=_persist.model_dump_json(),
                    stats_json=_json.dumps(stats),
                )
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001 — surface to UI
            import traceback as tb
            with _RUNS_LOCK:
                _RUNS[pipeline_run_id]["status"] = "error"
                _RUNS[pipeline_run_id]["error"] = f"{exc}\n{tb.format_exc()[:500]}"
            try:
                from app.observability.pipeline_store import save_pipeline_run

                save_pipeline_run(
                    pipeline_run_id=pipeline_run_id,
                    amendment_id=_RUNS[pipeline_run_id]["amendment_id"],
                    status="error",
                    clauses_count=_RUNS[pipeline_run_id].get("clauses_count", 0),
                    error=f"{exc}\n{tb.format_exc()[:500]}",
                )
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=_run_chain_background, daemon=True).start()
    return pipeline_run_id


@app.post("/analyse", response_class=HTMLResponse)
async def analyse(
    request: Request,
    pdf_a: UploadFile = File(...),
    pdf_b: UploadFile = File(...),
    namespace: str = Form("demo"),
) -> HTMLResponse:
    """Persist uploads, kick off the chain, return an HTMX-polling page."""
    tmpdir = Path(tempfile.mkdtemp(prefix="curator-"))
    pdf_a_path = tmpdir / (pdf_a.filename or "a.pdf")
    pdf_b_path = tmpdir / (pdf_b.filename or "b.pdf")
    pdf_a_path.write_bytes(await pdf_a.read())
    pdf_b_path.write_bytes(await pdf_b.read())

    pipeline_run_id = launch_chain_run(
        pdf_a_path,
        pdf_b_path,
        namespace=namespace,
        amendment_id=_normalize_doc_id(pdf_a.filename or "amendment"),
    )
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
        try:
            from app.observability import progress as _prog

            _prog.clear(run_id)
        except Exception:  # noqa: BLE001
            pass
        return HTMLResponse(
            content=f'<script>window.location="/impact/{run_id}";</script>'
            f'<p>Done — redirecting to impact view.</p>'
        )
    if status == "error":
        try:
            from app.observability import progress as _prog

            _prog.clear(run_id)
        except Exception:  # noqa: BLE001
            pass
        err = entry.get("error", "unknown error")
        return HTMLResponse(content=f'<p class="muted">Error: {err}</p>')

    import time as _time

    # ---- Live progress: stage, page count, parts done/total, ETA ----
    try:
        from app.observability import progress as _prog

        prog = _prog.get(run_id)
    except Exception:  # noqa: BLE001
        prog = {}

    pages_a = entry.get("pages_a") or 0
    pages_b = entry.get("pages_b") or 0
    pages_total = pages_a + pages_b
    started_at = entry.get("started_at")
    elapsed = int(_time.time() - started_at) if started_at else 0

    stage = prog.get("stage") or {
        "queued": "Queued",
        "ingesting": "Ingesting documents",
        "running_chain": "Four-lens debate panel",
    }.get(status, status)
    done = int(prog.get("done") or 0)
    total = int(prog.get("total") or 0)
    unit = prog.get("unit") or "step"
    stage_started = prog.get("stage_started")

    # Measured-rate ETA for the current stage: honest because it uses the
    # observed throughput so far, not a hard-coded guess. Needs >=1 unit done.
    eta_seconds = None
    if total and done and stage_started:
        stage_elapsed = max(0.001, _time.time() - stage_started)
        rate = stage_elapsed / done  # seconds per unit
        eta_seconds = int(rate * (total - done))

    def _fmt(s: int) -> str:
        m, sec = divmod(max(0, s), 60)
        return f"{m}m {sec:02d}s" if m else f"{sec}s"

    # Build the line(s).
    parts: list[str] = [f'Stage: <strong>{stage}</strong>']
    if total:
        parts.append(f"{done}/{total} {unit}{'s' if total != 1 else ''}")
    if pages_total:
        parts.append(f"{pages_total} pages ({pages_a}+{pages_b})")
    parts.append(f"elapsed {_fmt(elapsed)}")
    line1 = " · ".join(parts)

    eta_attr = ""
    eta_line = ""
    if eta_seconds is not None:
        eta_epoch = _time.time() + eta_seconds
        eta_attr = f' data-eta-epoch="{eta_epoch:.0f}"'
        eta_line = (
            f'<p class="muted">~ <span id="eta-countdown">{_fmt(eta_seconds)}</span> '
            f'remaining (estimated from current speed)</p>'
        )
    else:
        eta_line = '<p class="muted">Estimating time remaining…</p>'

    return HTMLResponse(
        content=(
            f'<div{eta_attr}>'
            f"<p>{line1}</p>"
            f"{eta_line}"
            f'<p class="muted">Polling every 3s…</p>'
            f"</div>"
        )
    )


@app.get("/analyse/{run_id}", response_class=HTMLResponse)
def analyse_page(request: Request, run_id: str) -> HTMLResponse:
    """The HTMX-polling status page for a run (the POST /analyse target and
    the /demos re-run redirect target). If the run already finished, send
    the viewer straight to the impact view."""
    with _RUNS_LOCK:
        entry = _RUNS.get(run_id)
    amendment_id = entry.get("amendment_id") if entry else None
    if entry and entry.get("status") == "done":
        return RedirectResponse(url=f"/impact/{run_id}", status_code=303)
    if amendment_id is None:
        # Cross-instance: the run may live on another container / be cached.
        try:
            from app.observability.pipeline_store import load_pipeline_run

            row = load_pipeline_run(run_id)
            if row:
                if row.get("status") == "done":
                    return RedirectResponse(url=f"/impact/{run_id}", status_code=303)
                amendment_id = row.get("amendment_id")
        except Exception:  # noqa: BLE001
            pass
    return templates.TemplateResponse(
        "analyse.html",
        {
            "request": request,
            "pipeline_run_id": run_id,
            "amendment_id": amendment_id or run_id,
            "clauses_count": 0,
        },
    )


def _load_state(run_id: str):
    """Look up an AgentState by pipeline_run_id.

    Two-tier read: in-process ``_RUNS`` cache (live polling) first; if
    the container restarted since the run completed, fall back to the
    Spanner-persisted snapshot. Either way callers always see the same
    AgentState shape they had at chain completion.
    """
    from app.models import AgentState

    with _RUNS_LOCK:
        entry = _RUNS.get(run_id)
    if entry is not None and entry.get("state") is not None:
        return entry["state"]

    try:
        from app.observability.pipeline_store import load_pipeline_run

        row = load_pipeline_run(run_id)
        if row and row.get("state_json"):
            return AgentState.model_validate_json(row["state_json"])
    except Exception:  # noqa: BLE001
        pass
    return None


def _run_stats(run_id: str) -> dict | None:
    """Fetch the performance stats blob (pages, per-stage timing) for a run."""
    import json as _json

    with _RUNS_LOCK:
        entry = _RUNS.get(run_id)
    run_stats = entry.get("stats") if entry else None
    if run_stats is None:
        try:
            from app.observability.pipeline_store import load_pipeline_run

            row = load_pipeline_run(run_id)
            if row and row.get("stats_json"):
                run_stats = _json.loads(row["stats_json"])
        except Exception:  # noqa: BLE001
            run_stats = None
    if run_stats is None:
        return None
    try:
        from app.observability.pipeline_store import stage_breakdown

        run_stats = dict(run_stats)
        run_stats["breakdown"] = stage_breakdown(run_id)
    except Exception:  # noqa: BLE001
        pass
    return run_stats


@app.get("/impact/{run_id}", response_class=HTMLResponse)
def impact(request: Request, run_id: str) -> HTMLResponse:
    """Final impact view. Reads in-memory cache, falls back to Spanner."""
    state = _load_state(run_id)
    if state is None:
        return HTMLResponse(content='<p class="muted">Run not found or still in progress.</p>', status_code=404)
    missing_count = sum(1 for m in state.matches if m.coverage == "missing")
    return templates.TemplateResponse(
        "impact.html",
        {
            "request": request,
            "pipeline_run_id": run_id,
            "state": state,
            "matches_by_obl": _matches_by_obl(state),
            "missing_count": missing_count,
            "run_stats": _run_stats(run_id),
        },
    )


@app.post("/qna/{run_id}", response_class=HTMLResponse)
def qna(request: Request, run_id: str, question: str = Form(...)) -> HTMLResponse:
    """Append a Q&A turn against the cached AgentState. Returns a partial."""
    state = _load_state(run_id)
    if state is None:
        return HTMLResponse(content='<p class="muted">Run not found.</p>', status_code=404)
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


@app.get("/gallery", response_class=HTMLResponse)
def gallery(request: Request) -> HTMLResponse:
    """Public gallery of completed analyses — browsable results, no re-run.

    Lists completed pipeline runs (newest first, one per amendment) so
    evaluators can open finished impact assessments instantly without
    triggering a live, quota-consuming run. Each card parses ``stats_json``
    for headline counts (obligations, parameter changes).
    """
    import json as _json

    runs: list[dict] = []
    try:
        from app.observability.pipeline_store import list_done_runs

        for row in list_done_runs(limit=50):
            stats = {}
            if row.get("stats_json"):
                try:
                    stats = _json.loads(row["stats_json"])
                except Exception:  # noqa: BLE001
                    stats = {}
            # Gallery shows real change-analyses only: a run must have a
            # quantitative parameter diff (param_changes > 0). This excludes
            # degenerate single-document triages (no comparison framework, no
            # policy corpus) that otherwise render as "N obligations / N missing
            # / N edits" — mathematically consistent but not a meaningful result.
            if not (stats.get("param_changes") or 0) > 0:
                continue
            ts = row.get("ts") or ""
            runs.append(
                {
                    "pipeline_run_id": row["pipeline_run_id"],
                    "amendment_id": row.get("amendment_id") or "(untitled)",
                    "date": ts[:10] if ts else "",
                    "clauses_count": row.get("clauses_count") or 0,
                    "obligations": stats.get("obligations"),
                    "param_changes": stats.get("param_changes"),
                    "cost_usd": row.get("total_cost_usd"),
                }
            )
    except Exception:  # noqa: BLE001 — gallery is best-effort
        runs = []
    return templates.TemplateResponse(
        "gallery.html",
        {"request": request, "runs": runs},
    )


@app.post("/inbox/poll")
def inbox_poll_manual() -> RedirectResponse:
    """Manual trigger: poll every configured regulator source now.

    Mirrors the standalone discovery service's ``/poll`` logic — iterates
    :func:`app.discovery.sources.active_sources`, so any source enabled
    via ``CURATOR_RSS_FEEDS`` (RBI, SEBI, IRDAI, EU EBA, US SEC, custom)
    is included. Best-effort; failures don't bubble up to the user.
    """
    try:
        from app.discovery.dedupe import Dedupe
        from app.discovery.publisher import Publisher
        from app.discovery.rss_poller import RssPoller
        from app.discovery.sources import active_sources

        dedupe = Dedupe()
        publisher = Publisher()
        for src in active_sources():
            try:
                items = RssPoller(source=src.id).poll(src.feed_url)
                new_items = dedupe.filter_new(items)
                publisher.publish_all(new_items)
                dedupe.mark_first_seen(new_items)
            except Exception as inner:  # noqa: BLE001 — per-source airlock
                logger.log_struct(
                    {"manual_poll_source_error": str(inner), "source": src.id},
                    severity="WARNING",
                )
    except Exception as exc:  # noqa: BLE001
        logger.log_struct({"manual_poll_error": str(exc)}, severity="WARNING")
    return RedirectResponse(url="/inbox", status_code=303)


@app.post("/inbox/{item_hash}/analyse")
def inbox_analyse_item(item_hash: str) -> RedirectResponse:
    """Triage a discovered regulator item through the chain.

    The Inbox surfaces regulator notifications (typically HTML, not PDF),
    so we don't run the Doc AI ingest path. Instead we construct a
    synthetic :class:`~app.models.AgentState` with one ``AmendedClause``
    carrying the notification's title + summary as ``new_text`` and run
    the chain proper (decompose → map → diff → judge) against the
    bank's policy corpus. The result is a fast "triage card" — useful
    for routing the item to the right compliance pod — not a deep
    clause-by-clause analysis (operators upload the corresponding PDF
    through ``/`` for that).
    """
    from app.discovery.dedupe import Dedupe
    from app.models import AgentState, AmendedClause, AmendmentInput
    from app.observability.run_log import begin_pipeline_run, bind_pipeline_run

    item = Dedupe().get_item(item_hash)
    if item is None:
        return RedirectResponse(url="/inbox", status_code=303)

    pipeline_run_id = begin_pipeline_run()
    Dedupe().mark_processing(item_hash, pipeline_run_id)

    amendment_id = f"discovery-{item_hash[:12]}"
    summary_text = item.get("title") or "(no title)"
    raw_text = (
        f"Regulator notification from {item.get('source','?')}\n"
        f"Title: {item.get('title','')}\n"
        f"URL: {item.get('url','')}\n"
        f"Summary: {summary_text}"
    )
    synth_clause = AmendedClause(
        clause_id=f"{amendment_id}#1",
        md_id=item.get("source", "discovery"),
        heading=item.get("title") or None,
        new_text=summary_text,
        change_type="insert",
    )
    initial_state = AgentState(
        amendment=AmendmentInput(
            amendment_id=amendment_id,
            master_direction_id=item.get("source", "discovery"),
            title=item.get("title") or amendment_id,
            notification_url=item.get("url"),
            raw_text=raw_text,
        ),
        amended_clauses=[synth_clause],
    )

    with _RUNS_LOCK:
        _RUNS[pipeline_run_id] = {
            "status": "queued",
            "amendment_id": amendment_id,
            "clauses_count": 1,
            "state": None,
            "error": None,
        }

    def _run_triage():
        try:
            bind_pipeline_run(pipeline_run_id)
            with _RUNS_LOCK:
                _RUNS[pipeline_run_id]["status"] = "running_chain"
            from app.chain import run_chain

            state = run_chain(initial_state=initial_state)
            with _RUNS_LOCK:
                _RUNS[pipeline_run_id]["state"] = state
                _RUNS[pipeline_run_id]["status"] = "done"
            try:
                Dedupe().mark_done(item_hash, pipeline_run_id)
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001
            import traceback as tb
            with _RUNS_LOCK:
                _RUNS[pipeline_run_id]["status"] = "error"
                _RUNS[pipeline_run_id]["error"] = f"{exc}\n{tb.format_exc()[:500]}"
            try:
                Dedupe().mark_error(item_hash, pipeline_run_id, str(exc)[:200])
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=_run_triage, daemon=True).start()
    return RedirectResponse(url=f"/analyse/{pipeline_run_id}", status_code=303)


# --------------------------------------------------------------------------
# Legacy feedback endpoint (preserved)
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Curated demos — capital-adequacy domain. Each runs on a real RBI doc pair
# (the 412-page prudential-norms Master Direction is ingested via a
# pre-parsed sidecar, $0 / sub-second; the live "re-run" forces a fresh
# parse). Results are cached in Spanner pipeline_runs for instant viewing.
# --------------------------------------------------------------------------
_FIXT = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "source_pdfs"
DEMOS = [
    {
        "id": "demo-capad",
        "title": "Capital Adequacy — Third Amendment vs Master Direction",
        "blurb": "The RBI Third Amendment (2026) to the Prudential Norms on "
                 "Capital Adequacy, read against the full 412-page consolidated "
                 "Master Direction. Surfaces what banks must change.",
        "doc_a": "03_third_amendment_2026-03-10_RBI-aaafe4b91697.pdf",
        "doc_b": "04_master_direction_AFTER_2026-03-10_RBI-0d6a477d11ba.pdf",
        "doc_a_label": "Third Amendment, 2026 (3 pp)",
        "doc_b_label": "Capital Adequacy Master Direction (412 pp)",
    },
    {
        "id": "demo-creditrisk",
        "title": "Credit-Risk Standardised Approach — 2026 vs Basel III (prior)",
        "blurb": "The 2026 Direction on capital charge for credit risk "
                 "(Standardised Approach) diffed against the prior Master "
                 "Circular – Basel III Capital Regulations. Surfaces the actual "
                 "risk-weight movements (corporate, equity, consumer credit / "
                 "LTV bands) and their Pillar-1 CRAR direction.",
        "doc_a": "05_credit_risk_standardised_2026-04-27_RBI-087798ec1547.pdf",
        "doc_b": "06_basel_iii_master_circular_2025-04-01_RBI-28cfc2fb93e7.pdf",
        "doc_a_label": "Credit-Risk SA, 2026 (new)",
        "doc_b_label": "Basel III Master Circular, 2025 (prior)",
    },
]


@app.get("/demos", response_class=HTMLResponse)
def demos(request: Request) -> HTMLResponse:
    """Curated capital-adequacy demos: cached results + a live re-run option."""
    from app.observability.pipeline_store import latest_done_run

    cards = []
    for d in DEMOS:
        cached = latest_done_run(d["id"])
        cards.append({**d, "cached_run_id": cached})
    return templates.TemplateResponse(
        "demos.html", {"request": request, "demos": cards}
    )


@app.post("/demos/{demo_id}/run")
def demos_run(demo_id: str) -> RedirectResponse:
    """Run a curated demo live (forces a fresh chain on the fixture pair)."""
    demo = next((d for d in DEMOS if d["id"] == demo_id), None)
    if demo is None:
        return RedirectResponse(url="/demos", status_code=303)
    pdf_a = _FIXT / demo["doc_a"]
    pdf_b = _FIXT / demo["doc_b"]
    if not pdf_a.exists() or not pdf_b.exists():
        return RedirectResponse(url="/demos", status_code=303)
    run_id = launch_chain_run(
        pdf_a, pdf_b, namespace="capital-adequacy", amendment_id=demo_id
    )
    return RedirectResponse(url=f"/analyse/{run_id}", status_code=303)


@app.get("/stats/{run_id}")
def stats(run_id: str) -> dict[str, Any]:
    """Performance breakdown for one run: doc pages, per-stage LLM timing
    and cost, chain wall-clock. Reads in-memory stats + agent_runs.

    Designed for evaluators: hit this on any run_id (including one you
    just kicked off) to see exactly where the time and money went.
    """
    import json as _json

    from app.observability.pipeline_store import load_pipeline_run, stage_breakdown

    out: dict[str, Any] = {"run_id": run_id}
    # Run-level stats (pages, ingest/chain seconds, model) — memory first,
    # then the persisted Spanner snapshot.
    with _RUNS_LOCK:
        entry = _RUNS.get(run_id)
    if entry and entry.get("stats"):
        out["run"] = entry["stats"]
    else:
        row = load_pipeline_run(run_id)
        if row and row.get("stats_json"):
            try:
                out["run"] = _json.loads(row["stats_json"])
            except Exception:  # noqa: BLE001
                pass
    # Per-stage LLM timing + cost from agent_runs.
    out["breakdown"] = stage_breakdown(run_id)
    return out


@app.get("/cost")
def cost(days: int = 7) -> dict[str, Any]:
    """Curator-side spend rollup for the last N days, from agent_runs.

    Sums ``cost_usd_estimated`` per agent and overall. Useful for
    catching surprise burns before they show up on the billing
    dashboard. Best-effort: returns ``available=False`` if Spanner
    isn't reachable.

    Note: this covers Vertex AI Gemini calls only — it does NOT include
    Spanner instance idle, Cloud Run runtime, Doc AI parses, or
    Cloud Build minutes. Cross-reference the GCP billing console for
    those line items.
    """
    from app.observability.pipeline_store import cost_summary

    return cost_summary(days=days)


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
