"""Single source of truth for which Gemini model Curator uses.

Every ADK Agent in :mod:`app.sub_agents` reads :func:`curator_model_name`
instead of hard-coding ``"gemini-flash-latest"``. Operators can swap
models per deploy via ``CURATOR_GEMINI_MODEL`` — no code change, no
redeploy of any sub-agent module.

Default: ``gemini-2.5-flash-lite``. It is roughly **3× cheaper on
input, 6× cheaper on output, and consistently faster** than the
``gemini-flash-latest`` alias (which currently points at
``gemini-2.5-flash``). For the Curator workload — short prompts,
structured-output JSON, high per-chain call count — flash-lite is the
right default. Switch back to the full ``gemini-2.5-flash`` (or any
other Vertex AI Gemini model id) by setting the env var.

Cost-tracking lives next door in :mod:`app.observability.cost` and
keys on the model name returned here.
"""

from __future__ import annotations

import os

ENV_VAR = "CURATOR_GEMINI_MODEL"
DEFAULT_MODEL = "gemini-2.5-flash-lite"

# Determinism knobs. Regulatory extraction must be reproducible and auditable:
# the same two documents should yield the same parameter table and obligations
# every run. Gemini's *default* temperature is non-zero, which produced the
# observed run-to-run swings (e.g. 11 vs 3 parameter rows on the same document).
# We pin temperature to 0 and a fixed seed across every Curator agent. Diversity
# in the debate panels comes from the four *distinct lens prompts*, not from
# sampling noise — so temperature 0 preserves the multi-perspective design while
# removing jitter. Tunable via env for A/B experiments.
TEMPERATURE_ENV = "CURATOR_LLM_TEMPERATURE"
SEED_ENV = "CURATOR_LLM_SEED"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_SEED = 7


def curator_model_name() -> str:
    """Return the Gemini model id to use for every Curator agent call.

    Resolved at call time (not import time) so a runtime env change
    takes effect on the next agent build — useful for A/B comparing
    model variants without restarting the service.
    """
    return os.environ.get(ENV_VAR, DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _resolve_float(env: str, default: float) -> float:
    try:
        return float(os.environ[env])
    except (KeyError, ValueError):
        return default


def _resolve_seed(default: int) -> int | None:
    raw = os.environ.get(SEED_ENV)
    if raw is None:
        return default
    raw = raw.strip().lower()
    if raw in ("", "none", "off"):
        return None  # let a model that rejects `seed` run without one
    try:
        return int(raw)
    except ValueError:
        return default


def curator_generation_config(temperature: float | None = None, seed: int | None = -1):
    """Deterministic ``GenerateContentConfig`` shared by every Curator agent.

    Lazy-imports ``google.genai`` so the offline stub path (which never builds a
    real agent) is unaffected. ``temperature`` defaults to 0; ``seed`` defaults
    to a fixed value. Pass ``seed=None`` (or ``CURATOR_LLM_SEED=none``) to omit
    the seed for a model that rejects it.
    """
    from google.genai import types

    temp = (
        _resolve_float(TEMPERATURE_ENV, DEFAULT_TEMPERATURE)
        if temperature is None
        else temperature
    )
    resolved_seed = _resolve_seed(DEFAULT_SEED) if seed == -1 else seed
    kwargs: dict = {"temperature": temp}
    if resolved_seed is not None:
        kwargs["seed"] = resolved_seed
    return types.GenerateContentConfig(**kwargs)


__all__ = [
    "ENV_VAR",
    "DEFAULT_MODEL",
    "curator_model_name",
    "curator_generation_config",
]
