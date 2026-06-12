"""Per-call USD cost estimator for Curator's Gemini calls.

Wired into :func:`app.runners.run_agent` so every successful (and
final-failed) agent invocation writes a ``cost_usd_estimated`` value
to the ``agent_runs`` Spanner table. That column then powers the
``/cost`` UI endpoint and the long-term spend ceiling guardrails per
:mod:`docs/eval_baselines` budgets.

Pricing
-------
We use a small static dict (:data:`_PRICE_PER_1M_TOKENS`) keyed on
model id. Values are public Vertex AI list-price USD per 1M tokens
(input / output) as of 2026-06. Updating the table is a one-line
change. When a model id isn't known, we fall back to the most
defensive (most expensive) entry so we never silently under-report
spend.

Token accounting
----------------
ADK doesn't surface the raw billed token count from the response
metadata via :class:`google.adk.runners.InMemoryRunner` at the layer
``run_agent`` sees, so we estimate from string length. The heuristic
``len(text) // 4`` gives a reasonable approximation for English /
JSON outputs (BPE tokens average ~4 chars). Production-grade
accounting would tap ``response.usage_metadata`` instead — flagged
in TODO.
"""

from __future__ import annotations

import os

# USD per 1,000,000 tokens. (input, output).
_PRICE_PER_1M_TOKENS: dict[str, tuple[float, float]] = {
    # 2.5 family (June 2026 list prices)
    "gemini-2.5-flash-lite":  (0.10, 0.40),
    "gemini-2.5-flash":       (0.30, 2.50),
    "gemini-2.5-pro":         (1.25, 10.00),
    # 2.0 family (still cheaper for high-volume offline work)
    "gemini-2.0-flash-lite":  (0.075, 0.30),
    "gemini-2.0-flash":       (0.10, 0.40),
    # Public alias — currently points at 2.5-flash.
    "gemini-flash-latest":    (0.30, 2.50),
}

# Defensive fallback when the model id isn't known — use the most
# expensive entry so spend is over-reported rather than missed.
_FALLBACK = (1.25, 10.00)


def _chars_to_tokens(text: str) -> int:
    """Estimate tokens from raw character count. ~4 chars / token."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_cost_usd(
    *,
    model: str,
    input_text: str,
    output_text: str,
) -> float:
    """Return an estimated USD cost for a single Gemini call.

    Args:
      model: Gemini model id (e.g. ``"gemini-2.5-flash-lite"``).
      input_text: prompt that was sent (user text + instruction).
      output_text: response text the model returned.

    Returns:
      Estimated USD spend. ``0.0`` if either text is empty (failed call
      with no observable tokens) or the env disables the estimator.
    """
    if os.environ.get("CURATOR_DISABLE_COST_ESTIMATE", "0") == "1":
        return 0.0
    in_price, out_price = _PRICE_PER_1M_TOKENS.get(model, _FALLBACK)
    in_tokens = _chars_to_tokens(input_text)
    out_tokens = _chars_to_tokens(output_text)
    return (in_tokens / 1_000_000.0) * in_price + (out_tokens / 1_000_000.0) * out_price


__all__ = ["estimate_cost_usd"]
