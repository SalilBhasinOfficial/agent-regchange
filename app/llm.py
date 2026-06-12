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


def curator_model_name() -> str:
    """Return the Gemini model id to use for every Curator agent call.

    Resolved at call time (not import time) so a runtime env change
    takes effect on the next agent build — useful for A/B comparing
    model variants without restarting the service.
    """
    return os.environ.get(ENV_VAR, DEFAULT_MODEL).strip() or DEFAULT_MODEL


__all__ = ["ENV_VAR", "DEFAULT_MODEL", "curator_model_name"]
