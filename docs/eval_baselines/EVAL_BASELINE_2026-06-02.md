# Eval Baseline — 2026-06-02 (Pre-Debate-Panel)

Captured at the start of D1 (Stage-2 day 1) to give a pre-debate-panel anchor for the multi-perspective work in D2–D3 and the GEPA/SimplePromptOptimizer pass in D7.

## Run setup
- Tool: `.venv/bin/adk eval app tests/eval/evalsets/curator.evalset.json --config_file_path=tests/eval/eval_config.json`
- Env: `CURATOR_REAL_LLM=1`, `GOOGLE_CLOUD_PROJECT=curator-research`, ADC via `.secrets/SA_aidnicloudcurator.json`.
- Model: `gemini-flash-latest` (both agent + LLM-as-judge), `numSamples=1`.
- Backend: `GoogleLLMVariant.VERTEX_AI`, location `global`.
- Raw log: `docs/eval_baselines/raw_2026-06-02.log` (108 lines, ~3 mins wall-clock).

## Results (3 of 5 eval cases completed)

The other 2 (`diff_quality`, `judge_downstream_effects`) hit `429 RESOURCE_EXHAUSTED` on Vertex AI Gemini-flash quota mid-run and were not re-tried before the run finished. The 3 that did complete all scored a perfect 1.0 on every rubric.

| eval_id | overall | decomposition_fanout | coverage_honesty | diff_specificity | downstream_effects | citations |
|---|---|---|---|---|---|---|
| decompose_fanout | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| map_coverage_missing | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| qna_followup_citations | 1.0 | 1.0 | 1.0 | — (judge dropped) | 1.0 | 1.0 |
| diff_quality | n/a — 429 rate-limited |  |  |  |  |  |
| judge_downstream_effects | n/a — 429 rate-limited |  |  |  |  |  |

## Interpretation

Perfect rubric scores on the 3 cases that completed almost certainly reflect a combination of (a) `gemini-flash-latest` being generous as an LLM-as-judge against a 5-case evalset shaped to its own tooling, (b) thin rubrics (5 cases is a low resolution), and (c) only 1 judge sample. **Take "1.0" as ceiling, not signal.** The real measurement will be against the 30-case expanded evalset in D7 after the Simulation-driven expansion.

What this baseline genuinely fences:
- The full chain `decompose → map → diff → judge → qna` runs end-to-end on real Gemini against the demo fixture amendment without exceptions.
- The 4 rubrics that scored on every completed case (decomposition_fanout, coverage_honesty, downstream_effects, citations) are within the ≥0.7 floor.

## Next checkpoints

- **D3 EOD (Gate 1):** Re-run after multi-perspective debate panels for decompose and judge land. Expect richer fan-out behaviour and possibly *more* downstream effects → ≥0.7 still required, ideally with visibly more obligations per fan-out case.
- **D7 (Agent Optimizer pass):** Run before and after the GEPA / SimplePromptOptimizer pass on the 30-case expanded evalset. Capture before/after deltas to `docs/OPTIMIZATION_LOG.md`. This is the demo's "the agent improved itself" proof-point.

## Known issue
The `429 RESOURCE_EXHAUSTED` on 2 cases indicates that running the full 5-case evalset bumps against the project's per-minute Gemini quota when both agent and judge calls fire in quick succession. Two mitigations:
1. Add `--max-concurrent-evals=1` if/when ADK exposes the flag.
2. Insert ~10s sleeps between cases, or use `agents-cli eval` (if it exposes throttling).

Not a blocker for Gate 1 — the dropped cases just need a re-run after a few minutes.
