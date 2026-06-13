# Curator — Generality & Robustness Audit (2026-06-13)

A framework-wide review aimed at one question the owner raised: **does Curator
generalise to a large array of regulatory documents — other RBI circulars, SEBI,
IRDAI, prudential *and* non-prudential, varied layouts, single- and two-document
modes — or is it overfit to the 6 RBI capital-adequacy / Basel-III PDFs it was
built on?**

Three independent reviewer passes (ingestion, agent-behaviour, downstream) plus
direct code reading produced the findings below. Each finding lists the
file, the assumption, a concrete out-of-distribution scenario, severity, and the
fix. The "Fixed in this pass" section records what shipped; "Backlog" records
what is scoped but deferred.

---

## Executive summary

The system was demonstrably tuned on one document family. The biggest
generality risks were:

1. **Non-determinism** — no `temperature`/`seed` anywhere, so the same document
   yielded different parameter tables run-to-run (observed 11 vs 3 rows). **Fixed.**
2. **A stuck audit gate** — `pass` required an empty findings list, so every real
   document landed on permanent "review / not publishable". The control gate
   conveyed no information because it never varied. **Fixed (severity-calibrated).**
3. **Over-aggressive parameter suppression** — the first "proven-movement" fix
   dropped *all* null-old `new` rows whenever any single movement existed, which
   would discard genuinely-new levers on a new-framework document. **Fixed
   (evidence-based restatement detection).**
4. **A capital-only param-diff prompt** — steered to risk-weights/CRAR even on a
   KYC or disclosure circular, so it hallucinated capital framing or returned
   nothing. **Fixed (domain-general prompt + empty-return escape).**
5. **Title extraction collapsing to the raw filename** on any document whose
   name isn't a clean RBI-keyword heading. **Mitigated (smart filename title).**
6. **Evaluator-facing fragility** — `impact is None` 500'd the page, the gallery
   hid valid runs, errors showed raw tracebacks, and a `terraform apply` would
   revert prod to stub mode. **Fixed.**

---

## Fixed in this pass

| ID | Area | Fix | Commit |
|----|------|-----|--------|
| G1 | Determinism | `temperature=0` + fixed `seed` via `curator_generation_config()` on all 13 agent factories. Debate diversity comes from the 4 distinct lens prompts, not sampling noise. | af8dc68 |
| T1 | Title | `_prettify_filename()` fallback: `05_credit_risk_standardised_2026-04-27_RBI-…` → `Credit Risk Standardised (RBI · 2026-04-27)`. Reject trailing-period sentences + `(n)`-prefixed clauses. | 8c31676, af8dc68 |
| P2 | Param-diff | Evidence-based restatement suppression: drop a null-old `new` row only when ALL its distinctive concept tokens already appear in the prior text; keep movements + prior-citing rows; empty-guard preserves new-table docs. | 4810878 |
| A1 | Audit | `_calibrate_verdict()` derives verdict/publishable from worst finding severity (blocker→fail, major→review, else pass). "No policy corpus in a doc-vs-doc run" reclassified as an info scoping note. | 4810878 |
| F1 | Finalize | Loop fires only on actionable (major/blocker) findings, not info/minor. | 4810878 |
| P1 | Param-diff | De-Baselized prompt: quantitative levers now include thresholds, timelines, fees, frequencies, ratios *and* prudential weights; explicit `[]` return for narrative circulars. | dab7374 |
| R1 | Reconciler | `_normalize_action` stops sorting+capping tokens (which merged distinct obligations); keeps order + numeric tokens. | dab7374 |
| U1 | UI | Guard `state.impact is None` (was a 500); reframe audit banner so "review" reads as reviewer notes, not failure. | 3cd035b |
| U2 | UI | Gallery shows runs with params **or** obligations (was hiding every single-doc / Inbox run). | 3cd035b |
| U3 | UI | Friendly, rate-limit-aware error message instead of a raw traceback. | 3cd035b |
| U4 | Obs | Roll up per-call cost into `pipeline_runs.total_cost_usd` (was always NULL). | 3cd035b |
| U5 | Chain | Pre-diff clause filter never empties the clause set (cascade guard). | 3cd035b |
| O1 | Ops | `terraform service.tf` codifies `CURATOR_REAL_LLM/GROUNDING/AGENT_RUN_LOG/model` + Spanner/project/location so `terraform apply` can't revert prod to stub. | 3cd035b |

All 54 unit+integration tests pass; offline stub chain green throughout.

---

## Backlog (scoped, not yet shipped)

Ordered by leverage. None block current demos; each is a real generality gap.

### Ingestion
- **B-I1 — Three divergent heading-type sets** (`docai`, `graph_extractor`,
  `pipeline`). A `heading-3`/`section_heading` block starts a clause and seeds a
  parent heading but is invisible to title extraction. Unify into one constant.
- **B-I2 — Title length cap (160) + trailing-period reject** still drop some long
  / period-terminated real titles. Mitigated by the filename fallback, but the
  cap could be raised to ~240 with a sentence-likeness check rather than length.
- **B-I3 — Non-PDF / encrypted / scanned inputs.** `mime_type` hard-coded to
  `application/pdf`; encrypted PDFs silently degrade; scanned PDFs with sparse
  OCR collapse to one giant clause. Detect mime/encryption; warn on low text yield.
- **B-I4 — Page-spanning table wider than the 2-page overlap is truncated** at a
  30-page batch boundary — silently losing the tail rows of a long risk-weight
  schedule. Widen overlap dynamically or use the Doc AI batch API for long tables.
- **B-I5 — `prediff` assumes the two docs are versions of the same instrument.**
  Two unrelated docs (cross-framework) produce a near-100%-changed blob and an
  O(n·m) similarity blow-up. Gate similarity mode on a quick shared-shingle check.
- **B-I6 — `split_paragraphs` single-newline explosion** shatters wrapped lines
  into one "paragraph" each. Prefer the already-segmented chunk boundaries.
- **B-I7 — Clause/doc IDs are filename + ordinal derived** → unstable across
  re-ingest / page-split changes. Derive from a content hash.
- **B-I8 — `>500`-page docs silently truncated**; surface in the UI, not just logs.

### Agent behaviour
- **B-A1 — Reflector is inert** (`reflect()` returns `escalate=True` everywhere;
  `reflect_and_requery` is never called from the demo path). Either wire it or
  document it as future work so it isn't mistaken for active self-correction.
- **B-A2 — param_diff is the only stage that reads Doc B.** For a non-quantitative
  document where param_diff legitimately returns `[]`, nothing else diffs old vs
  new — the "change analysis" degenerates into plain obligation extraction. A
  future obligation-level diff would restore the change dimension for those docs.
- **B-A3 — Finalize can only delete rows + rewrite the summary**, and its
  exclusion key (parameter name only) is blunter than the cleaner's composite
  key. It cannot remediate findings like "inferred old value" or "missing
  effective date", so those findings persist across the loop. Add per-row
  corrections + composite-key exclusion (needs a small `Finalization` schema add).
- **B-A4 — `_salvage_truncated_array` handles arrays only**, not a truncated
  top-level object (judge/finalize/audit return single objects). Extend salvage
  or rely on the size caps and log when salvage drops content.

### Eval / tuning
- **B-E1 — Evalset (30 cases) is shaped around the capital-adequacy family.** Add
  SEBI / IRDAI / non-prudential (KYC, disclosure, conduct) cases to actually
  measure generality, not just in-distribution rubric pass rate.
- **B-E2 — Run a SimplePromptOptimizer pass** on the now-deterministic agents and
  capture before/after rubric deltas (GEPA backend currently raises
  `NotImplementedError`; SimplePromptOptimizer is the default).

---

## Method note

Findings came from three parallel reviewer passes over `app/` plus direct code
reading and live runs against the two demo document pairs (05-vs-06 credit-risk;
03-vs-04 capital-adequacy). A free, separate model pass (the `agy1` Gemini-CLI
reviewer) is available to cross-check generality from an independent perspective;
its prompt is at `docs/audit/agy1_review_prompt.txt`.
