"""In-memory per-run progress for the live-analysis UI.

The status endpoint shows a static "ingesting" string while a multi-minute
Doc AI parse runs silently. This module gives the deep ingest path a place
to publish fine-grained progress (current stage, page-batch X of Y) without
threading a callback through every function signature: it keys progress on
the same ``pipeline_run_id`` that ``run_log`` already binds into the
ContextVar + cross-thread mirror, so ``parse_pdf`` (and its
ThreadPoolExecutor workers) can call ``bump()`` and the FastAPI status
handler can read it back.

Best-effort and never raises: if no run id is bound (offline / unit tests)
every call is a no-op.
"""

from __future__ import annotations

import threading
import time

from app.observability.run_log import current_pipeline_run_id

_LOCK = threading.Lock()
_PROGRESS: dict[str, dict] = {}


def _rid(run_id: str | None) -> str | None:
    return run_id or current_pipeline_run_id()


def set_stage(
    stage: str, *, total: int = 0, unit: str = "step", run_id: str | None = None
) -> None:
    """Begin a new stage. Resets the done counter and the stage clock."""
    rid = _rid(run_id)
    if not rid:
        return
    with _LOCK:
        p = _PROGRESS.setdefault(rid, {})
        p.update(
            stage=stage,
            total=int(total),
            done=0,
            unit=unit,
            stage_started=time.time(),
        )


def bump(n: int = 1, run_id: str | None = None) -> None:
    """Increment the current stage's done counter (thread-safe)."""
    rid = _rid(run_id)
    if not rid:
        return
    with _LOCK:
        p = _PROGRESS.setdefault(rid, {})
        p["done"] = int(p.get("done", 0)) + n


def set_fields(run_id: str | None = None, **fields) -> None:
    rid = _rid(run_id)
    if not rid:
        return
    with _LOCK:
        _PROGRESS.setdefault(rid, {}).update(fields)


def get(run_id: str) -> dict:
    """Snapshot of a run's progress (empty dict if none)."""
    with _LOCK:
        return dict(_PROGRESS.get(run_id) or {})


def clear(run_id: str) -> None:
    with _LOCK:
        _PROGRESS.pop(run_id, None)


__all__ = ["set_stage", "bump", "set_fields", "get", "clear"]
