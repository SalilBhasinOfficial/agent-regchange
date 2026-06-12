"""Curator prompt optimizer driver.

Wires Google ADK's prompt optimizers to the Curator decompose sub-agent.

Strategy
--------
1. Prefer ``SimplePromptOptimizer`` (simpler API, deterministic per pass).
2. Fall back to ``GEPARootAgentPromptOptimizer`` only if explicitly requested
   via ``--algo gepa`` (it requires the third-party ``gepa`` package and a
   working ``Sampler`` adapter — more moving parts).
3. Bound everything by a tight LLM-call budget so a runaway loop can't
   spend more than the configured cap.

Usage
-----
    .venv/bin/python -m app.optimization.run_gepa \
        --target=decompose \
        --algo=simple \
        --num-iterations=2 \
        --batch-size=3 \
        --budget-usd=15

What this does
--------------
1. Snapshots the **current** ``DECOMPOSE_INSTRUCTION`` from
   ``app/sub_agents/decompose.py`` (the prompt under optimisation).
2. Builds the agent via the existing ``decompose._build_single_decompose_agent``
   (we optimise the legacy single-shot agent, not the panel — the panel's
   four lens preambles are derived from this single instruction).
3. Runs the optimizer for ``num_iterations`` rounds. Each round samples
   ``batch_size`` cases from ``tests/eval/evalsets/curator.evalset.json``,
   evaluates the candidate against them, and (if scored higher) updates the
   best prompt.
4. Writes the before/after prompts + scores to
   ``docs/OPTIMIZATION_LOG.md`` (append-only) — the demo's
   "agent improved its own prompt" proof-point.

Acceptance
----------
- Stays within ``--budget-usd`` (hard cap; the script aborts when the
  estimated cost exceeds the cap).
- Always writes ``docs/OPTIMIZATION_LOG.md`` even on early termination —
  partial progress is documented.
- Never mutates the live ``decompose.py`` prompt. Operators copy the
  proposed prompt manually if they want to ship it (the prompt is a
  load-bearing demo artifact; auto-rewriting it without review is the
  wrong default).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_PATH = REPO_ROOT / "docs" / "OPTIMIZATION_LOG.md"

# Per-call cost estimate for gemini-flash-latest. Conservative.
APPROX_COST_USD_PER_CALL = 0.02


def _resolve_target_prompt(target: str) -> str:
    """Pull the current instruction prompt for the named sub-agent."""
    if target == "decompose":
        from app.sub_agents.decompose import DECOMPOSE_INSTRUCTION

        return DECOMPOSE_INSTRUCTION
    if target == "judge":
        from app.sub_agents.judge import JUDGE_INSTRUCTION

        return JUDGE_INSTRUCTION
    raise ValueError(f"unknown target: {target}")


def _build_agent(target: str):  # type: ignore[no-untyped-def]
    """Build the single-shot agent (NOT the panel) for optimisation."""
    if target == "decompose":
        from app.sub_agents.decompose import _build_single_decompose_agent

        return _build_single_decompose_agent()
    if target == "judge":
        from app.sub_agents.judge import _build_single_judge_agent

        return _build_single_judge_agent()
    raise ValueError(f"unknown target: {target}")


def _load_eval_cases() -> list[dict[str, Any]]:
    """Read the evalset (30 cases as of D7 expansion) and return the list."""
    evalset_path = REPO_ROOT / "tests" / "eval" / "evalsets" / "curator.evalset.json"
    with evalset_path.open() as f:
        data = json.load(f)
    return data.get("eval_cases", [])


def _append_log(section_md: str) -> None:
    """Append a section to docs/OPTIMIZATION_LOG.md (creates if missing)."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_PATH.exists():
        LOG_PATH.write_text(
            "# Curator Agent Optimizer — Log\n\n"
            "Append-only record of prompt-optimisation passes. Each section "
            "captures the input prompt, the algorithm used, the iteration "
            "scores, and the proposed output prompt. Operators decide "
            "whether to merge a proposed prompt into the live source.\n\n"
            "---\n\n"
        )
    with LOG_PATH.open("a") as f:
        f.write(section_md)
        f.write("\n\n---\n\n")


async def run_simple_optimizer(
    target: str,
    num_iterations: int,
    batch_size: int,
    budget_usd: float,
) -> dict[str, Any]:
    """Run SimplePromptOptimizer with a hand-rolled local sampler.

    Returns the optimisation result dict. Always writes to OPTIMIZATION_LOG.md.
    """
    from google.adk.optimization.simple_prompt_optimizer import (
        SimplePromptOptimizer,
        SimplePromptOptimizerConfig,
    )

    initial_agent = _build_agent(target)
    initial_prompt = _resolve_target_prompt(target)
    cases = _load_eval_cases()
    if not cases:
        raise RuntimeError("evalset is empty — cannot optimise without samples")

    # The official LocalEvalSampler wires through ADK's eval pipeline; for the
    # D7 demo we use a lightweight local sampler that just runs the chain on
    # the named cases and scores via the rubric judge. The full path is
    # documented but deferred to Phase-5 polish (see plan §What NOT to do).
    from app.optimization.local_sampler import CuratorEvalSampler

    sampler = CuratorEvalSampler(
        eval_cases=cases,
        budget_usd=budget_usd,
        approx_cost_per_call=APPROX_COST_USD_PER_CALL,
    )

    config = SimplePromptOptimizerConfig(
        optimizer_model="gemini-2.5-flash",
        num_iterations=num_iterations,
        batch_size=batch_size,
    )
    optimizer = SimplePromptOptimizer(config=config)

    t0 = time.monotonic()
    try:
        result = await optimizer.optimize(initial_agent, sampler)
    except Exception as exc:  # noqa: BLE001 — log and degrade
        elapsed = int(time.monotonic() - t0)
        _append_log(
            f"## Run {datetime.now(timezone.utc).isoformat()}\n\n"
            f"- target: `{target}`\n"
            f"- algorithm: SimplePromptOptimizer\n"
            f"- status: **FAILED** ({type(exc).__name__})\n"
            f"- elapsed: {elapsed}s\n"
            f"- error: {exc!s}\n\n"
            f"### Initial prompt (unchanged)\n```\n{initial_prompt[:2000]}\n```\n"
        )
        raise

    elapsed = int(time.monotonic() - t0)
    # OptimizerResult shape: result.optimized_agents: list[AgentWithScores]
    # where AgentWithScores has .optimized_agent (Agent) and .overall_score.
    optimized_list = getattr(result, "optimized_agents", []) or []
    if optimized_list:
        top = optimized_list[0]
        best_agent = getattr(top, "optimized_agent", None)
        overall_score = getattr(top, "overall_score", None)
    else:
        best_agent = None
        overall_score = None
    best_prompt = getattr(best_agent, "instruction", None) if best_agent else None

    delta_md = ""
    if best_prompt and best_prompt != initial_prompt:
        # Show first-100-char diff inline as evidence
        initial_head = initial_prompt[:200].replace("\n", " ")
        proposed_head = best_prompt[:200].replace("\n", " ")
        delta_md = (
            f"\n### Prompt delta (head)\n"
            f"- **Initial (200 chars):** `{initial_head}…`\n"
            f"- **Proposed (200 chars):** `{proposed_head}…`\n"
            f"- **Prompts differ:** YES\n"
        )
    elif best_prompt:
        delta_md = "\n### Prompt delta (head)\n- **Prompts differ:** NO — optimizer kept the original.\n"

    _append_log(
        f"## Run {datetime.now(timezone.utc).isoformat()}\n\n"
        f"- target: `{target}`\n"
        f"- algorithm: SimplePromptOptimizer\n"
        f"- num_iterations: {num_iterations}\n"
        f"- batch_size: {batch_size}\n"
        f"- elapsed: {elapsed}s\n"
        f"- eval cases sampled: {sampler.calls_made} agent+judge calls\n"
        f"- estimated spend: ${sampler.estimated_cost_usd:.2f} (cap: ${budget_usd:.2f})\n"
        f"- candidates in Pareto front: {len(optimized_list)}\n"
        f"- best overall_score: {overall_score if overall_score is not None else 'n/a'}\n"
        f"{delta_md}\n"
        f"### Initial prompt\n```\n{initial_prompt[:2000]}\n```\n\n"
        f"### Proposed prompt (from optimizer)\n```\n"
        f"{(best_prompt or '<no candidate produced>')[:4000]}\n```\n"
    )
    return {
        "target": target,
        "algorithm": "SimplePromptOptimizer",
        "elapsed_seconds": elapsed,
        "candidates_count": len(optimized_list),
        "best_overall_score": overall_score,
        "initial_prompt": initial_prompt,
        "best_prompt": best_prompt,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Curator prompt optimizer driver")
    parser.add_argument("--target", default="decompose", choices=["decompose", "judge"])
    parser.add_argument("--algo", default="simple", choices=["simple", "gepa"])
    parser.add_argument("--num-iterations", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--budget-usd", type=float, default=15.0)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip the live optimize() call; just log the planned configuration.",
    )
    args = parser.parse_args()

    if args.dry_run:
        prompt = _resolve_target_prompt(args.target)
        _append_log(
            f"## Dry-run plan {datetime.now(timezone.utc).isoformat()}\n\n"
            f"- target: `{args.target}`\n- algorithm: {args.algo}\n"
            f"- num_iterations: {args.num_iterations}\n"
            f"- batch_size: {args.batch_size}\n"
            f"- budget cap: ${args.budget_usd:.2f}\n\n"
            f"### Initial prompt (would have been optimised)\n```\n{prompt[:2000]}\n```\n"
        )
        print(f"Dry-run written to {LOG_PATH}")
        return

    if args.algo == "gepa":
        # GEPA path requires the third-party `gepa` package and an
        # UnstructuredSamplingResult adapter. The plan calls this out as
        # the fallback only — SimplePromptOptimizer is the default. Implement
        # at need.
        raise NotImplementedError(
            "GEPA path not wired in D7. Use --algo=simple. "
            "GEPA fallback is documented in plan §D7 Track B."
        )

    # Ensure GOOGLE_CLOUD_PROJECT and ADC are set, otherwise the optimizer
    # call will fail at the first model invocation.
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        raise RuntimeError(
            "GOOGLE_CLOUD_PROJECT is unset. Source scripts/env.sh first."
        )

    result = asyncio.run(
        run_simple_optimizer(
            target=args.target,
            num_iterations=args.num_iterations,
            batch_size=args.batch_size,
            budget_usd=args.budget_usd,
        )
    )
    print(f"Done. Log: {LOG_PATH}")
    print(f"  Algorithm: {result['algorithm']}")
    print(f"  Elapsed: {result['elapsed_seconds']}s")
    print(f"  Candidates in Pareto front: {result.get('candidates_count', 0)}")
    print(f"  Best overall_score: {result.get('best_overall_score')}")


if __name__ == "__main__":
    main()
