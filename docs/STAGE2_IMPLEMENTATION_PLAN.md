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

## Day-by-day calendar (D1 = 2026-06-02 Mon → D10 = 2026-06-11 Wed)

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

### D5 — Fri 2026-06-06 — Discovery agent (Cloud Run service) + UI templates (PARALLEL)
**Track A — Subagent on discovery agent:**
- Brief: "Implement standalone Cloud Run service in `app/discovery/` and `deployment/discovery/`. Files: `app/discovery/rss_poller.py` (polls `https://www.rbi.org.in/Scripts/RssNotification.aspx`, parses notifications via `feedparser`), `app/discovery/dedupe.py` (Spanner `discovered_items` hash-check), `app/discovery/publisher.py` (Pub/Sub publish to `projects/{PROJECT}/topics/curator-discoveries`), `app/discovery/service.py` (FastAPI app with `/poll` endpoint for Cloud Scheduler, `/health` standard). Cloud Scheduler YAML at `deployment/discovery/scheduler.yaml`. Own only `app/discovery/*`, `deployment/discovery/*`, `tests/integration/test_discovery.py`. Resilience: never depend on chain service uptime."
- File ownership strictly enforced.

**Track B (me, parallel, UI):**
- Extend `app/fast_api_app.py` with Jinja templates per legacy §3.3 PLUS `/inbox` route.
- Templates: `app/templates/{base.html, upload.html, analyse.html, inbox.html, impact.html, qna.html}`. Clean, monospace, no marketing.
- `/inbox` queries Spanner: `SELECT * FROM discovered_items LEFT JOIN agent_runs ON discovered_items.agent_run_id = agent_runs.run_id ORDER BY first_seen DESC LIMIT 50`.
- HTMX polling for in-flight runs.
- Pub/Sub subscriber: new `app/discovery/subscriber.py` running inside the chain service, listening on `curator-discoveries` topic, triggering the chain on each new item and writing `agent_run_id` back to `discovered_items`.

**Regression:** stub chain green. Real chain green on `02` vs `03`. Discovery service ingests at least one item locally (mocked RSS feed for the test).
**Commit:** `phase-2.3: discovery agent + inbox UI`.

### D6 — Sat 2026-06-07 — Cloud Run deploy x2 + Discovery Inbox wiring
**Owner: me, sequential (user approval gate before each deploy).**
- `agents-cli infra single-project` for chain-service Terraform if not done.
- Deploy 1: `adk deploy cloud_run --service_name=curator-chain --project=curator-research --region=asia-south1 --trace_to_cloud --otel_to_cloud --with_ui --a2a --service_account=curator-ai-engine@curator-research.iam.gserviceaccount.com .` (region per DECISIONS-6).
- Deploy 2: `curator-discovery` — same flags minus `--with_ui --a2a`. Smaller resource profile.
- Cloud Scheduler job created via `gcloud scheduler jobs create http curator-discovery-poll --schedule="*/30 * * * *" --uri="https://<discovery-url>/poll" --oidc-service-account=…`.
- Validate `/.well-known/agent.json` on chain service lists 5 skills (decompose-panel, map, diff, judge-panel, qna). Hand-edit `agent.json` if auto-card incomplete; add a 6th skill `discovery.poll` advertised by discovery service.
- Validate A2A discovery from `tools/a2a-inspector/` (gitignored).
- README addendum pointing judges at Cloud Trace dashboard.

**Gate 3 — SUBMITTABLE FLOOR (EOD):**
- Deployed Cloud Run URLs (chain + discovery) both healthy.
- A2A-discoverable, 6 skills exposed.
- Gemini reasoning, B2B, Cloud Run, A2A — all four Track-3 mandates met.
- Judge can: (a) upload 2 PDFs via UI → full debated chain output; (b) open Inbox → see auto-discovered RBI items processed by the chain.
- Offline `python -m app.chain` green.
- **Tag `gate-3`. Push.** Project is now submittable at respectable quality regardless of what slips next.

### D7 — Sun 2026-06-08 — Agent Optimizer + Simulation eval expansion (PARALLEL)
**Track A — Subagent on simulation:**
- Brief: "Use `google.adk.evaluation.simulation.llm_backed_user_simulator` with `pre_built_personas` to generate 15 new evalset cases targeting fan-out depth, multi-hop Q&A, and downstream-effect detection. Append to `tests/eval/evalsets/curator.evalset.json`. Total cases: 30. Own only the evalset file."

**Track B (me, sequential, optimizer):**
- **D7 morning de-risk (2-hour spike):** write `app/optimization/run_gepa.py` — load `agent_runs` from Spanner, format as GEPA training data, run **one** `GEPARootAgentPromptOptimizer` pass against the `decompose` agent with hard budget cap `$25`. If `gepa` package errors or undocumented surface blocks > 2 hours, **immediately switch to `SimplePromptOptimizer`** (same module path, simpler API). Do not exceed $30.
- Capture before/after rubric deltas. Commit the optimized prompt as a new branch `optim/gepa-decompose-v2` — do not merge until validated.
- If validated: cherry-pick the prompt delta into main. Document in `docs/OPTIMIZATION_LOG.md` with rubric scores.
- This is the demo's "the agent improved itself" proof-point.

**Commit:** `phase-3.1: agent-optimizer pass + 15 simulated eval cases`.

### D8 — Mon 2026-06-09 — Devpost assets (3 PARALLEL subagents) + demo video script
**Three subagents in parallel (legacy §4.1 a/b/c brief, lightly updated):**
- A — Architecture diagram (Mermaid → SVG) at `docs/submission/architecture.svg`. Must show: 4-lens debate panels, LoopAgent reflector, Spanner Graph, agent_runs table, Agent Optimizer feedback, Discovery Agent + Pub/Sub, Cloud Run × 2, A2A skill card.
- B — Devpost written fields at `docs/submission/devpost_fields.md`. Problem, Solution, Technologies, Data sources, Findings & learnings (mine `docs/DECISIONS.md` + `docs/OPTIMIZATION_LOG.md`), Business case, Marketplace path.
- C — Repo hygiene: grep for `bbb`/`tailscale`/`milvus`/`neo4j`/`matryoshka` → none. README one-command setup. Apache 2.0 LICENSE present. No secrets committed. May edit `README.md` and `LICENSE` only.

**Me (parallel):** write demo video shot list and script (`docs/submission/video_script.md`). 3-minute structure: hook → discovery inbox → upload + watch debate fan out + reflection → optimization log → architecture + tech stack → business case → close.

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

## File-ownership matrix (extending legacy plan §3.2)

| Day | Subagent / Owner | Owns (edit allowed) | Strictly forbidden |
|---|---|---|---|
| D1 | me | `app/models.py`, `app/sub_agents/*.py` (output-schema only), `app/chain.py`, `pyproject.toml`, `docs/DECISIONS.md`, `docs/STAGE2_IMPLEMENTATION_PLAN.md` | everything else |
| D2-A | me | `app/sub_agents/{lenses,reconciler,reflector,decompose}.py`, `app/agent.py`, `tests/integration/test_parallel_smoke.py` | grounding, runners, models |
| D2-B | me | `scripts/spanner_up.sh`, `app/ingest/spanner_schema.sql` | sub_agents |
| D3-A | judge-panel subagent | `app/sub_agents/judge_panel.py`, `app/sub_agents/judge.py`, `tests/integration/test_judge_panel.py` | everything else |
| D3-B | docai subagent | `app/ingest/docai.py`, `tests/integration/test_docai.py` | everything else |
| D4 | me | `app/grounding.py`, `app/ingest/graph_extractor.py`, `app/ingest/pipeline.py`, `app/observability/run_log.py`, `app/runners.py`, `app/sub_agents/reflector.py` | UI, discovery, models |
| D5-A | discovery subagent | `app/discovery/*`, `deployment/discovery/*`, `tests/integration/test_discovery.py` | sub_agents, grounding, models |
| D5-B | me | `app/fast_api_app.py`, `app/templates/*.html`, `app/discovery/subscriber.py` | discovery service code (D5-A's lane) |
| D6 | me | deployment YAMLs, `README.md` (deploy section), `agent.json` if needed | code |
| D7-A | sim subagent | `tests/eval/evalsets/curator.evalset.json` (append-only) | everything else |
| D7-B | me | `app/optimization/run_gepa.py`, `docs/OPTIMIZATION_LOG.md`, the decompose/judge prompts | infra |
| D8-A | diagram subagent | `docs/submission/architecture.{md,svg}` | everything else |
| D8-B | devpost subagent | `docs/submission/devpost_fields.md` | everything else |
| D8-C | hygiene subagent | `README.md`, `LICENSE` | everything else |

`app/models.py` frozen after D1 EOD. `app/runners.py` frozen after D4 EOD (only `log_run` wiring). Stubs (`stub_*`) never touched.

---

## Gate definitions

- **Gate 1 (D3 EOD):** Multi-perspective `decompose` + `judge` panels working under real-LLM through `LoopAgent`/`ParallelAgent`/`Reconciler`/`Reflector`. Confidence + missing_evidence emitted by all 5 sub-agents. `python -m app.chain` (stub) regression-clean. `agents-cli eval run` ≥0.7 on all 5 rubrics.
- **Gate 2 (D4 EOD):** Spanner ingestion live for `02` vs `03`. `agent_runs` table populated on every real-LLM call. Reflector successfully re-queries Spanner on injected low-confidence. Offline path green.
- **Gate 3 (D6 EOD) — SUBMITTABLE FLOOR:** Cloud Run × 2 deployed (chain + discovery). A2A card lists 5–6 skills. Discovery Inbox UI shows auto-triggered runs. Uploaded-PDF UI shows debated decompose results. Four Track-3 mandates met. Offline regression green. **Tagged `gate-3` and pushed.**
- **Gate 4 (D9 EOD):** Devpost submission complete with architecture, written fields, video. One Agent-Optimizer (GEPA or SimplePromptOptimizer) pass demonstrably improved at least one rubric on the 30-case evalset; before/after captured in `docs/OPTIMIZATION_LOG.md`.

---

## Risk register additions (extending legacy §4)

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R13 | `ParallelAgent` of LLM sub-agents misbehaves inside `Runner.run_async` event stream | medium | high | D2 morning 50-line smoke harness de-risks. Fallback: `asyncio.gather` over 4 manual `run_agent` calls. |
| R14 | GEPA optimizer undocumented / unstable | medium | medium | D7 morning 2-hour spike. Fallback: `SimplePromptOptimizer` same module. Hard budget cap $30. |
| R15 | RBI RSS feed unreachable / malformed at demo time | low | medium | Cache 5 previous items in Spanner before D6 demo. If feed is down on D6, demo Inbox shows cached items. |
| R16 | Cloud Run cold-start ugly in live demo | low | low | `--min-instances=1` post Gate-3 on chain service only (~$5/day, within budget). |
| R17 | Spanner asia-south1 vector-index creation slow (~5 min) | medium | low | Warm during D2-B during off-peak; index creation issued before D4 begins. |
| R18 | Subagent file-scope violation (touches forbidden file) | medium | medium | `git diff --stat` after every subagent; revert + re-spawn with tighter brief. Already legacy-plan policy. |

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

## Critical files (entry points for implementation)

- `/home/nvidia/bs/agent-regchange/app/chain.py` — orchestration shim
- `/home/nvidia/bs/agent-regchange/app/runners.py` — runner + `log_run` wiring (D4)
- `/home/nvidia/bs/agent-regchange/app/models.py` — schema freeze D1
- `/home/nvidia/bs/agent-regchange/app/sub_agents/decompose.py` — first panel
- `/home/nvidia/bs/agent-regchange/app/sub_agents/judge.py` — second panel
- `/home/nvidia/bs/agent-regchange/app/grounding.py` — SpannerGraphBackend
- `/home/nvidia/bs/agent-regchange/app/fast_api_app.py` — UI + Inbox
- `/home/nvidia/bs/agent-regchange/scripts/spanner_up.sh` + `app/ingest/spanner_schema.sql` — D2 infra
- `/home/nvidia/bs/agent-regchange/docs/STAGE2_IMPLEMENTATION_PLAN.md` — first-thing mirror target

Existing reusable scaffolding:
- `run_agent` retry/JSON-repair at `app/runners.py:137-186` — reuse, do not rewrite.
- `MockGroundingBackend` at `app/grounding.py:49-125` — keep working as airlock.
- `PolicyMatch.confidence` at `app/models.py:121` — pattern to mirror in other models.
- `inout/*.html.json` sidecars — bypass Doc AI for D3 smoke.

---

## Verification

End-to-end checks at each gate (in order, each gate runs all preceding-gate checks too):

**Gate 1:**
```bash
.venv/bin/python -m app.chain    # stub regression, must match canonical line
CURATOR_REAL_LLM=1 .venv/bin/python -m app.chain    # debated real chain
.venv/bin/python -m pytest tests/unit tests/integration -q
.venv/bin/adk eval app tests/eval/evalsets/curator.evalset.json --config_file_path=tests/eval/eval_config.json
# Inspect: all 5 rubrics ≥0.7; obligation count from debated decompose > stub count
```

**Gate 2:**
```bash
bash scripts/spanner_up.sh    # idempotent
CURATOR_GROUNDING=spanner CURATOR_REAL_LLM=1 .venv/bin/python -m app.ingest.pipeline \
    data/fixtures/source_pdfs/02_*.pdf data/fixtures/source_pdfs/03_*.pdf
# Verify: agent_runs has rows for every sub-agent invocation
gcloud spanner databases execute-sql curator --instance=curator-graph \
    --sql="SELECT agent_name, COUNT(*), AVG(confidence) FROM agent_runs GROUP BY 1"
```

**Gate 3:**
```bash
# After adk deploy cloud_run --service_name=curator-chain ... and curator-discovery ...
curl https://<chain-url>/.well-known/agent.json | jq '.skills | length'    # expect 5–6
curl https://<chain-url>/health
curl https://<discovery-url>/health
# Browser: open /inbox; verify ≥1 auto-discovered item (manually trigger /poll if needed)
# Browser: upload 02 + 03 PDFs via /; verify debated obligation list + ImpactSummary
# A2A inspector: tools/a2a-inspector/ → point at chain URL → confirm skill list
```

**Gate 4:**
```bash
.venv/bin/python app/optimization/run_gepa.py --budget-usd=25 --target=decompose
# Inspect docs/OPTIMIZATION_LOG.md: before/after rubric scores, delta > 0 on at least one rubric
# Re-open Devpost submission as anonymous viewer; confirm video + diagram + fields all visible
```

---

**First execution step after approval:** mirror this plan into `docs/STAGE2_IMPLEMENTATION_PLAN.md` (replacing the existing file; archive previous as `docs/STAGE2_IMPLEMENTATION_PLAN.v1.md`) and commit before starting D1's schema work.
