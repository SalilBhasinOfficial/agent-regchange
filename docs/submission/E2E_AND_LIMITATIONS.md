# Curator — End-to-end validation & honest limitations

*Prepared for the Google for Startups AI Agents Challenge submission (Track 3, India region).*

This document is the integrity backbone of the submission: what was tested
live, what the real numbers are, and what is **not** yet production-grade.
Judges who dig in find honest engineering, not marketing.

---

## End-to-end validation (live, on Cloud Run)

The chain was exercised end-to-end on the **deployed** `curator-chain`
service (not just locally) on 2026-06-11, on real RBI capital-adequacy
documents.

### Full documents are genuinely ingested

Proof from the live Spanner `clauses` table after ingesting the demo corpus:

| Document | Pages | Clauses in Spanner Graph |
|---|---:|---:|
| Capital Adequacy **Master Direction** (consolidated) | **412** | **55** |
| Credit-Risk Standardised Approach capital charge | 85 | 38 (sidecar) |
| Second Amendment, 2026 | 17 | 18 |
| Third Amendment, 2026 | 3 | 9 |

The full 412-page Master Direction is ingested into the graph as 55
heading-rooted clauses — not a truncated slice. The amendment being
*decomposed* yields its own (smaller) clause set; the Master Direction is
ingested as the grounding corpus the Reflector can re-query.

> Doc-AI cost note: the four demo documents ship with pre-parsed sidecars
> (`app/data/sidecars/`), so re-parsing the 412-page MD at demo time costs
> $0 and milliseconds instead of ~$4 and ~10 minutes. A novel PDF a judge
> uploads has no sidecar and goes through **live** Document AI Layout
> Parser. The "Re-run live" button on `/demos` exercises the full path.

### The two curated demos (cached + re-runnable)

`/demos` exposes two capital-adequacy demos. Each result is **cached** in
Spanner `pipeline_runs` (served in milliseconds) with an explicit
**Re-run live** button that executes the full agentic loop. Cached vs live
is labelled on the page — no smoke, no mirrors.

1. **Third Amendment vs Master Direction** — what banks must change.
2. **Credit-Risk Standardised Approach vs Master Direction.**

### Performance is measured and surfaced, not hidden

Every run records per-stage timing + estimated cost to Spanner
`agent_runs`; the impact page renders a **Performance** panel (doc pages,
ingest seconds, debate-chain seconds, total TAT, model, and a per-stage
latency/cost table), and `/stats/{run_id}` returns the full JSON. Live
`/cost` rolls spend up by agent.

Observed shape on `gemini-2.5-flash-lite` (this session's model switch,
~3× cheaper input / 6× cheaper output than the previous default):
- Per model call: **~3–5 s** (was ~12 s on the prior model).
- Ingest: page-count-bound (Doc AI), or sub-second from a sidecar.
- Debate chain: bounded by free-tier Vertex AI quota (429 back-off), not
  by code. `CURATOR_FAST_MODE` caps the fan-out for a snappy interactive
  demo; unset it to run the full panel.

### Test + regression status
- `pytest tests/unit tests/integration`: **24 passed, 13 skipped, 0 failed.**
- Offline stub chain (`python -m app.chain`) canonical line unchanged —
  the deterministic airlock still green.
- A2A skill card live with **6 skills** at `/a2a/app/.well-known/agent-card.json`.

---

## Honest limitations (carried into Devpost "Challenges / What's next")

1. **Free-tier Vertex quota is the latency floor.** The full debate chain
   is minutes, not seconds, because of 429 back-off — not code. Dedicated
   throughput would collapse it to ~15–30 s.
2. **Fast-mode samples clauses/obligations** for interactive demos
   (`CURATOR_FAST_MAX_CLAUSES`, `CURATOR_FAST_MAX_OBLIGATIONS`). The full
   document is still ingested + persisted; the *debate* runs on a bounded
   sample unless fast-mode is unset.
3. **Master Direction is grounding, not yet a second decompose target.**
   The amendment is decomposed; the MD's 55 clauses are ingested and
   available to the Reflector's Spanner-Graph re-query, but the `map` step
   still scores coverage against the bank's policy corpus (mock in the
   public repo).
4. **Reconciler dedup edge cases** — 4/8 audit mismatches documented in
   `docs/eval_baselines/RECONCILER_AUDIT_2026-06-02.md`.
5. **Confidence is calibrated to lens agreement**, not eval pass rate.
6. **GEPA optimizer is staged** (`--algo=gepa` raises NotImplementedError);
   `SimplePromptOptimizer` is the production default and produced a real
   prompt delta for $0.84.
7. **RBI's RSS endpoint is broken**; discovery defaults to SEBI's feed
   (`CURATOR_RSS_FEEDS` env selects regulators; SEBI/RBI/IRDAI/EU-EBA/US-SEC
   registered).
8. **`_RUNS` is per-instance**, but completed runs persist to Spanner
   `pipeline_runs`, so `/impact` and `/demos` survive container
   scale-to-zero. `min-instances=1` is set during the judging window for
   no cold start.
9. **Optional bbb-corpus A2A bridge** is consume-only and **off by default**
   (`CURATOR_A2A_BEARER` unset) — it never crosses the IP wall in the public
   repo.

---

## What a judge can verify in 2 minutes

- `GET /demos` → two cached capital-adequacy results, instant.
- Open a cached result → obligations, coverage gaps, suggested edits,
  impact, **and** the Performance panel.
- `GET /a2a/app/.well-known/agent-card.json` → 6 A2A skills.
- `GET /cost` → live per-agent spend.
- Click **Re-run live** on a demo → watch the chain execute end-to-end.
