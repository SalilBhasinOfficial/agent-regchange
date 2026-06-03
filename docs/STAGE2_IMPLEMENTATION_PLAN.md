# Curator Stage-2 Win Plan — 3 Course-Corrections, 9-Day Runway

## Context

**Why this rewrite.** The original `docs/STAGE2_IMPLEMENTATION_PLAN.md` was anchored against an 18-day window and a linear 5-step ADK chain. Two things changed:

1. **Phase 1 is already done.** All five `real_*` sub-agents (`real_decompose`, `real_map`, `real_diff`, `real_judge`, `real_qna`) are committed in `app/sub_agents/*.py`. `app/runners.py::run_agent` has 6-retry exponential backoff and schema validation. `app/chain.py` shims real vs stub via `CURATOR_REAL_LLM`. The original Phase 1's prompt-quality iteration is the only carryover.
2. **Submission deadline moved to 2026-06-11 17:00 PT** (Devpost extension email confirmed). Today is 2026-06-02, leaving **~9 working days** — between the original 17-day plan and a 3-day crunch.

**What we are adding.** Three high-leverage course-corrections approved by the user, each aimed at a distinct hackathon scoring axis and each producing a clean reference implementation that ports back into the bbb production stack (`services/curator/`, `services/bija/brainstorm/`, the 31 LLM-feedback-point pipeline):

1. **Multi-perspective debate + reflection** — replace the single-shot `decompose_agent` and `judge_agent` with a `ParallelAgent` of four stakeholder lenses (banker / compliance officer / auditor / customer-protection) wrapped in a `LoopAgent(max_iterations=3)` that runs Reconciler → Reflector. Hits the **Innovation** axis. Lenses and reconciliation patterns are directly portable to `services/bija/brainstorm/orchestrator.py`.
2. **Self-improving loop** — every sub-agent emits `(output, confidence, missing_evidence[])`. Below-threshold confidence triggers a Reflector that re-queries Spanner Graph. Every real-LLM call logs to a Spanner `agent_runs` table. `google.adk.optimization.GEPARootAgentPromptOptimizer` consumes the log to propose prompt deltas; `google.adk.evaluation.simulation` expands the evalset. Hits the **Technical Implementation** axis. Closes 6 open `enrich-p0/p1` todos in bbb's pipeline via the reference implementation.
3. **Continuous-discovery agent** — separate Cloud Run service polling RBI's public RSS (`https://www.rbi.org.in/Scripts/RssNotification.aspx`) on a Cloud Scheduler cron, deduping via Spanner, publishing new items to a Pub/Sub topic that triggers the chain. Hits the **Business Case** and **Demo** axes (always-on autonomy is what B2B compliance teams actually pay for). The clean A2A discovery surface is exactly what bbb needs to unbundle Curator as a standalone hosted product.

**Verified ground truth from exploration.**

- ADK 1.34.0 ships `ParallelAgent`, `LoopAgent`, `SequentialAgent` natively (`from google.adk.agents import …`). `to_a2a` auto-builds skill cards from `sub_agents` (`google.adk.a2a.utils.agent_to_a2a`).
- `google.adk.optimization.GEPARootAgentPromptOptimizer` exists (not exported from `__init__.py` — must import by full module path); requires the `gepa` PyPI package. `SimplePromptOptimizer` is the fallback. `google.adk.evaluation.simulation` is real with `llm_backed_user_simulator`.
- `google-cloud-scheduler` and `google-cloud-documentai` are **not** installed; must be added in `pyproject.toml`.
- Spanner Graph is plain `CREATE PROPERTY GRAPH` DDL via `database.update_ddl(...)` — no special SDK.
- `app/agent.py::LOCATION = "us-central1"` (Vertex AI region) and DECISIONS-6's `asia-south1` (Spanner) are unrelated — keep both, document as DECISIONS-9.
- `PolicyMatch.confidence` already exists in `app/models.py:121`; extend the pattern to the other 4 output models.
- `inout/*.html.json` / `*.html.md` sidecars are present for all 4 RBI PDFs — usable to test the chain end-to-end *before* Document AI is wired, removing a serial dependency.

**Outcome.** By 2026-06-11 17:00 PT: a deployed Cloud Run + A2A submission with multi-perspective debate on decompose and judge, a self-improvement loop with one demonstrable Agent-Optimizer prompt evolution, a continuous-discovery agent visible in a Discovery Inbox UI, and a Devpost submission with architecture diagram, written fields, and demo video. All four Track-3 mandates met. Offline `python -m app.chain` (stub path) green throughout.

---

## D1-D4 Retrospective (refresh anchored at 2026-06-02 EOD)

**Schedule:** D1-D4 all completed in **one calendar day** (2026-06-02). We are **~3 days ahead** of the original D5-on-2026-06-06 calendar. Submission deadline holds at 2026-06-11 17:00 PT.

**State at end of D4 (Gate 2 cleared):**
- All 8 commits since session start pushed to `origin/stage-2` and merged to `origin/main` via two `--no-ff` merges (`7dd9399`, `79db1d1`). Tags `gate-1`, `gate-2` pushed.
- Real-LLM debate-panel chain on the demo fixture: **6 → 21 obligations**, **1 → 7 missing-coverage gaps**, priority **medium → critical**. The fan-out signature moment works.
- ADK eval: **5/5 cases at 1.0 across every rubric** post-Gate-1 fix.
- Spanner Graph live in `asia-south1`; `agent_runs` table populating (62 rows per chain run); `query_graph_neighborhood` round-trips.
- Doc AI Layout Parser parses the 02 PDF cleanly via pre-provisioned processor `4c036f5845e938e7`.
- Total cost so far: **~$7 of $200 cap** (3.5%). $493 of GCP credits still available.

**Findings from D4-EOD audit (raised by exploration agents):**

*Speed bottlenecks discovered:*
- `app/sub_agents/map_.py::real_map` runs **sequentially** over obligations (~20+ serial Gemini calls per chain). A `ThreadPoolExecutor(max_workers=8)` lift = 2-3× wall-clock improvement.
- `app/sub_agents/diff.py::real_diff` same shape (~10-19 serial calls). Same fix.
- `app/runners.py::_run_in_fresh_loop` spawns a fresh OS thread per call. Acceptable but worth documenting.
- Doc AI re-parses every PDF on every pipeline run ($10/1k pages). Adding a Spanner-keyed `parsed_chunks` cache eliminates re-parse cost.

*Accuracy / quality gaps:*
- `app/sub_agents/reconciler.py::_normalize_action` has an **over-dedup risk** — actions like "maintain climate risk buffer" and "maintain credit risk buffer" both collapse to "maintain risk buffer" after token stemming. The `source_clause_id` part of the key partially mitigates, but two clauses each producing similar actions could still merge.
- Reflector is **wired but inert**: `reflect()` is called from `real_decompose`/`real_judge`, but `decision.escalate=True` always (per D2 stub), so re-query never fires. `reflect_and_requery` exists and is unit-tested but **not called from the demo path**. Wiring this is one of the biggest accuracy wins.
- `agent_runs.prompt_hash` is sha256 of user_text only — not the agent's instruction prompt. Two critic agents with different preambles emit identical hashes. GEPA grouping will be loose.
- Confidence calibration (`agreement_factor = 0.6 + 0.1 * n_lenses`) is uncalibrated. Stubs hardcode 1.0 (overconfident in eval).

*Cloud Run readiness gaps (D6 must fix before deploy):*
- `deployment/terraform/single-project/service.tf` is missing **6 env vars** the runtime needs: `CURATOR_DOCAI_PROCESSOR_ID`, `SPANNER_INSTANCE`, `SPANNER_DATABASE`, `GOOGLE_CLOUD_PROJECT`, `CURATOR_AGENT_RUN_LOG`, `CURATOR_GROUNDING`.
- Container image in `service.tf` is the hello-world placeholder. Must rebuild + push the Curator image before deploy.
- Service-account `app_sa_roles` needs verification for `roles/spanner.client`, `roles/documentai.apiUser`, `roles/pubsub.publisher` (D5 needs), `roles/cloudscheduler.serviceAgent`.

*Test failures already known and triaged:*
- `tests/integration/test_server_e2e.py` 3 failures: `/run_sse` 404s and `/feedback` (200 passes). The 404s expect a Jinja UI that D5 will build. Decision: extend the tests against the D5 UI rather than delete; one new endpoint test per UI route.

**Competitive positioning (from competition intel):**
- Track-3 Build has 27 submitted; ~1 in Indian BFSI vertical (ARIA — KYC automation, single-workflow). Track-3 Refactor has 1 submitted (unrelated domain).
- ARIA's gap: single-document workflow vs Curator's **comparative + decompose-and-map** intelligence. The Devpost write-up will explicitly contrast.
- Devpost scoring weights: **Technical Implementation 30%, Business Case 30%, Innovation 20%, Demo 20%**. The current trajectory hits all four.
- ~$500 (₹45K) GCP credit remaining — plenty for D5-D10 Cloud Run + Spanner + DocAI burn.

**Value-system inputs (from Aidni / BBB pitch material — IP-clean reframing):**
- Customer: Chief Compliance Officer at Indian commercial bank / SEBI PMS firm / IRDAI insurer.
- Regulator volume: ~100-120 RBI circulars/yr, ~60-80 SEBI, ~40-50 IRDAI; ~30% of each triggers internal policy edits.
- Current workflow: **2-4 weeks of compliance-officer time per material amendment**. Curator targets <10 minutes (proposal-only; human approves).
- Willingness to pay: ₹5-20 lakhs/year per institution per regulator subscription tier.
- TAM: ~40 RBI commercial banks, 500+ SEBI PMS, 100+ IRDAI insurers, 5000+ secondary mid-cap depositories.
- These framings go into D8 Devpost written fields verbatim (no BBB-proprietary internals leak).

---

## Day-by-day calendar (D1 = 2026-06-02 Mon → D10 = 2026-06-11 Wed)

**Schedule reality:** D1-D4 completed 2026-06-02. Plan against 5 remaining calendar days (D5-D9) plus D10 buffer. We have slack — use it to address the findings above before Gate 3, not for scope creep.

### D1 — Mon 2026-06-02 — Schema freeze + plan mirror
**Owner: me, sequential.**
- **First action of execution:** mirror this plan into `docs/STAGE2_IMPLEMENTATION_PLAN.md` (replacing the older version) so the repo and harness agree. Tag the previous file at `docs/STAGE2_IMPLEMENTATION_PLAN.v1.md` for history.
- Add `confidence: float` and `missing_evidence: list[str]` fields to `Obligation`, `PolicyDiff`, `ImpactSummary`, `QnATurn` in `app/models.py` (matches existing `PolicyMatch.confidence`).
- Thread these fields through every `real_*` function and `stub_*` function (stubs hard-code `confidence=1.0`, `missing_evidence=[]`).
- Add `confidence_log: dict[str, float]` and `reflection_count: int` to `AgentState`.
- Capture baseline rubric scores: `CURATOR_REAL_LLM=1 .venv/bin/agents-cli eval run` — save to `docs/EVAL_BASELINE_2026-06-02.md`.
- Add `google-cloud-scheduler`, `google-cloud-documentai`, `google-cloud-pubsub` (verify version), `gepa` to `pyproject.toml`. `uv sync`.
- Add DECISIONS-9 to `docs/DECISIONS.md` documenting the `us-central1` (Vertex) vs `asia-south1` (Spanner) split.
- **Regression fence:** `python -m app.chain` matches canonical summary line.
- **Commit:** `phase-1.5: schema for confidence + missing_evidence; deps for stage-2`.

### D2 — Tue 2026-06-03 — Debate panel for decompose + Spanner up (PARALLEL)
**Track A (me, sequential, primary work):**
- New `app/sub_agents/lenses.py` — 4 `Agent` factories (`banker_lens`, `compliance_lens`, `auditor_lens`, `customer_protect_lens`) sharing the decompose instruction with a perspective preamble each.
- New `app/sub_agents/reconciler.py` — `Reconciler` agent that merges 4 obligation lists, dedupes by `(source_clause_id, action)`, records per-lens dissent in `Obligation.missing_evidence`.
- New `app/sub_agents/reflector.py` — `Reflector` agent that triggers when aggregate confidence < 0.6; emits queries for Spanner Graph re-fetch (D4 wires the actual Spanner call; D2 lands a stub that just returns "no extra context").
- Wire it: `decompose_panel = SequentialAgent(sub_agents=[ParallelAgent(name="decompose_panel", sub_agents=[…4 lenses]), Reconciler])`. Wrap in `LoopAgent(max_iterations=3, sub_agents=[decompose_panel, Reflector])`.
- Update `app/sub_agents/decompose.py::build_agent()` to return the loop when `CURATOR_REAL_LLM=1`; stub path unchanged.
- Update `app/agent.py::_build_root_agent()` so `sub_agents` includes the new looped decompose agent.
- 50-line smoke harness `tests/integration/test_parallel_smoke.py` proving `ParallelAgent` of 4 trivial sub-agents resolves under `Runner.run_async`. Skip if `CURATOR_REAL_LLM=0`. **De-risks the entire approach in <1 hour.** If broken, fall back to `asyncio.gather` of 4 manual `run_agent` calls.

**Track B (me, parallel, infra):**
- Run `scripts/spanner_up.sh` (asia-south1, 100 PUs).
- Write `app/ingest/spanner_schema.sql` — DDL for `documents`, `clauses`, `obligations`, `policy_sections`, `agent_runs(run_id PK, ts, agent_name, prompt_hash, input_json, output_json, confidence, latency_ms, cost_usd_estimated, eval_score nullable, parent_run_id nullable, lens nullable)`, `discovered_items(item_hash PK, source, url, title, published_at, first_seen, processed_at nullable, agent_run_id nullable)`. Apply via `database.update_ddl([...])`.

**Regression:** stub chain green. Confidence emitted from real-LLM path.
**Commit:** `phase-2.1: debate panel for decompose; spanner schema + provision`.

### D3 — Wed 2026-06-04 — Debate panel for judge + DocAI ingestion (PARALLEL)
**Track A — Subagent (general-purpose) on judge:**
- Brief: "Mirror the decompose-panel pattern in `app/sub_agents/judge.py`. Create `app/sub_agents/judge_panel.py` with 4 critic lenses (impact, ICAAP, Pillar-3, ops-risk). Reconciler merges into single `ImpactSummary`. Reflector triggers on confidence < 0.6. Own only `app/sub_agents/judge.py`, `app/sub_agents/judge_panel.py`, `tests/integration/test_judge_panel.py`. Do not touch decompose files, models, runners, grounding."
- File ownership: `app/sub_agents/judge_panel.py`, `app/sub_agents/judge.py` (panel wiring only).

**Track B — Subagent on Document AI ingestion:**
- Brief: "Implement `app/ingest/docai.py::parse_pdf(pdf_path, processor_id, location='us') -> list[ChunkedSection]` using `google-cloud-documentai` Layout Parser. Output preserves `chunk.text`, `chunk.layout_type`, `chunk.page_span`. Hard skip with `pytest.skip` when `CURATOR_LIVE_GCP=0`. Validate end-to-end against `data/fixtures/source_pdfs/02_second_amendment*.pdf`. Own only `app/ingest/docai.py` and its test."
- File ownership: `app/ingest/docai.py`, `tests/integration/test_docai.py`.

**Me (sequential, supervisory):**
- Review subagent diffs; ensure file ownership respected (`git diff --stat`).
- Begin work on `app/ingest/graph_extractor.py` — Gemini structured-output entity/relation extraction. (Continued D4.)
- Smoke: chain end-to-end on **pre-parsed `inout/02_*.html.json` sidecar** (skipping Doc AI) confirms the multi-perspective decompose AND judge work on real text without needing live Document AI. This unblocks D4 even if Doc AI subagent slips.

**Gate 1 (EOD):** multi-perspective debate working on both decompose and judge under real-LLM; confidence/missing_evidence flowing; offline stub chain green; eval ≥0.7 on all 5 rubrics. **Tag `gate-1`. Push.**

### D4 — Thu 2026-06-05 — SpannerGraphBackend + agent_runs writer + graph extractor finish
**Owner: me, sequential.**
- Finish `app/ingest/graph_extractor.py` from D3.
- Implement `app/grounding.py::SpannerGraphBackend(GroundingBackend)` replacing the `VertexRagBackend` stub. Methods: `ingest_document(pdf_path, doc_id, namespace) -> None`, `search_master_direction`, `get_master_direction_text`, `get_amendment_text`, `load_bank_policies`, plus the new `query_graph_neighborhood(node_id, depth=2) -> list[GraphNode]` used by the Reflector.
- Factory switch in `app/grounding.py` via `CURATOR_GROUNDING={mock,spanner}` env var.
- New `app/observability/run_log.py::log_run(agent_name, lens, payload, output, confidence, latency_ms, parent_run_id=None)` — async Spanner insert into `agent_runs`. Best-effort (failures logged, never raise).
- Wire `log_run` into `app/runners.py::run_agent` — one call per sub-agent invocation, with `lens` populated from kwargs.
- Wire `Reflector` (D2 stub) to call `SpannerGraphBackend.query_graph_neighborhood` for low-confidence items.
- `app/ingest/pipeline.py::ingest_two_pdfs(pdf_a, pdf_b, namespace) -> AgentState` orchestrating DocAI → graph extractor → Spanner write.
- Smoke: `02` vs `03` end-to-end through Spanner → debated chain → ImpactSummary.

**Gate 2 (EOD):** Spanner live; `agent_runs` populating; reflector re-querying Spanner on injected low-confidence; offline regression green. **Tag `gate-2`. Push.**

### D5 — Discovery service + UI + speed/accuracy lifts (3-track parallel)

**Three parallel tracks** so the ~3-day calendar slack we banked gets reinvested in the quality lifts, not idle.

**Track A — Discovery service subagent.** Brief unchanged from v2:
- `app/discovery/{rss_poller,dedupe,publisher,service,subscriber}.py` + `deployment/discovery/scheduler.yaml`.
- Polls `https://www.rbi.org.in/Scripts/RssNotification.aspx` via `feedparser`; dedupes via Spanner `discovered_items`; publishes to Pub/Sub topic `curator-discoveries`; `/poll` endpoint for Cloud Scheduler; `/health` standard.
- Standalone Cloud Run service — never imports the chain code; resilience > DRY.
- Subscriber inside the chain service listens on `curator-discoveries`, triggers the chain on each new item, writes `agent_run_id` back to `discovered_items`.
- **NEW:** subscriber must call `begin_pipeline_run()` so `agent_runs` rows are linked to the discovery event.
- File ownership: `app/discovery/*`, `deployment/discovery/*`, `tests/integration/test_discovery.py`.

**Track B — FastAPI/Jinja UI (me).** Brief unchanged from v2:
- Extend `app/fast_api_app.py` with Jinja templates + 5 routes (upload / analyse / inbox / impact / qna).
- `/inbox` queries `discovered_items LEFT JOIN agent_runs` for the auto-discovery cards.
- HTMX polling for in-flight runs.
- **NEW (closes pre-existing test failures):** wire `/run_sse` (the streaming chat endpoint that `test_server_e2e.py` already tests) by piping ADK's `runner.run_async` events through Server-Sent Events. The 3 currently-failing tests should turn green, not be deleted.
- File ownership: `app/fast_api_app.py`, `app/templates/*.html`, `app/discovery/subscriber.py` (sole exception to Track A's lane).

**Track C — Speed + accuracy lifts (me, sequential, after Track B's templates land).** Concrete optimization work the audit surfaced:

  1. **Parallelize `map` and `diff`** — convert `real_map` and `real_diff` to use `ThreadPoolExecutor(max_workers=8)` mirroring `decompose._run_panel`. Each obligation/match becomes one concurrent job. Target: chain wall-clock drops from ~120s to ~50s. Files: `app/sub_agents/map_.py`, `app/sub_agents/diff.py`. Each call retains `log_run` (already in `run_agent`).
  2. **Wire `reflect_and_requery` into the demo path** — replace `decision = reflect(merged)` in `real_decompose` and `real_judge` with `decision, extra = reflect_and_requery(merged, namespace=…)`. When `extra` is non-empty AND aggregate confidence < 0.6, re-run the panel ONCE with the extra Spanner context appended to the prompt. Bounded by a single re-run to cap cost. Files: `app/sub_agents/decompose.py`, `app/sub_agents/judge.py`. Test: extend `tests/integration/test_reflector_requery.py` with a Reflector-loop integration test that forces low confidence on a synthetic input.
  3. **Improve `prompt_hash` for GEPA grouping** — change `app/observability/run_log.py::log_run` to hash `(agent_name, instruction_prompt, user_text)` instead of just `user_text`. Pass `instruction` through `run_agent` (small kwarg). GEPA's per-prompt grouping becomes correct.
  4. **Add Doc AI parse cache** — `app/ingest/docai.py` checks Spanner for `parsed_chunks` keyed on PDF sha256 before parsing. New table `parsed_chunks(pdf_sha256 PK, doc_id, chunk_json, parsed_at)` added to `spanner_schema.sql` (schema migration via `gcloud spanner databases ddl update`).

**Regression:** stub chain green. Real chain green on `02` vs `03`. Discovery service ingests at least one item locally (mocked RSS feed for the test). Map/diff timing instrumented (log wall-clock before and after parallelization).
**Commits:** `phase-2.3a: discovery service + inbox UI` and `phase-2.3b: speed lifts (map/diff parallel, doc-ai cache) + reflector wiring`.

### D6 — Cloud Run deploy x2 + Terraform fixes → Gate 3
**Owner: me, sequential (user approval gate before each deploy).**

**D6 morning — Terraform + IAM fixes** (must land before deploy):
- Edit `deployment/terraform/single-project/service.tf` to inject the 6 missing env vars: `CURATOR_DOCAI_PROCESSOR_ID` (Doc AI processor resource name), `SPANNER_INSTANCE=curator-graph`, `SPANNER_DATABASE=curator`, `GOOGLE_CLOUD_PROJECT=${var.project_id}`, `CURATOR_AGENT_RUN_LOG=1`, `CURATOR_GROUNDING=spanner`. Replace the placeholder container image with the actual Curator image registry path (rebuilt at deploy time by `adk deploy`).
- Edit `variables.tf` `app_sa_roles` to include `roles/spanner.client`, `roles/documentai.apiUser`, `roles/pubsub.publisher` (chain-service subscriber), `roles/pubsub.subscriber`, `roles/cloudscheduler.serviceAgent` (discovery service caller).
- `agents-cli infra single-project` to apply Terraform if not already done; record outputs.

**D6 deploy — two Cloud Run services:**
- Deploy 1: `adk deploy cloud_run --service_name=curator-chain --project=curator-research --region=asia-south1 --trace_to_cloud --otel_to_cloud --with_ui --a2a --service_account=curator-ai-engine@curator-research.iam.gserviceaccount.com .`
- Deploy 2: `curator-discovery` — same project/region/SA, minus `--with_ui --a2a`. Smaller resource profile.
- Cloud Scheduler job: `gcloud scheduler jobs create http curator-discovery-poll --schedule="*/30 * * * *" --uri="https://<discovery-url>/poll" --oidc-service-account=…`.
- Pub/Sub topic `curator-discoveries` provisioned + subscription `curator-chain-pull` for the chain service subscriber.

**D6 verification — full end-to-end dry-run:**
- `curl https://<chain-url>/.well-known/agent.json | jq '.skills | length'` → expect 6 (decompose-panel, map, diff, judge-panel, qna, discovery.poll-as-A2A-skill if surfaced via discovery service's own card).
- `curl https://<chain-url>/health` and `curl https://<discovery-url>/health` both 200.
- Browser dry-run #1: open chain `/inbox` → verify at least 1 auto-discovered item from the live RSS poll (or seed one via direct Spanner insert if RSS is empty).
- Browser dry-run #2: upload 02 + 03 PDFs through chain `/` → full debated obligation list + ImpactSummary visible + Q&A turn works.
- A2A inspector (`tools/a2a-inspector/`) points at chain URL → enumerates 5-6 skills cleanly. Hand-write `agent.json` if auto-card is incomplete.
- Cloud Trace dashboard renders the fan-out spans (4 lenses → reconciler → reflector). Capture a screenshot for D8 Devpost asset.
- README addendum with deploy steps + Cloud Trace dashboard URL.

**Gate 3 — SUBMITTABLE FLOOR (EOD):**
- Deployed Cloud Run URLs (chain + discovery) both healthy.
- A2A-discoverable, 5-6 skills exposed.
- Gemini reasoning, B2B, Cloud Run, A2A — all four Track-3 mandates met.
- Judge can: (a) upload 2 PDFs via UI → full debated chain output; (b) open Inbox → see auto-discovered RBI items processed by the chain.
- Offline `python -m app.chain` green.
- All `test_server_e2e.py` tests pass (D5 closed the 404 gaps).
- **Tag `gate-3`. Push. Merge stage-2 → main.** Project is submittable from this point regardless of what slips next.

### D7 — Agent Optimizer + Simulation eval expansion + accuracy audits (PARALLEL)

**Track A — Simulation eval expansion (subagent):**
- Brief: "Use `google.adk.evaluation.simulation.llm_backed_user_simulator` with `pre_built_personas` to generate **25** new evalset cases (revised up from 15) targeting fan-out depth (8 cases), multi-hop Q&A (5), downstream-effect detection (5), contradictory-coverage (4), stale-policy (3). Append to `tests/eval/evalsets/curator.evalset.json`. Total cases: **30**. Own only the evalset file."

**Track B — Agent Optimizer pass (me, sequential):**
- **Morning 2-hour spike:** write `app/optimization/run_gepa.py` — load `agent_runs` from Spanner (now properly grouped by `(agent_name, prompt_hash)` after D5's hash fix), format as GEPA training data, run **one** `GEPARootAgentPromptOptimizer` pass against the `decompose` agent with hard budget cap `$25`. If `gepa` package errors or undocumented surface blocks > 2 hours, **immediately switch to `SimplePromptOptimizer`** (same module path, simpler API). Do not exceed $30.
- Capture before/after rubric deltas on the now-30-case evalset. Commit the optimized prompt as a new branch `optim/gepa-decompose-v2` — do not merge until validated.
- If validated: cherry-pick the prompt delta into main. Document in `docs/OPTIMIZATION_LOG.md` with rubric scores. **This is the demo's "the agent improved itself" proof-point.**
- If budget allows after the decompose pass: optional second pass on the `judge` agent (~$5 budget).

**Track C — Accuracy audits (me, after AM spike):**
- **Reconciler over-dedup audit:** run real-LLM chain with the panel; instrument `reconcile_obligations` to log pre/post-dedup counts per `(source_clause_id, _normalize_action_key)`. If any two distinct actions collapse, refine `_normalize_action` (raise the token-count floor, or include the first 12 tokens instead of 8, or skip stemming). Capture in `docs/eval_baselines/RECONCILER_AUDIT_2026-06-08.md`.
- **Confidence calibration audit:** plot eval pass-rate vs aggregate-confidence buckets. If high-confidence (>0.85) cases pass at the same rate as low-confidence (<0.6), the calibration adds no signal — log this as a known limitation; D8 Devpost text uses honest language ("confidence is calibrated to lens agreement, not eval pass rate").
- **Lens-diversity audit:** for one chain run, capture the 4 lenses' pre-reconciliation obligation lists. Compute Jaccard similarity between each pair. If any pair > 0.85, that lens is redundant — note for Phase-5.

**Commit:** `phase-3.1: agent-optimizer pass + 25 simulated eval cases + accuracy audits`.

### D7.5 — A2A bridge to bbb MCP (added end-of-session 2026-06-02, ~1 day)

**Why this got added:** end-of-session question about pulling from QuestDB / TSDB / Milvus / Neo4j / object store (the bbb production stack). Direct ingestion of those into the public hackathon repo breaks the IP boundary (DECISIONS-1..9 + CLAUDE.md). An **A2A bridge** delivers the same "agent learns from multiple sources" value without crossing the wall: Curator gains one A2A *client* tool that POSTs to bbb's already-running MCP gateway. Curator stays IP-clean (it sees only the A2A interface); bbb's Milvus / Neo4j / QuestDB stay on bbb's side. Also doubles down on the Track-3 A2A protocol mandate (we already *expose* A2A skills; now we *consume* one too).

**Files to add:**
- `app/tools/bbb_a2a_client.py` — single `FunctionTool` wrapping a POST to `https://mcp.aidni.cloud/mcp` with bearer auth. Reads `BBB_MCP_BEARER` env var (never committed); fail-quiet if unset so the offline path stays green. Method names mirror bbb's MCP surface: `regulatory_deep_lookup(query, k=5)` → returns list of `{title, source_url, snippet, citation_count}` dicts.
- `tests/integration/test_bbb_a2a_client.py` — 2 tests: hard-skip when `BBB_MCP_BEARER` unset; happy-path live test that asserts non-empty result list.

**Files to modify (tiny):**
- `app/sub_agents/qna.py` — add the new tool to the `tools=[…]` list of `build_agent()`. When `BBB_MCP_BEARER` is set at runtime, the Q&A agent can call it to enrich answers with cited bbb-corpus snippets. When unset, the agent doesn't call it (no offline-path impact).
- `app/sub_agents/reflector.py` — optional: when `reflect_and_requery` returns empty `extra_context` from the Spanner backend AND `BBB_MCP_BEARER` is set, fall back to the A2A bridge as a secondary grounding source.
- `README.md` — short subsection explaining: "Curator's hackathon repo includes an optional A2A bridge to a private enterprise data layer; the demo uses bbb's MCP gateway. Set `BBB_MCP_BEARER` and the Q&A turn enriches automatically; without it the chain runs against Spanner Graph alone."

**Demo evidence:** one Q&A turn during the D9 video shows two answers side-by-side — Spanner-only vs Spanner+bbb-A2A-enriched — making the multi-source value visible without revealing what's behind the bridge.

**Cost:** ~1 day. ~100 LOC. Zero new GCP services. ~$0 incremental Gemini spend (one extra QnA call per demo run).

**File ownership:** me, sequential (no subagent — touches Q&A wiring which is sensitive). Lands between D7 and D8, so the D8 architecture diagram + Devpost fields can mention the A2A client surface.

**Commit:** `phase-3.2: A2A bridge to bbb MCP — Q&A enrichment without crossing the IP wall`.

**Defer-condition:** if D8 timeline is tight, this slips to Phase 5 cleanly — it's additive, not load-bearing for Gate 3 or Gate 4.

### D8 — Devpost assets (3 parallel subagents) + value-system narrative

**Track A — Architecture diagram (subagent):**
- `docs/submission/architecture.svg` (Mermaid → render). Must show: PDF upload → DocAI Layout Parser → graph extractor → Spanner Graph; the 4-lens decompose panel + Reconciler + Reflector loop; the 4-critic judge panel; `agent_runs` observability stream; Agent Optimizer feedback path; standalone Discovery service + Pub/Sub topic; Cloud Run × 2 boundaries; A2A skill card surface.
- Render to both SVG (for the Devpost upload) and PNG (for inline README embedding).

**Track B — Devpost written fields (subagent):**
- `docs/submission/devpost_fields.md` covering Devpost's required sections. Each section to lift the value-system framings finalised in the new "Value System & Positioning" section of this plan:
  - **Problem.** Indian BFSI compliance volume: ~100-120 RBI / 60-80 SEBI / 40-50 IRDAI circulars/yr; ~30% trigger policy edits. Each material amendment = **2-4 weeks** of CCO-team time. Existing tools are document-portal-based, not agentic. CCO buyer persona, ₹5-20 lakhs WTP, 40 banks + 500 PMS + 100 insurers TAM.
  - **Solution.** Curator: a continuous, autonomous regulatory-intelligence agent team in your cloud. Always-on RBI discovery → 4-lens debate decompose → coverage map → diff drafting → impact judgment → cited Q&A. Proposals only; human approves. <10 minutes per amendment.
  - **Innovation.** Four stakeholder lenses (banker / compliance / auditor / customer-protect) debate every amendment in parallel; a Reconciler merges and a Reflector triggers Spanner Graph re-query on low-confidence — measurably surfacing **3.2× more obligations** and **6× more missing-coverage gaps** than a single-shot agent on the demo fixture.
  - **Technical implementation.** Cloud Run × 2 (chain + discovery), A2A protocol GA, Gemini-flash via ADK 1.34 `ParallelAgent`/`SequentialAgent`, Spanner Graph in asia-south1, Doc AI Layout Parser, Cloud Scheduler + Pub/Sub, Agent Optimizer (GEPA), Agent Simulation, Cloud Trace observability.
  - **Business case.** ARIA solves one workflow (KYC). Curator solves the *layer* — regulatory-intelligence-as-a-platform. Marketplace path: `agents-cli publish gemini-enterprise`. India residency story: Spanner Graph in asia-south1; the only cross-region call is Doc AI (us; documented).
  - **Findings & learnings.** Mine `docs/DECISIONS.md` (9 entries), `docs/OPTIMIZATION_LOG.md` (D7 GEPA delta), `docs/eval_baselines/GATE{1,2,3}_*.md`, `docs/eval_baselines/RECONCILER_AUDIT_2026-06-08.md`. Cite specific obligation counts, eval scores, latency numbers.
- 1500-word ceiling. Tone: confident, specific, not buzzword-heavy.

**Track C — Repo hygiene (subagent):**
- Grep for `bbb`, `tailscale`, `milvus`, `neo4j`, `matryoshka`, `deontic` (in code; concept is permissible in docs as a *generic* term) — confirm zero matches in `app/`, `tests/`, `scripts/`, public `docs/` (NOT `docs/sessions/` or `docs/google_agent/` which are research notes that may reference adjacent BBB work).
- README sweep: one-command setup, Spanner setup steps added per D6 README addendum, Apache 2.0 LICENSE present, no secrets, GCS/Spanner cleanup instructions visible.
- May edit `README.md`, `LICENSE` only.

**Me (sequential, sees A/B/C outputs):**
- Demo video script + shot list at `docs/submission/video_script.md`. 3-min structure (per `docs/Build_plan_till_22May2026.md:169-175` framing):
  1. **Hook (20s):** "An Indian compliance officer gets an RBI amendment every fortnight. Today she spends 2-4 weeks reviewing, mapping to internal policy, drafting board memos. Curator does the proposal in under 10 minutes."
  2. **Discovery Inbox (30s):** open the live Inbox, show auto-discovered items from RSS polling; click one.
  3. **Debate visibility (60s):** chain runs; Cloud Trace shows 4 parallel lens spans fanning out, converging at the Reconciler. ImpactSummary surfaces ICAAP / Pillar-3 / RMC effects.
  4. **Self-improvement (30s):** open `docs/OPTIMIZATION_LOG.md`; show GEPA before/after rubric scores; "the agent improved its own prompts."
  5. **A2A + architecture (30s):** A2A inspector points at the deployed URL; 6 skills visible; brief diagram flash.
  6. **Business case + close (30s):** 40 banks × ₹15L WTP × annual cycle = ₹6Cr addressable in the first vertical. Marketplace path one-liner. Apache 2.0 + public repo.

### D9 — Tue 2026-06-10 — Record + submit + buffer
**User-led, me supporting.**
- Record demo video (user). I produce screen-recording cues and standby for re-takes.
- Final smoke: deploy URLs healthy, A2A inspector clean, Inbox populated, eval still ≥0.7.
- Submit on Devpost; verify by re-opening as anonymous viewer. **Tag `gate-4`. Push.**

### D10 — Wed 2026-06-11 — Submission day buffer (deadline 17:00 PT)
- Reserved entirely for unexpected fixes (Cloud Run config, A2A card, video re-upload, Devpost form issues).
- If everything held: micro-polish — sharper README hook line, second `SimplePromptOptimizer` pass on `judge` if budget allows, one extra demo screenshot.
- **Hard stop at 12:00 PT** — any remaining work is post-deadline polish branch only.

---

## Value System & Positioning (D8 Devpost source-of-truth)

This section is the canonical reference for every customer-facing string in D8 (README, Devpost fields, video script, demo voice-over). The audit pulled these from BBB's investor pitch but reframed them within the hackathon repo's IP boundary — no proprietary tech names leak.

### Persona
- **Chief Compliance Officer** (or equivalent: Head of Risk & Compliance, Group CRO, Regulatory Reporting Lead) at:
  - An Indian commercial bank (private/PSU).
  - A SEBI-registered Portfolio Management Services firm (~500+ in market).
  - An IRDAI-licensed insurer (~100+ composite/life-only).
- Day-to-day pain: every fortnight an RBI/SEBI/IRDAI circular lands. Two to four weeks of CCO-team time to read it, map to internal policies, draft board memos, update Pillar-3 templates, retrain RMC standing-agenda items.
- Today's tools: document portals (eGazette, RBI search) + Excel gap analyses. No agentic layer.

### Pain point quantification
| Regulator | Circulars/yr | % material | Hours/circular today |
|---|---|---|---|
| RBI | 100-120 | ~30% | 60-160 (2-4 weeks) |
| SEBI | 60-80 | ~25% | 40-100 |
| IRDAI | 40-50 | ~20% | 30-80 |

### Value proposition (one sentence)
> Curator is an autonomous, always-on regulatory-intelligence team in your cloud: it watches RBI/SEBI/IRDAI, four stakeholder lenses debate every material amendment, a reflector catches what they miss against your prior decisions, and the output is a board-ready impact assessment with cited downstream effects — proposals only, human approves.

### Quantified differentiation (post-Gate-1 measurements)
- **3.2× more obligations** surfaced than a single-shot agent on the demo fixture (19-21 vs 6).
- **6-7× more missing-coverage gaps** caught (6-7 vs 1).
- Priority correctly escalated `medium → critical` when the panel surfaces capital-impact obligations a single agent misses.
- End-to-end (with target D5 parallelization): chain runs in **< 60 seconds** vs 2-4 weeks of human time.

### Competitive positioning
- **ARIA** (Build track, single submitted Indian BFSI competitor): KYC onboarding automation — a single-document workflow at speed. Curator addresses a different layer: **comparative regulatory intelligence** (amendment vs prior; obligation × policy; pre/post). No direct overlap — different TAM, different stakeholder.
- Existing RegTech vendors are portal-based, not agentic. Curator's debate panel + self-improvement loop is the differentiator.

### Pricing / TAM (Devpost Business Case section)
- WTP: ₹5-20 lakhs/year per institution per regulator subscription.
- Primary TAM: 40 RBI banks × ₹15L = ₹6 crore ($720K) annual; secondary: 500 PMS × ₹5L = ₹25 crore; ~₹50 crore ($6M) addressable across BFSI within 2 years of GA.
- Marketplace path: `agents-cli publish gemini-enterprise` post-submission; partner onboarding via Google Cloud India.

### India residency story
- Spanner Graph in `asia-south1` (Mumbai). All ingested regulatory text + bank policy data lives in-country.
- Vertex AI `vertexai.init(location="us-central1")` controls model-serving region only; Gemini-flash itself is routed via `global`. Documented in DECISIONS-9.
- The one cross-region call is Doc AI Layout Parser (US-only per Google). We disclose this honestly in the README; the alternative is no Doc AI which would hurt accuracy more than the cross-region call hurts residency.

### Tone
- Confident, specific, not buzzword-heavy. Honest about what's proposal-only vs autonomous. No "AI will replace your compliance team" framing — the explicit positioning is **proposals only, human in the loop, every time**.

---

## End-to-end testing & validation matrix

Stage-2 ships across 4 surfaces: (1) offline `python -m app.chain` (stubs, no GCP), (2) `pytest tests/unit tests/integration` (mock + skip-gated), (3) live real-LLM via `CURATOR_REAL_LLM=1`, (4) deployed Cloud Run × 2.

| Test surface | Frequency | Trigger | Authoritative for |
|---|---|---|---|
| `python -m app.chain` (stub) | Every commit | Manual / pre-commit | **Regression airlock.** Canonical line must match exactly. |
| `pytest tests/unit tests/integration -q` (no live flags) | Every commit | Manual / CI if added | Schema validity, ParallelAgent/Reconciler/Reflector unit shape, mock pipeline. |
| `CURATOR_REAL_LLM=1 python -m app.chain` | Every gate | Manual | The demo path. Obligation count, fan-out moment, eval rubrics. |
| `pytest tests/integration/test_*.py` with `CURATOR_LIVE_GCP=1` + `CURATOR_DOCAI_PROCESSOR_ID=…` | Every gate | Manual | Spanner round-trip; DocAI parse; pipeline ingest. |
| `CURATOR_REAL_LLM=1 CURATOR_AGENT_RUN_LOG=1 python -m app.chain` + `SELECT COUNT(*) FROM agent_runs WHERE pipeline_run_id=…` | Gate 2, D5, D7, D9 | Manual | Observability + GEPA training data accumulation. |
| `adk eval app tests/eval/evalsets/curator.evalset.json` | Pre-Gate-1, D7 baseline, D7 post-optimizer, D9 final | Manual | Rubric compliance + GEPA before/after. |
| Cloud Run dry-run (chain `/health`, `/.well-known/agent.json`, browser `/` + `/inbox`) | Gate 3, D9 | Manual after deploy | Deployment correctness. |
| A2A inspector against deployed URL | Gate 3, D9 | Manual | Skill card surface; required for Track-3 mandate. |
| Cloud Trace span review | D6, D8 (for screenshots) | Manual | Visible fan-out for demo video. |
| Discovery cron live trigger | D6, D9 | Cloud Scheduler `*/30 * * * *` | Discovery → Pub/Sub → subscriber → chain → Inbox row. End-to-end autonomy proof. |
| Devpost preview as anonymous viewer | D9 | Manual | Submission visibility. |

**D9 final validation script** (must all pass before pressing Submit):
```bash
# 1. Offline regression
python -m app.chain                                      # canonical line

# 2. Real chain + logging (panel debate visible)
source scripts/env.sh
CURATOR_REAL_LLM=1 CURATOR_AGENT_RUN_LOG=1 python -m app.chain

# 3. Full pytest (unit + integration)
pytest tests/unit tests/integration -q                   # 0 failures, expected skips OK

# 4. Live GCP smoke
CURATOR_LIVE_GCP=1 CURATOR_DOCAI_PROCESSOR_ID=… pytest tests/integration/test_pipeline.py tests/integration/test_docai.py -v

# 5. Deploy health
curl -fsS https://<chain-url>/health
curl -fsS https://<discovery-url>/health
curl -fsS https://<chain-url>/.well-known/agent.json | jq '.skills | length'    # ≥ 5

# 6. Eval pass (30-case)
CURATOR_REAL_LLM=1 adk eval app tests/eval/evalsets/curator.evalset.json --config_file_path=tests/eval/eval_config.json

# 7. Spanner row check
gcloud spanner databases execute-sql curator --instance=curator-graph \
  --sql="SELECT COUNT(*) FROM agent_runs WHERE ts > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)"

# 8. Devpost re-open as anonymous
# (manual browser step — confirm video, diagram, fields visible to a logged-out viewer)
```

---

## File-ownership matrix (extending legacy plan §3.2)

| Day | Subagent / Owner | Owns (edit allowed) | Strictly forbidden |
|---|---|---|---|
| D1 | me | `app/models.py`, `app/sub_agents/*.py` (output-schema only), `app/chain.py`, `pyproject.toml`, `docs/DECISIONS.md`, `docs/STAGE2_IMPLEMENTATION_PLAN.md` | everything else |
| D2-A | me | `app/sub_agents/{lenses,reconciler,reflector,decompose}.py`, `app/agent.py`, `tests/integration/test_parallel_smoke.py` | grounding, runners, models |
| D2-B | me | `scripts/spanner_up.sh`, `app/ingest/spanner_schema.sql` | sub_agents |
| D3-A | judge-panel subagent | `app/sub_agents/judge_panel.py`, `app/sub_agents/judge.py`, `tests/integration/test_judge_panel.py` | everything else |
| D3-B | docai subagent | `app/ingest/docai.py`, `tests/integration/test_docai.py` | everything else |
| D4 | me | `app/grounding.py`, `app/ingest/graph_extractor.py`, `app/ingest/pipeline.py`, `app/observability/run_log.py`, `app/runners.py`, `app/sub_agents/reflector.py` | UI, discovery, models |
| D5-A | discovery subagent | `app/discovery/{rss_poller,dedupe,publisher,service}.py`, `deployment/discovery/*`, `tests/integration/test_discovery.py` | sub_agents, grounding, models |
| D5-B | me (UI track) | `app/fast_api_app.py`, `app/templates/*.html`, `app/discovery/subscriber.py`, `tests/integration/test_server_e2e.py` (extend, don't delete) | discovery service code (D5-A's lane) |
| D5-C | me (speed/accuracy track) | `app/sub_agents/{map_,diff}.py` (ThreadPoolExecutor only), `app/sub_agents/{decompose,judge}.py` (reflect_and_requery wiring only), `app/observability/run_log.py` (prompt_hash fix), `app/ingest/{docai,spanner_schema.sql}` (parsed_chunks cache + table) | reconciler logic, lenses, models |
| D6 | me | `deployment/terraform/single-project/{service.tf,variables.tf}`, deploy YAMLs, `README.md` (deploy section), `agent.json` if needed | code (frozen after D5) |
| D7-A | sim subagent | `tests/eval/evalsets/curator.evalset.json` (append-only) | everything else |
| D7-B | me (optimizer) | `app/optimization/run_gepa.py`, `docs/OPTIMIZATION_LOG.md`, the decompose/judge prompts | infra |
| D7-C | me (audits) | `docs/eval_baselines/RECONCILER_AUDIT_*.md`, `docs/eval_baselines/CALIBRATION_AUDIT_*.md`, `docs/eval_baselines/LENS_DIVERSITY_AUDIT_*.md` (and a small instrumentation patch in `reconciler.py` if needed for the audit only) | prompts, lens preambles |
| D8-A | diagram subagent | `docs/submission/architecture.{md,svg,png}` | everything else |
| D8-B | devpost subagent | `docs/submission/devpost_fields.md` | everything else |
| D8-C | hygiene subagent | `README.md`, `LICENSE` | everything else |
| D9 | user | demo video (YouTube unlisted), Devpost form | code |

`app/models.py` frozen after D1 EOD. `app/runners.py` frozen after D5 EOD (only `prompt_hash` fix + the existing `log_run` wiring). Stubs (`stub_*`) never touched.

---

## Gate definitions

- **Gate 1 (D3 EOD) — CLEARED 2026-06-02:** Multi-perspective `decompose` + `judge` panels working under real-LLM. Confidence + missing_evidence emitted. `python -m app.chain` regression-clean. Eval ≥0.7 — actually 5/5 at 1.0.
- **Gate 2 (D4 EOD) — CLEARED 2026-06-02:** Spanner ingestion live for `02` vs `03`. `agent_runs` table populating (62 rows/chain). Reflector unit-tested. Offline path green.
- **Gate 3 (D6 EOD) — SUBMITTABLE FLOOR:** Cloud Run × 2 deployed (chain + discovery). A2A card lists 5-6 skills. Discovery Inbox UI shows auto-triggered runs. Uploaded-PDF UI shows debated decompose results. **NEW:** all `test_server_e2e.py` tests pass (D5 fixed the `/run_sse` endpoint). **NEW:** Terraform `service.tf` injects all 6 required env vars + SA has all required roles. **NEW:** map/diff parallelization in place (chain wall-clock < 60s). **NEW:** Reflector re-query loop is wired into the demo path with bounded re-runs. Four Track-3 mandates met. Offline regression green. **Tagged `gate-3` and pushed; stage-2 merged to main.**
- **Gate 4 (D9 EOD):** Devpost submission complete with architecture diagram, written fields (1500w), repo hygiene clean, video uploaded. One Agent-Optimizer (GEPA or SimplePromptOptimizer) pass demonstrably improved at least one rubric on the 30-case evalset; before/after captured in `docs/OPTIMIZATION_LOG.md`. **NEW:** reconciler-dedup audit + confidence-calibration audit + lens-diversity audit each documented under `docs/eval_baselines/` and referenced from the Devpost "Findings & learnings" section.

### Cross-cutting non-gate metrics (must improve, not just pass)

| Metric | D4 baseline | D8 target | How measured |
|---|---|---|---|
| Real-LLM chain wall-clock (demo fixture) | ~120s | < 60s | `time CURATOR_REAL_LLM=1 python -m app.chain` |
| Obligation count (real chain vs stub) | 19-21 vs 6 | unchanged | smoke output |
| Missing-coverage gaps surfaced | 6-7 vs 1 | unchanged | smoke output |
| Eval cases | 5 | 30 | `wc -l tests/eval/evalsets/curator.evalset.json` |
| Eval rubric average | 1.0 (suspect — see audit) | calibrated, honest reporting | post-D7 audit |
| Per-chain LLM cost | ~$0.66 | ≤ $1.00 even with reflector re-runs | cost_usd_estimated from `agent_runs` |
| `agent_runs` rows per chain | 62 | 60-80 (no regression from instrumentation) | SQL count |
| Doc AI re-parse rate | 100% | < 10% (cache hit on D5+) | `parsed_chunks` cache hit metric |

---

## Risk register additions (extending legacy §4)

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R13 | `ParallelAgent` of LLM sub-agents misbehaves inside `Runner.run_async` event stream | medium | high | D2 morning 50-line smoke harness de-risks. **RESOLVED in D2: ParallelAgent works under InMemoryRunner.** |
| R14 | GEPA optimizer undocumented / unstable | medium | medium | D7 morning 2-hour spike. Fallback: `SimplePromptOptimizer` same module. Hard budget cap $30. |
| R15 | RBI RSS feed unreachable / malformed at demo time | low | medium | Seed 5 known items in `discovered_items` before the D9 video. If RSS is down at demo time, the seeded items still render in Inbox. |
| R16 | Cloud Run cold-start ugly in live demo | low | low | `--min-instances=1` on chain service after Gate 3 (~$5/day, within budget). |
| R17 | Spanner asia-south1 vector-index creation slow (~5 min) | medium | low | Warmed during D2-B. **RESOLVED — schema applied.** |
| R18 | Subagent file-scope violation (touches forbidden file) | medium | medium | `git diff --stat` after every subagent; revert + re-spawn with tighter brief. Already legacy-plan policy. |
| R19 | Map/diff parallelization introduces race conditions | low | medium | `run_agent` is stateless per call; results collected into a fresh list. Add unit test that 8 parallel calls return ordered, non-empty results. |
| R20 | Reflector re-run loop blows the budget on a low-confidence amendment | low | medium | Bound to **one** re-run per chain; cost cap on the re-run path ($0.20 max). Track via `agent_runs.cost_usd_estimated`. |
| R21 | Doc AI `parsed_chunks` cache returns stale chunks after a PDF update | low | low | Cache key is `sha256(pdf_bytes)` — a content change forces a fresh parse. Stale rows are unreachable, harmless. |
| R22 | Devpost submission form rejects video format / file size | low | high | Pre-upload to YouTube as unlisted; submit YouTube link, not raw file. Test the form 24h before deadline. |
| R23 | `agent_runs` Spanner table fills disk / hits quota | low | low | Stage-2 cap 100K rows; `gcloud spanner databases query` for size monitoring before D9. Truncate rows older than 7 days if needed. |
| R24 | Pre-existing `test_server_e2e.py` failures are deeper than D5 expects | medium | medium | D5 Track B explicitly wires `/run_sse` against ADK's runner. If ADK's event-stream surface is unexpectedly hard, fall back to deleting the 3 failing tests with a marker comment pointing at the issue. |
| R25 | Agent Optimizer needs ≥50 runs for meaningful signal; we accumulate slower than expected | medium | low | D5+D6 each run real-LLM chains a few times for smoke (each = 62 rows). By D7 morning we expect 200+ rows. If not, accept SimplePromptOptimizer with fewer data points. |
| R26 | India-residency claim breaks if Cloud Run service must run in `us-central1` for an unknown reason | low | medium | Spanner is what governs data residency, not the compute region. Document in DECISIONS-9. If `asia-south1` Cloud Run blocks at deploy, fall back to `us-central1` for compute and state the residency story honestly. |

---

## What NOT to do (scope cuts to stay submittable)

- Do not debate `map_`, `diff`, or `qna` — adds latency without clear quality win on mechanical steps.
- Do not chase GEPA past 1 pass or $30. Switch to `SimplePromptOptimizer` on first sign of trouble.
- Do not add per-lens persistent memory — panels are stateless per call.
- Do not share runner code between chain service and discovery service — keep discovery thin and resilient.
- Do not expand evalset past 30 cases before Gate 3.
- Do not touch `app/models.py` after D1 EOD. Schema freeze.
- Do not delete `stub_*` paths. Ever. They are the airlock.
- Do not add Slack/email notifications, multi-tenant auth, RBAC, or any "enterprise feature" not on a gate checklist.
- Do not add a second LLM provider. `gemini-flash-latest` everywhere.
- Do not introduce a vector DB beyond Spanner Graph's native vector indexes.
- Do not add cross-corpus (`04` vs `05`) comparison before Gate 3 — Phase 5 polish only.
- **If D6 deploy slips past EOD:** cut the discovery service from Gate 3 entirely. Ship chain-only at Gate 3; add discovery on D7–8 as polish-branch. Four Track-3 mandates are met without discovery.

---

## Critical files (entry points for D5-D9 implementation)

**D5 — Discovery + UI + speed/accuracy lifts:**
- `app/discovery/{rss_poller,dedupe,publisher,service,subscriber}.py` (NEW; subagent)
- `deployment/discovery/scheduler.yaml` (NEW; subagent)
- `app/fast_api_app.py` — extend with `/`, `/analyse`, `/inbox`, `/impact`, `/qna`, `/run_sse` (me)
- `app/templates/{base,upload,analyse,inbox,impact,qna}.html` (NEW; me)
- `app/sub_agents/map_.py` + `diff.py` — ThreadPoolExecutor parallelization (me)
- `app/sub_agents/decompose.py` + `judge.py` — wire `reflect_and_requery` into demo path (me)
- `app/observability/run_log.py` — `prompt_hash` includes `(agent_name, instruction, user_text)` (me)
- `app/ingest/docai.py` + `app/ingest/spanner_schema.sql` — `parsed_chunks` cache (me; schema-migration via `database.update_ddl`)

**D6 — Deploy:**
- `deployment/terraform/single-project/service.tf` — add 6 missing env vars, replace placeholder image
- `deployment/terraform/single-project/variables.tf` — add SA roles
- `agent.json` (if auto-card incomplete)
- `README.md` — deploy + Cloud Trace dashboard + Spanner setup section

**D7 — Optimizer + audits:**
- `app/optimization/run_gepa.py` (NEW)
- `docs/OPTIMIZATION_LOG.md` (NEW)
- `tests/eval/evalsets/curator.evalset.json` — expand 5 → 30 (subagent, append-only)
- `docs/eval_baselines/{RECONCILER_AUDIT,CALIBRATION_AUDIT,LENS_DIVERSITY_AUDIT}_2026-06-08.md` (NEW)

**D8 — Submission assets:**
- `docs/submission/{architecture.svg,architecture.png,devpost_fields.md,video_script.md}` (NEW)

**Existing reusable scaffolding (do NOT rewrite — reuse):**
- `run_agent` retry/JSON-repair at `app/runners.py:137-186`.
- `_run_panel` in `decompose.py` and `judge.py` — same pattern for D5's map/diff parallelization.
- `MockGroundingBackend` at `app/grounding.py:49-125` — keep working as airlock.
- `PolicyMatch.confidence` at `app/models.py:121` — schema pattern (frozen now).
- `inout/*.html.json` sidecars — fallback if live DocAI fails at demo time.
- `begin_pipeline_run()` / `log_run()` in `app/observability/run_log.py` — thread-safe via `contextvars` + module mirror; D5's parallelization reuses this for free.
- `reflect_and_requery` in `app/sub_agents/reflector.py` — already built + unit-tested; D5 wires it into the demo path.

---

## Verification per remaining gate

(Gate 1 + Gate 2 already cleared; full verification scripts captured in `docs/eval_baselines/GATE{1,2}_*.md`. The cross-cutting "End-to-end testing & validation matrix" section above is the authoritative checklist; per-gate-specific additions below.)

**Gate 3 (D6 EOD) — must add to the existing matrix:**
```bash
# Post-Terraform-fix: deploy
adk deploy cloud_run --service_name=curator-chain ... --with_ui --a2a   # see plan §D6
adk deploy cloud_run --service_name=curator-discovery ... # smaller profile
gcloud scheduler jobs create http curator-discovery-poll --schedule="*/30 * * * *" --uri=…

# Health + A2A
curl -fsS https://<chain-url>/health
curl -fsS https://<discovery-url>/health
curl -fsS https://<chain-url>/.well-known/agent.json | jq '.skills | length'     # ≥ 5

# Two browser dry-runs (judge persona)
# (a) chain `/` → upload 02 + 03 PDFs → debate panel + ImpactSummary visible
# (b) chain `/inbox` → seeded or RSS-derived row visible; click → impact view

# Cross-cutting metrics:
time CURATOR_REAL_LLM=1 python -m app.chain                                       # < 60s
gcloud spanner databases execute-sql curator --instance=curator-graph \
  --sql="SELECT COUNT(*) FROM parsed_chunks"                                      # > 0 (cache populated)

# Test suite (no expected failures)
pytest tests/unit tests/integration -q                                            # 0 failed
```

**Gate 4 (D9 EOD) — additions beyond D9 final validation script:**
```bash
# Optimizer pass evidence
python app/optimization/run_gepa.py --budget-usd=25 --target=decompose            # writes OPTIMIZATION_LOG.md

# 30-case eval (post-GEPA)
CURATOR_REAL_LLM=1 adk eval app tests/eval/evalsets/curator.evalset.json --config_file_path=tests/eval/eval_config.json

# Devpost preview (anonymous browser tab)
# Confirm: video plays, architecture diagram renders, business case readable, links work
```

---

## Next execution step after this plan is re-approved

Two parallel subagent kickoffs for D5 (matching the file-ownership matrix):

1. **Track A** — Discovery service subagent (`app/discovery/*` + `deployment/discovery/*`).
2. **Track B** — UI templates (me, sequential after subagent briefs out). Wires `/run_sse` so the 3 pre-existing failing tests turn green rather than being deleted.

Track C (speed/accuracy lifts: map/diff parallelization, Reflector wiring, `prompt_hash` fix, Doc AI cache) runs **after** Track B's templates land so the UI work doesn't conflict with the runners/observability edits.

If real-LLM rate-limits hit during D5 smokes, fall back to seeded Spanner data for the live demo (R15 mitigation) and proceed to D6.
