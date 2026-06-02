"""Best-effort observability writer for the ``agent_runs`` Spanner table.

Every real-LLM sub-agent invocation that flows through
``app.runners.run_agent`` writes one row here, capturing the agent name,
the lens (when invoked from one of the four-perspective panels), the
prompt hash, truncated input/output text, latency and (optionally) an
error string. The data drives:

  * D7 GEPA / SimplePromptOptimizer feedback — the optimizer reads
    historical agent runs joined with eval scores.
  * D5 inbox UI — surfaces the latest pipeline run per discovered RBI item.
  * Manual triage — Cloud Trace shows latency; ``agent_runs`` shows
    the prompt + output side-by-side.

Activation
----------
Writes are gated on ``CURATOR_AGENT_RUN_LOG=1``. The flag is OFF by
default so that:

  * ``python -m app.chain`` (offline smoke) never touches GCP.
  * ``pytest tests/unit tests/integration`` (without ``CURATOR_LIVE_GCP``)
    never touches GCP.

The Spanner client is constructed lazily on first successful write — until
then this module has zero side effects beyond importing.

Connection
----------
Reads ``GOOGLE_CLOUD_PROJECT`` (default ``curator-research``),
``SPANNER_INSTANCE`` (default ``curator-graph``), and
``SPANNER_DATABASE`` (default ``curator``) from the environment.

Threading
---------
``pipeline_run_id`` propagation uses a ``contextvars.ContextVar`` as
the primary store. ContextVar gets the asyncio / structured-concurrency
semantics right when the same thread reflects multiple nested pipeline
runs. However ``concurrent.futures.ThreadPoolExecutor`` does NOT
automatically copy the parent Context onto worker threads in CPython
3.12, and the four-lens debate panel fans out via that executor — so a
naive ContextVar-only design loses the id at the panel boundary.

To bridge that gap we additionally mirror the active id into a
module-level variable guarded by ``_pipeline_lock``. The reader
(``current_pipeline_run_id``) prefers the ContextVar value (so nested
runs in the same thread work correctly) and falls back to the
module-level mirror when the ContextVar is empty — which is exactly
what happens inside a ThreadPoolExecutor worker. The chain is
sequential between panel invocations, so a single global mirror is
safe at our concurrency level (one pipeline run at a time per process).

Error policy
------------
``log_run`` NEVER raises. A best-effort writer that crashes the chain
on every run defeats the purpose. Failures are caught, the Spanner
client is invalidated (so the next call retries the lazy init), and
the function returns ``None``.
"""

from __future__ import annotations

import contextvars
import hashlib
import logging
import os
import threading
import uuid

LOGGER = logging.getLogger(__name__)

# Env flags
ENV_ENABLE = "CURATOR_AGENT_RUN_LOG"
ENV_PROJECT = "GOOGLE_CLOUD_PROJECT"
ENV_INSTANCE = "SPANNER_INSTANCE"
ENV_DATABASE = "SPANNER_DATABASE"

DEFAULT_PROJECT = "curator-research"
DEFAULT_INSTANCE = "curator-graph"
DEFAULT_DATABASE = "curator"

# Conservative truncation. Spanner STRING(MAX) accepts up to ~10 MB, but
# we don't need to persist the entire raw text of every clause — 32K
# leaves room for verbose lens outputs without bloating the table.
_TEXT_MAX_CHARS = 32_000

# ContextVar so the panel ThreadPoolExecutor workers inherit the
# active pipeline_run_id without us having to plumb it through call
# sites. CPython 3.12's ThreadPoolExecutor does NOT auto-copy Context
# onto workers, so we additionally mirror into a module-level slot
# (see module docstring "Threading").
_pipeline_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "curator_pipeline_run_id", default=None
)
_pipeline_lock = threading.Lock()
_pipeline_run_id_mirror: str | None = None

# Lazy Spanner client cache. Set on first successful write.
_database = None
_client_init_failed = False


def _enabled() -> bool:
    val = os.environ.get(ENV_ENABLE, "0").strip().lower()
    return val in {"1", "true", "yes", "on"}


def _truncate(s: str | None) -> str:
    if not s:
        return ""
    if len(s) <= _TEXT_MAX_CHARS:
        return s
    return s[:_TEXT_MAX_CHARS]


def _get_database():
    """Lazily construct (and cache) the Spanner ``Database`` client.

    Returns ``None`` if construction has previously failed in this
    process — we don't want to spam stack traces on every log call when
    the env is misconfigured.
    """
    global _database, _client_init_failed
    if _database is not None:
        return _database
    if _client_init_failed:
        return None
    try:
        from google.cloud import spanner  # type: ignore[import-not-found]

        project = os.environ.get(ENV_PROJECT, DEFAULT_PROJECT)
        instance_id = os.environ.get(ENV_INSTANCE, DEFAULT_INSTANCE)
        database_id = os.environ.get(ENV_DATABASE, DEFAULT_DATABASE)

        client = spanner.Client(project=project)
        instance = client.instance(instance_id)
        _database = instance.database(database_id)
        return _database
    except Exception as e:  # noqa: BLE001 — best-effort
        LOGGER.warning("agent_runs Spanner client init failed: %s", e)
        _client_init_failed = True
        return None


def begin_pipeline_run() -> str:
    """Open a fresh logical pipeline run.

    Generates a uuid4 hex, binds it to BOTH the current ``contextvars``
    scope (so nested calls in the same thread see it correctly) and a
    module-level mirror (so ThreadPoolExecutor workers, which do not
    inherit the parent Context in CPython 3.12, still resolve the same
    id via ``current_pipeline_run_id``). Always returns a fresh id;
    callers wanting nesting should manage their own context tokens.
    """
    global _pipeline_run_id_mirror
    pid = uuid.uuid4().hex
    _pipeline_run_id.set(pid)
    with _pipeline_lock:
        _pipeline_run_id_mirror = pid
    return pid


def current_pipeline_run_id() -> str | None:
    """Return the active pipeline run id, or ``None`` if no run is open.

    Reads the ContextVar first (correct under nested in-thread
    contexts) and falls back to the cross-thread mirror — that
    fallback is what allows the panel ThreadPoolExecutor workers to
    tag their writes with the parent's pipeline id.
    """
    val = _pipeline_run_id.get()
    if val is not None:
        return val
    with _pipeline_lock:
        return _pipeline_run_id_mirror


def log_run(
    *,
    agent_name: str,
    input_text: str,
    output_text: str,
    lens: str | None = None,
    confidence: float | None = None,
    latency_ms: int | None = None,
    cost_usd_estimated: float | None = None,
    parent_run_id: str | None = None,
    error: str | None = None,
    instruction: str | None = None,
) -> str | None:
    """Write one row into ``agent_runs``. Never raises.

    Args:
      agent_name: short name (e.g. ``"decompose_lens_banker"``).
      input_text: the user-role prompt sent to the agent. Truncated.
      output_text: the agent's raw text response. Truncated.
      lens: optional lens / critic name when the call originated from a
        debate panel; ``None`` for single-shot agents.
      confidence: optional scalar confidence in [0,1].
      latency_ms: optional elapsed wall-clock time of the underlying
        runner call.
      cost_usd_estimated: optional model-cost estimate.
      parent_run_id: optional id of the run that triggered this one
        (e.g. a Reflector re-query).
      error: optional error string if the underlying call failed.
      instruction: optional agent instruction prompt. Hashed alongside
        ``(agent_name, input_text)`` so GEPA can group identical
        prompts correctly — without this, different panel critics
        sharing the same input collide on prompt_hash.

    Returns:
      The generated ``run_id`` (uuid4 hex) on a successful Spanner write;
      ``None`` if the env flag is unset, the Spanner client couldn't be
      constructed, or the write itself errored.
    """
    if not _enabled():
        return None

    database = _get_database()
    if database is None:
        return None

    run_id = uuid.uuid4().hex
    pipeline_run_id = _pipeline_run_id.get()

    input_text_t = _truncate(input_text)
    output_text_t = _truncate(output_text)
    # D5: include agent_name + instruction in the hash so GEPA groups
    # variants correctly (e.g., 4 critic agents with the same user_text
    # used to collide on a user-text-only hash).
    _hash_payload = (
        f"agent={agent_name}\n"
        f"instruction={(instruction or '')[:8192]}\n"
        f"input={input_text_t}"
    )
    prompt_hash = hashlib.sha256(_hash_payload.encode("utf-8")).hexdigest()[:64]

    try:
        from google.cloud import spanner  # type: ignore[import-not-found]

        def _txn(transaction) -> None:
            transaction.insert(
                table="agent_runs",
                columns=(
                    "run_id",
                    "ts",
                    "agent_name",
                    "lens",
                    "prompt_hash",
                    "input_json",
                    "output_json",
                    "confidence",
                    "latency_ms",
                    "cost_usd_estimated",
                    "parent_run_id",
                    "pipeline_run_id",
                    "error",
                ),
                values=[
                    (
                        run_id,
                        spanner.COMMIT_TIMESTAMP,
                        agent_name,
                        lens,
                        prompt_hash,
                        input_text_t,
                        output_text_t,
                        confidence,
                        latency_ms,
                        cost_usd_estimated,
                        parent_run_id,
                        pipeline_run_id,
                        error,
                    )
                ],
            )

        database.run_in_transaction(_txn)
        return run_id
    except Exception as e:  # noqa: BLE001 — best-effort
        LOGGER.warning("agent_runs insert failed (agent=%s): %s", agent_name, e)
        return None


__all__ = [
    "ENV_ENABLE",
    "begin_pipeline_run",
    "current_pipeline_run_id",
    "log_run",
]
