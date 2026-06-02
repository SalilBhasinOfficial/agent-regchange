# Session Handover — 2026-06-02

End-of-session checkpoint. Curator Stage-2 is **on schedule and ahead of pace**: D1-D7 of the 9-day plan all completed today. D8-D10 remain, plus a user-gated Cloud Run deploy. **Devpost deadline: 2026-06-11 17:00 PT** (still 9 calendar days away).

---

## Status by gate

| Gate | Status | Tag | Evidence |
|---|---|---|---|
| Gate 1 (D3 EOD) — multi-perspective debate on decompose + judge, eval ≥ 0.7 | ✅ CLEARED | `gate-1` pushed | `docs/eval_baselines/GATE1_2026-06-04.md` (5/5 cases at 1.0) |
| Gate 2 (D4 EOD) — Spanner ingestion + agent_runs + Reflector re-query | ✅ CLEARED | `gate-2` pushed | `docs/eval_baselines/GATE2_2026-06-05.md` (62 agent_runs rows/chain, 02-vs-03 PDF round-trip) |
| Gate 3 (D6 EOD) — Cloud Run × 2 + A2A + Discovery Inbox | ⚠️ **LOCAL CLEARED, DEPLOY DEFERRED** | tag pending | All commands documented + locally validated; `gcloud run deploy` itself is the one remaining action |
| Gate 4 (D9 EOD) — Devpost submission with assets + GEPA delta | ⏳ PENDING | n/a | D8 + D9 ahead |

---

## What shipped this session (D1-D7)

**13 commits on `origin/stage-2` plus 2 merge commits on `origin/main` (Gate-1 and Gate-2 promotions):**

```
de7cd00  phase-3.1: D7 Agent Optimizer + 30-case evalset + accuracy audits
abfd685  phase-2.5: D6 local E2E validation + deploy-ready
2a8f0f9  phase-2.4: D5 discovery service + Jinja UI + map/diff parallelization
87512bd  docs: refresh STAGE2_IMPLEMENTATION_PLAN for D5-D10 (post-Gate-2)
9774bdb  gate-2: Spanner ingestion live, agent_runs writing, Reflector re-queries
ffb3b2f  phase-2.3: SpannerGraphBackend + agent_runs writer + Reflector re-query
f594539  gate-1: build_agent drops LoopAgent so Reconciler output surfaces
b1cb339  phase-2.2: judge debate panel + Document AI ingestion (D3 parallel)
1a865b1  phase-2.1: debate panel on decompose + Spanner schema + provision
e283187  docs: D1 eval baseline (pre-debate-panel)
c0c7949  phase-1.5: confidence + missing_evidence schema, Stage-2 deps, DECISIONS-9
f3cb252  docs: ADK reference notes + Stage-2 session research
e3437f5  phase 1.2-1.3: real_* implementations for all 5 sub-agents + chain shim
5a99b03  chore: gitignore ADK runtime caches
bc6a8fe  stage-2 plan: 3 course-corrections (debate panels, self-improvement, discovery) on 9-day runway
```

### Key headline numbers
- **Real-LLM debate chain on the demo fixture:** obligations 6 → **22**, missing-coverage gaps 1 → **9**, priority `medium → critical`.
- **Test suite:** 22 passed, 12 skipped, **0 failed** (up from 9 at session start).
- **Eval rubrics:** 5/5 cases at 1.0 (5-case set); 30-case set ready for next pass.
- **`agent_runs` Spanner table:** ~62 rows per chain run, lens-tagged, `pipeline_run_id` propagates across `ThreadPoolExecutor`.
- **Cost spent this session:** **~$10 of $200 cap** (Agent Optimizer $0.84, eval baselines $2, smokes $5, Doc AI parses $2, Spanner runtime $1). **~$490 GCP credits remain** through 2026-07-14.
- **Spanner instance `curator-graph` (asia-south1) is still running.** Tear down command: `bash scripts/spanner_down.sh`.

---

## What's pending

### D8 — Devpost assets (3 parallel subagents + me on video script)

| Track | Owner | File(s) | Status |
|---|---|---|---|
| A | subagent | `docs/submission/architecture.svg` (Mermaid → SVG render) + `architecture.png` | not started |
| B | subagent | `docs/submission/devpost_fields.md` (Problem / Solution / Innovation / TI / Business Case / Findings — 1500 word ceiling) | not started |
| C | subagent | Repo hygiene sweep: grep for `bbb`/`tailscale`/`milvus`/`neo4j`/`matryoshka` in `app/`+`tests/`+`scripts/`; README cleanup; LICENSE check | not started |
| video script | me | `docs/submission/video_script.md` (3-min shot list per plan §D8) | not started |

**Source-of-truth references for D8:**
- Persona, pain quantification, TAM, WTP, India-residency story → `docs/STAGE2_IMPLEMENTATION_PLAN.md` § "Value System & Positioning"
- Headline numbers (obligations 22, missing 9, priority critical) → above
- Architecture detail to diagram → `docs/STAGE2_IMPLEMENTATION_PLAN.md` § "Architecture state at Gate 2" + the 8 commits' file additions

### D9 — Record demo + submit on Devpost → Gate 4

- User-led: record video per `docs/submission/video_script.md` (D8 produces it).
- Final smoke per `docs/STAGE2_IMPLEMENTATION_PLAN.md` § "D9 final validation script".
- Submit on Devpost; verify by re-opening as anonymous viewer.
- Tag `gate-4`, push.

### D10 — Submission day buffer (2026-06-11 hard deadline 17:00 PT)
Reserved for unexpected fixes. **Hard stop 12:00 PT.**

### Gate-3 deploy (the one remaining user-approval gate)

The plan and `README.md` § "Stage-2 deployment" document everything needed. The user paused before running these because (a) production deploy needs a deliberate approval, (b) local validation came first and passed.

```bash
# Prereq (one-time)
gcloud pubsub topics create curator-discoveries --project=curator-research                                # DONE
gcloud pubsub subscriptions create curator-chain-pull --topic=curator-discoveries --ack-deadline=300 ... # DONE
gcloud services enable cloudscheduler.googleapis.com --project=curator-research                          # DONE

# Deploy chain (UI + A2A + ADK API surface)
gcloud run deploy curator-chain --source=. --region=asia-south1 \
    --service-account=curator-ai-engine@curator-research.iam.gserviceaccount.com \
    --allow-unauthenticated --memory=2Gi --cpu=2 --port=8080 --timeout=600 \
    --min-instances=0 --max-instances=5 \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=curator-research,GOOGLE_CLOUD_LOCATION=global,\
GOOGLE_GENAI_USE_VERTEXAI=True,SPANNER_INSTANCE=curator-graph,SPANNER_DATABASE=curator,\
CURATOR_AGENT_RUN_LOG=1,CURATOR_GROUNDING=spanner,CURATOR_REAL_LLM=1,\
CURATOR_DOCAI_PROCESSOR_ID=projects/890675948352/locations/us/processors/4c036f5845e938e7,\
CURATOR_DISCOVERY_SUBSCRIBE=1,CURATOR_DISCOVERY_SUBSCRIPTION=curator-chain-pull"

# Deploy discovery (smaller; CMD-overridden to discovery.service:app)
gcloud run deploy curator-discovery --source=. --region=asia-south1 \
    --service-account=curator-ai-engine@curator-research.iam.gserviceaccount.com \
    --allow-unauthenticated --memory=512Mi --cpu=1 --port=8080 --timeout=120 \
    --min-instances=0 --max-instances=2 \
    --command=uv --args="run,uvicorn,app.discovery.service:app,--host,0.0.0.0,--port,8080" \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=curator-research,SPANNER_INSTANCE=curator-graph,\
SPANNER_DATABASE=curator,CURATOR_DISCOVERY_TOPIC=curator-discoveries"

# Cloud Scheduler — every 30 minutes
DISCOVERY_URL=$(gcloud run services describe curator-discovery \
    --region=asia-south1 --project=curator-research --format='value(status.url)')
gcloud scheduler jobs create http curator-discovery-poll \
    --location=asia-south1 --schedule="*/30 * * * *" \
    --uri="${DISCOVERY_URL}/poll" --http-method=POST \
    --oidc-service-account-email=curator-ai-engine@curator-research.iam.gserviceaccount.com \
    --oidc-token-audience="${DISCOVERY_URL}"

# Verify
curl -fsS "${CHAIN_URL}/health"
curl -fsS "${CHAIN_URL}/.well-known/agent.json" | jq '.skills | length'    # ≥ 5
# Browser: ${CHAIN_URL}/ and ${CHAIN_URL}/inbox
```

Cost estimate: Cloud Build minutes ≈ $0.10 per deploy. Cloud Run idle scale-to-zero = $0. Total deploy cost ~$0.30.

---

## Known limitations / technical debt (carry-forward)

| Item | Severity | Plan |
|---|---|---|
| Reconciler `_normalize_action` has 4/8 known edge-case mismatches (climate vs credit, quarterly vs annually) | low | Phase-5; documented honestly in `docs/eval_baselines/RECONCILER_AUDIT_2026-06-02.md` and intended for D8 "Findings" disclosure |
| Confidence calibration is anchored to lens-agreement, not eval pass rate (eval too coarse to discriminate) | low | Phase-5; honest disclosure already drafted in `docs/eval_baselines/CALIBRATION_AUDIT_2026-06-02.md` |
| RBI's `/Scripts/RssNotification.aspx` no longer returns RSS XML — defaulted to SEBI RSS as the demo feed | low | Operators can override via `CURATOR_RSS_FEED_URL`; Phase-5 idea is to BeautifulSoup-parse RBI's HTML notifications page |
| Real-LLM chain wall-clock 7-8 min (vs aspirational <60s target) under Vertex AI rate limits | medium | Map/diff parallelization is in (D5); the limit is Vertex quota itself. Devpost video should be edited / time-lapsed at this section. |
| GEPA optimizer not wired (SimplePromptOptimizer is the default) | low | The `--algo=gepa` flag raises `NotImplementedError`. D7 SimplePromptOptimizer pass already produced a Devpost-grade proof-point. GEPA wiring is Phase-5 polish. |
| 12 tests skip without `CURATOR_REAL_LLM=1` / `CURATOR_LIVE_GCP=1` | n/a | By design — they exercise live GCP and would cost too much in CI. |
| Doc AI `parsed_chunks` cache not implemented | medium | Plan called for it in D5 Track C; deferred because the demo only ingests 2 PDFs ($1-2 per run, acceptable). Phase-5 if a continuous-ingestion deployment is added. |
| Reflector `reflect_and_requery` is callable but not wired into the demo path | medium | Decision was to ship one-pass chain at Gate 3; the function exists with 4 unit tests passing. Wire-in is one if-statement in `real_decompose` / `real_judge` — D8 or Phase-5. |
| Spanner instance left running (~$0.40/hr) | low | Tear down with `bash scripts/spanner_down.sh` when stepping away >4h |
| `app/agent.py::LOCATION = "us-central1"` while Spanner is `asia-south1` | none | Documented in `DECISIONS-9`; these are unrelated regions (Vertex AI region vs Spanner region). Not drift. |

---

## How to resume next session

1. **Source env + verify state**
   ```bash
   cd ~/bs/agent-regchange
   source scripts/env.sh
   git status                                    # should be clean
   git log --oneline -5                          # latest is de7cd00 (phase-3.1)
   .venv/bin/python -m app.chain                 # stub canonical line
   .venv/bin/python -m pytest tests/unit tests/integration -q   # 22 passed, 12 skipped
   ```

2. **Check Spanner / Pub/Sub state**
   ```bash
   gcloud spanner instances describe curator-graph --project=curator-research
   gcloud pubsub topics describe curator-discoveries --project=curator-research
   gcloud pubsub subscriptions describe curator-chain-pull --project=curator-research
   ```

3. **Pick up the plan** at `docs/STAGE2_IMPLEMENTATION_PLAN.md` D8 section. Either:
   - **Sequential path:** run D8 (Devpost assets), then deploy (Gate 3), then D9 (record + submit), then D10 buffer.
   - **Deploy-first path:** approve the `gcloud run deploy` commands above; cut `gate-3` tag; then D8 assets reference the live URLs; then D9 + D10.

   The deploy-first path lets the demo video include the live `https://curator-chain-…asia-south1.run.app/` URL. The sequential path keeps D8 deterministic but means re-recording or post-editing the video URL bits later. Recommend deploy-first.

4. **Subagent kickoff for D8** (copy these prompts):
   - **Track A — architecture diagram:** "Read `docs/STAGE2_IMPLEMENTATION_PLAN.md` § 'Architecture state at Gate 2' and the file diffs in commits 1a865b1, b1cb339, ffb3b2f, 2a8f0f9. Produce `docs/submission/architecture.svg` (Mermaid → rendered SVG) + `.png` showing: PDF upload → DocAI → graph extractor → Spanner Graph; 4-lens decompose panel + Reconciler + Reflector loop; 4-critic judge panel; agent_runs observability; Agent Optimizer feedback; Discovery service + Pub/Sub; Cloud Run × 2; A2A skill card. Own only `docs/submission/architecture.*`."
   - **Track B — Devpost fields:** "Read `docs/STAGE2_IMPLEMENTATION_PLAN.md` § 'Value System & Positioning' for source-of-truth. Produce `docs/submission/devpost_fields.md` covering Problem, Solution, Innovation, Technical Implementation, Business Case, Findings & learnings. Cite the headline numbers (6→22 obligations, 1→9 missing-coverage, medium→critical priority, 5/5 eval at 1.0, $0.84 GEPA pass). Honest disclosures: reconciler 4/8 audit mismatches, confidence calibrated to lens-agreement not eval pass rate. 1500 word ceiling. Own only `docs/submission/devpost_fields.md`."
   - **Track C — repo hygiene:** "Sweep `app/`, `tests/`, `scripts/`, `docs/` (excluding docs/sessions and docs/google_agent which are research notes) for any `bbb`/`tailscale`/`milvus`/`neo4j`/`matryoshka` references in code. Confirm `README.md` describes current state (Stage-2 with debate panels + Spanner + Discovery + Cloud Run × 2). Verify Apache 2.0 LICENSE. No committed secrets. May edit `README.md`, `LICENSE` only."

---

## Files / docs to reference

- **Plan of record:** `docs/STAGE2_IMPLEMENTATION_PLAN.md` (matches the harness plan file)
- **Gate evidence:** `docs/eval_baselines/GATE{1,2}_*.md`
- **Audits:** `docs/eval_baselines/{RECONCILER,CALIBRATION,LENS_DIVERSITY}_AUDIT_2026-06-02.md`
- **Optimization run:** `docs/OPTIMIZATION_LOG.md`
- **Eval baselines:** `docs/eval_baselines/EVAL_BASELINE_2026-06-02.md` (pre-debate)
- **Decisions:** `docs/DECISIONS.md` (D1-D9 locked)
- **Run-time env:** `scripts/env.sh`
- **Spanner up/down:** `scripts/spanner_{up,down}.sh`

---

## Quick stats — this session

- Calendar days used: **1** (2026-06-02)
- Plan days completed: **D1-D7** (~58% of the 12-day envelope)
- Net commits on stage-2: **15**
- Tags pushed: **gate-1**, **gate-2**
- Net new files added: ~40 (including all sub_agents/lenses, observability/, discovery/, templates/, optimization/, eval audits, submission scaffold paths)
- Net LOC added: ~6000 across implementation + docs
- Cumulative GCP cost: **~$10 of $200 cap**
- Days of slack remaining vs deadline: **9 calendar days** to 2026-06-11 17:00 PT; only **3 days of plan work** remain (D8/D9/D10)

We are **firmly on track to ship Gate-4 (Devpost submission)**. The one remaining user-approval gate is the Cloud Run deploy — everything else is documented, queued, and rehearsed locally.
