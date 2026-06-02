"""Shared ADK runner adapter for the Curator sub-agents.

Each sub-agent (decompose/map/diff/judge/qna) needs the same plumbing:
spin up an ``InMemoryRunner``, send a single user message, collect the
agent's structured response, validate it against a pydantic schema. This
module wraps that flow in one function so the sub-agents themselves stay
tiny — they only differ in their instruction and output schema.

Stage-1 offline path (``stub_*`` functions in each sub-agent file)
remains untouched. The real path is opt-in via ``CURATOR_REAL_LLM=1``;
when unset, every ``run_agent_*`` call raises and the caller falls back
to the stub. ``app/chain.py`` does the routing.

Threading model: ADK's runner is async-native. We expose a synchronous
``run_agent`` so callers (`chain.py`, `tests/`) don't have to spread
``async`` through the codebase. Internally we open a fresh event loop
per call — fine for our cadence (5 calls per amendment).
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from typing import Any, TypeVar

from pydantic import TypeAdapter, ValidationError

T = TypeVar("T")

ENV_FLAG = "CURATOR_REAL_LLM"


def real_llm_enabled() -> bool:
    """True when CURATOR_REAL_LLM is set to a truthy value."""
    val = os.environ.get(ENV_FLAG, "0").strip().lower()
    return val in {"1", "true", "yes", "on"}


class RunnerError(RuntimeError):
    """Raised when the ADK runner returns no usable content or fails to validate."""


def _extract_text(events) -> str:
    """Walk the async event stream and return the last non-empty text part."""
    last_text = None
    for ev in events:
        content = getattr(ev, "content", None)
        if not content:
            continue
        parts = getattr(content, "parts", None) or []
        for p in parts:
            text = getattr(p, "text", None)
            if text:
                last_text = text
    if last_text is None:
        raise RunnerError("ADK runner returned no text content")
    return last_text


def _coerce(text: str, output_schema: Any) -> Any:
    """Best-effort coercion of model output into ``output_schema``.

    ADK with ``output_schema=...`` is supposed to return JSON matching the
    schema, but we still defend against (a) a stray code-fence wrapper,
    (b) leading/trailing prose. If validation fails, raise — the caller
    decides whether to retry or fall back to stub.
    """
    payload = text.strip()
    # strip markdown code fences if Gemini sneaks them in
    if payload.startswith("```"):
        # remove opening fence (optionally with language tag) and closing fence
        first_nl = payload.find("\n")
        if first_nl != -1:
            payload = payload[first_nl + 1 :]
        if payload.endswith("```"):
            payload = payload[: -len("```")]
        payload = payload.strip()
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as e:
        raise RunnerError(f"agent output is not valid JSON: {e}; got: {payload[:200]}") from e
    try:
        return TypeAdapter(output_schema).validate_python(parsed)
    except ValidationError as e:
        raise RunnerError(f"agent output did not match schema {output_schema}: {e}") from e


async def _run_once_async(agent, user_text: str) -> str:
    """One async invocation against an InMemoryRunner. Caller-owned event loop."""
    # Late import: keeps `app.runners` importable without GCP creds.
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    app_name = f"curator-{agent.name}"
    runner = InMemoryRunner(agent=agent, app_name=app_name)
    session = await runner.session_service.create_session(
        app_name=app_name, user_id="curator"
    )
    content = types.Content(role="user", parts=[types.Part(text=user_text)])
    events = []
    async for ev in runner.run_async(
        user_id="curator", session_id=session.id, new_message=content
    ):
        events.append(ev)
    return _extract_text(events)


def _run_in_fresh_loop(coro):
    """Run an async coroutine to completion without contaminating the caller's loop.

    Spawns a dedicated thread so callers nested inside an existing event
    loop (e.g. notebooks, the FastAPI request handler in Phase 3) still
    work. Synchronous-callsite ergonomics matter more than throughput
    at our cadence.
    """
    result: dict[str, Any] = {}

    def _target():
        loop = asyncio.new_event_loop()
        try:
            result["value"] = loop.run_until_complete(coro)
        except BaseException as e:  # noqa: BLE001 — re-raised below
            result["error"] = e
        finally:
            loop.close()

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join()
    if "error" in result:
        raise result["error"]
    return result["value"]


def run_agent(
    agent,
    user_text: str,
    output_schema: Any | None = None,
    *,
    lens: str | None = None,
):
    """Synchronously run an ADK Agent with a single user message.

    Args:
      agent: an ADK ``Agent``/``LlmAgent``. If the agent has
        ``output_schema`` configured at build time, it will be used by
        ADK to constrain Gemini output; passing ``output_schema`` here
        too is a belt-and-braces step (the caller validates again).
      user_text: the user-role prompt content. The instruction lives
        on the Agent itself; this is the per-call input.
      output_schema: optional Python type to validate the response
        against (``Obligation``, ``list[Obligation]``, etc.). If
        omitted, the raw response text is returned.
      lens: optional lens / critic name when the call originated from a
        debate panel. Forwarded to the observability ``log_run`` writer
        so panel rows are tagged with the lens that produced them.

    Returns:
      The validated pydantic model (or list thereof) if ``output_schema``
      was provided; otherwise the raw response string.

    Raises:
      RunnerError: ADK produced no text, or text didn't parse / validate.
    """
    import time
    import random

    # Lazy import — observability is best-effort and must never block
    # importing this module (e.g. when google.cloud.spanner isn't installed
    # in a constrained eval environment).
    from app.observability.run_log import log_run

    max_attempts = 6
    backoff = 2.0
    agent_name = getattr(agent, "name", "?")

    for attempt in range(max_attempts):
        t0 = time.monotonic()
        try:
            text = _run_in_fresh_loop(_run_once_async(agent, user_text))
            latency_ms = int((time.monotonic() - t0) * 1000)
            log_run(
                agent_name=agent_name,
                input_text=user_text,
                output_text=text,
                lens=lens,
                latency_ms=latency_ms,
            )
            if output_schema is None:
                return text
            return _coerce(text, output_schema)
        except Exception as e:
            latency_ms = int((time.monotonic() - t0) * 1000)
            err_str = str(e)
            is_rate_limit = (
                "429" in err_str
                or "RESOURCE_EXHAUSTED" in err_str
                or "exhausted" in err_str.lower()
            )
            if is_rate_limit and attempt < max_attempts - 1:
                sleep_time = (backoff ** attempt) + random.uniform(1.0, 3.0)
                time.sleep(sleep_time)
                continue
            # Final failure (or non-rate-limit error) — log before re-raise.
            log_run(
                agent_name=agent_name,
                input_text=user_text,
                output_text="",
                lens=lens,
                latency_ms=latency_ms,
                error=err_str[:500],
            )
            raise


def require_real_llm(node: str) -> None:
    """Helper for sub-agent ``real_*`` functions to fail loudly if mis-called.

    Used like::

        def real_decompose(clauses):
            require_real_llm("decompose")
            ...

    The chain.py shim never calls ``real_*`` when the flag is off, but a
    direct caller (eval, notebook) might — better a clear error than a
    silent live-Gemini call when the env is unset.
    """
    if not real_llm_enabled():
        raise RuntimeError(
            f"real_{node}() called but {ENV_FLAG} is not set. "
            f"Export {ENV_FLAG}=1 or use stub_{node}() for offline."
        )


# Re-exports for convenience.
__all__ = [
    "ENV_FLAG",
    "RunnerError",
    "real_llm_enabled",
    "require_real_llm",
    "run_agent",
]
