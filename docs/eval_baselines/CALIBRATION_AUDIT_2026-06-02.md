# Confidence Calibration Audit — 2026-06-02

## What we're checking

When the chain reports `confidence=0.92` on an obligation, does that
correlate with the case actually passing the rubric? Or is the
confidence number cosmetic — produced by a heuristic that doesn't
discriminate good from bad?

## Data sources used

1. `docs/eval_baselines/GATE1_2026-06-04.md` — post-debate eval result
   (5/5 cases at 1.0 across every rubric on the original 5-case evalset).
2. `app/sub_agents/reconciler.py::_merge_obligations` — confidence
   formula: `avg(lens_confs) × (0.6 + 0.1 × n_lenses_seen)`. Ranges
   from 0.7× (1 lens) to 1.0× (4 lenses).
3. Live chain runs from D2-D6 (real-LLM panel): the chain consistently
   reports confidences in the 0.7–0.95 band when run with real Gemini.

## Findings

- **All 5 baseline cases scored 1.0** on the rubric judge. The eval
  granularity is too coarse to discriminate confidence buckets — a
  rubric score of 1.0 vs 0.95 is statistically equivalent on a 5-case
  set.
- **The agreement factor (0.6 + 0.1 × n_lenses)** is mathematically
  fine but uncalibrated. A 1-lens-only obligation gets 0.7× scaling,
  but we have no measurement that says 0.7 is the right floor (it
  could be 0.4 if single-lens recall is unreliable; it could be 0.85
  if single-lens recall is fine).
- **Stubs hardcode `confidence=1.0`** which is overconfident in any
  comparative analysis. Acceptable because the offline path is an
  airlock, not a live demo.

## Honest verdict

The confidence number is **directionally useful but not statistically
calibrated**. It reliably distinguishes high-agreement obligations
(all 4 lenses caught it) from single-lens-only obligations. It does
NOT yet correlate to rubric pass-rate because the rubric granularity
is too coarse.

## Devpost-write-up disclosure

> Confidence is calibrated to cross-lens agreement, not eval pass rate.
> We use it as a per-obligation signal to the Reflector (low-confidence
> obligations trigger a Spanner Graph re-query for additional context),
> not as a statistical posterior. Future work: calibrate against a
> ≥1000-case evalset where rubric scores have finer granularity.

## Remediation policy

- D7 GEPA pass: include confidence as one of the optimization signals
  so the optimizer can learn to emit calibrated confidences.
- Phase 5: 1000-case evalset for statistical-signal-rich calibration.
