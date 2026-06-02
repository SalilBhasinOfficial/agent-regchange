"""Lightweight local Sampler for Curator's prompt optimizer.

ADK ships ``LocalEvalSampler`` which routes through the full evaluation
service. That's the right surface for production. For the D7 hackathon
demo, we use a slim drop-in that:

1. Reads cases from the in-memory ``eval_cases`` list (the 30-case D7
   evalset already loaded by ``run_gepa.py``).
2. Implements the ``Sampler[UnstructuredSamplingResult]`` protocol with
   the minimum methods ``SimplePromptOptimizer`` actually calls.
3. Enforces a hard per-call budget so a runaway optimizer can't spend
   more than the configured cap.

When sampling, we run the **candidate agent's instruction** (not the
panel) against the case's user message, then score it via a single
gemini-flash rubric-judge pass. This mirrors ``adk eval`` but in-process
and with explicit cost accounting.
"""

from __future__ import annotations

import asyncio
from typing import Any, Iterable

try:  # pragma: no cover - import-time check
    from google.adk.optimization.sampler import Sampler
    from google.adk.optimization.data_types import UnstructuredSamplingResult
except ImportError as exc:  # pragma: no cover - clear message at import time
    raise ImportError(
        "google.adk.optimization.sampler not available. Install google-adk[eval]."
    ) from exc


_RUBRIC_PROMPT = """You are scoring an agent's response against five rubrics.
Return JSON with a `score` field in [0.0, 1.0].

Rubrics:
1. decomposition_fanout: the response surfaces multiple distinct atomic
   obligations when the clause encodes multiple (subject, action) tuples.
2. coverage_honesty: the response labels coverage faithfully (full / partial
   / missing / stale / contradicts) and is willing to return 'missing' when
   appropriate.
3. diff_specificity: suggested edits cite the source clause and obligation.
4. downstream_effects: surfaces non-obvious downstream effects (ICAAP,
   Pillar 3, RMC, etc.).
5. citations: Q&A answers cite obligation ids and policy section ids.

User asked:
{user_msg}

Agent responded:
{agent_response}

Return ONLY a JSON object with a single key `score` (float). No prose."""


class CuratorEvalSampler(Sampler[UnstructuredSamplingResult]):
    """Lightweight Sampler for SimplePromptOptimizer.

    Attributes:
      eval_cases: 30 cases loaded from the curator evalset.
      budget_usd: hard cost cap. When estimated spend exceeds this, the
        sampler returns a sentinel "budget exhausted" score (0.0) without
        invoking the model.
      calls_made: count of agent + judge calls actually executed.
    """

    def __init__(
        self,
        eval_cases: list[dict[str, Any]],
        budget_usd: float = 15.0,
        approx_cost_per_call: float = 0.02,
    ) -> None:
        self.eval_cases = eval_cases
        self.budget_usd = float(budget_usd)
        self.approx_cost_per_call = float(approx_cost_per_call)
        self.calls_made = 0
        # Each scoring round = 1 agent call + 1 judge call. So one scoring
        # round consumes 2 × approx_cost_per_call.
        self.budget_call_cap = int(budget_usd / (2 * approx_cost_per_call))

    @property
    def estimated_cost_usd(self) -> float:
        return self.calls_made * self.approx_cost_per_call

    # ---- Sampler protocol ----------------------------------------------

    def get_train_example_ids(self) -> list[str]:
        """Use the first 60% of cases for training (rounded up)."""
        n = max(1, int(len(self.eval_cases) * 0.6 + 0.5))
        return [c["eval_id"] for c in self.eval_cases[:n]]

    def get_validation_example_ids(self) -> list[str]:
        """Use the remaining 40% for validation."""
        n = max(1, int(len(self.eval_cases) * 0.6 + 0.5))
        return [c["eval_id"] for c in self.eval_cases[n:]] or [
            c["eval_id"] for c in self.eval_cases[:1]
        ]

    async def sample_and_score(
        self,
        agent: Any,
        example_set: str,
        example_ids: Iterable[str] | None = None,
        capture_full_eval_data: bool = False,
    ) -> UnstructuredSamplingResult:
        """SimplePromptOptimizer's final-validation path calls this with
        only ``(agent, "validation")`` — no example_ids. Default to the
        appropriate split's IDs when omitted."""
        if example_ids is None:
            if example_set == "validation":
                example_ids = self.get_validation_example_ids()
            else:
                example_ids = self.get_train_example_ids()
        """Run the candidate agent on each example and return per-id scores.

        Returns a ``UnstructuredSamplingResult`` whose ``scores`` field is a
        dict of ``eval_id → float in [0, 1]``.
        """
        from app.runners import run_agent
        from google.adk.agents import LlmAgent
        from google.adk.models import Gemini
        from google.genai import types

        case_by_id = {c["eval_id"]: c for c in self.eval_cases}
        scores: dict[str, float] = {}

        # One LlmAgent constructed per scoring round, with a tiny rubric
        # prompt. We don't reuse Curator's run_agent helper for the judge
        # call because it carries decompose / map / etc. logging overhead.
        judge_agent = LlmAgent(
            name="optimizer_rubric_judge",
            model=Gemini(model="gemini-2.5-flash"),
            instruction="You are a strict rubric judge. Return only valid JSON.",
        )

        for ex_id in example_ids:
            if self.calls_made >= 2 * self.budget_call_cap:
                # Budget exhausted — return 0.0 for the remaining ids so
                # the optimizer can still finish a round without runaway spend.
                scores[ex_id] = 0.0
                continue
            case = case_by_id.get(ex_id)
            if not case:
                scores[ex_id] = 0.0
                continue
            user_msg = (
                case.get("conversation", [{}])[0]
                .get("user_content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )
            try:
                # 1) Run the candidate agent against the eval case's user msg.
                response = run_agent(agent, user_msg, output_schema=None)
                self.calls_made += 1
                response_str = (
                    str(response)
                    if not isinstance(response, str)
                    else response
                )[:8000]

                # 2) Score the response against the rubric prompt.
                rubric_user = _RUBRIC_PROMPT.format(
                    user_msg=user_msg[:2000],
                    agent_response=response_str,
                )
                judge_text = run_agent(judge_agent, rubric_user, output_schema=None)
                self.calls_made += 1

                # 3) Extract score from JSON.
                import json as _json
                import re as _re

                # Strip code fences if present
                payload = (judge_text or "").strip()
                if payload.startswith("```"):
                    payload = _re.sub(r"^```[a-z]*\n?", "", payload, count=1)
                    if payload.endswith("```"):
                        payload = payload[:-3]
                try:
                    parsed = _json.loads(payload)
                    s = float(parsed.get("score", 0.0))
                except Exception:  # noqa: BLE001 — fall back to 0
                    s = 0.0
                scores[ex_id] = max(0.0, min(1.0, s))
            except Exception:  # noqa: BLE001 — score 0 on any failure
                scores[ex_id] = 0.0

        # SimplePromptOptimizer reads .scores; UnstructuredSamplingResult
        # also accepts an optional .data dict for per-example metadata.
        return UnstructuredSamplingResult(scores=scores, data=None)
