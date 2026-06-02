# Curator Stage 2 — Implementation Plan

**Status:** Draft for sign-off, advisor-reviewed, output_schema spike succeeded. Phase 0 is complete (committed on `stage-2`).
**Target:** Cloud Run + A2A + Gemini agent submitted to the **Google for Startups AI Agents Challenge** (Track 3) by **2026-06-05 17:00 PT** (~18 days from today).
**Strategy:** Hit Gate 3 (submittable floor) at **day 10** to leave a 5-day polish/contingency buffer; submit Gate 4 by **day 13**; spend the rest on polish for the win.

### Pre-plan verifications done today

- **`output_schema=list[Obligation]` works** with `gemini-flash-latest` via `InMemoryRunner` — returned 2 validated `Obligation` objects from the CRCB clause including the fan-out. Step 1.1 below stays small.
- **LICENSE file added** at repo root (Apache 2.0). Phase 4 hygiene risk eliminated.
- **Demo orchestration path decided:** the demo and the deployed Cloud Run service run the **deterministic Python chain in `app/chain.py` swapped to call `real_*` sub-agent runners**. The ADK `root_agent` with delegating `sub_agents=[...]` stays in the repo (for `adk run app` exploration) but is **not the demo path**. ADK delegation routing is a Phase-5 enhancement. This is the advisor's recommendation — reliability > "agentic" appearance.
- **UI pattern decided:** **FastAPI + Jinja** (single Cloud Run service co-located with the A2A surface), not Streamlit. One deploy target, one URL, simpler Gate 3.
- **Phase 1 fan-out bar tightened:** real-LLM decompose must produce *strictly more* obligations than the stub on the fixture **and** capture at least one fan-out the stub flattens (e.g., the `material change` branch of the quarterly ICAAP clause).
- **Comparison-mode scope tightened:** Phase 1 implements **version-pair only**; cross-document is a Phase-5 enhancement and doesn't appear in the demo.
- **Cost cap set to $200** total Stage-2 spend; manual Spanner teardown when stepping away >4h.
- **Push to `origin` after each Gate** (1, 2, 3) is now policy, not ambiguity. SA key gitignored; safe.
- **A2A multi-skill exposure** to be verified during Phase 1 (not Phase 3) via the a2a-inspector against a locally-wrapped root.

---

## 0. Reference point — restating the goal so the plan stays anchored

### 0.1 What we are building (the product)

Curator is a regulatory-change-intelligence agent. A judge uploads **two PDFs** (typically v1 vs v2 of an RBI/SEBI Master Direction; optionally regulation vs internal policy). The agent:

1. Ingests both PDFs at runtime — no pre-seeded corpus.
2. Builds a knowledge graph from each document via **Document AI Layout Parser → Gemini → Spanner Graph**.
3. Decomposes amended clauses into multiple atomic **Obligations** (this fan-out is the signature innovation moment).
4. Maps each obligation against the other document (full / partial / **missing** / stale / contradicts).
5. Drafts clause-level **diffs** with rationale.
6. **Judges** impact/priority and surfaces non-obvious downstream effects.
7. Answers grounded follow-up **Q&A** with citations.

### 0.2 Hackathon constraints (Track 3 — non-negotiable)

- Runtime on **Cloud Run** (or GKE) — we pick Cloud Run.
- Reasoning on **Gemini** (or 3rd-party LLMs only through Agent Platform).
- **A2A protocol** interoperability.
- **B2B** focus.
- Public repo, OSI license, judge-runnable.

### 0.3 Hard rules

- **IP boundary:** zero `bbb` / Curator-proprietary content (no 14-stage pipeline, deontic methodology, Matryoshka embeddings, Milvus/Neo4j/TSDB, Tailscale, Azure). Standard public GCP services only.
- **Model:** `gemini-flash-latest` (don't change unless explicitly asked). Location: `global` for Gemini.
- **Submittable at every gate.** Each phase must leave Gate-3 functionality intact.
- **No regressions to offline path.** `MockGroundingBackend` and the stub-driven `app/chain.py` must keep passing after every change — that's our airlock.

### 0.4 Latest-developments delta (May 2026, refreshed today)

- Vertex AI → **Gemini Enterprise Agent Platform** (rebrand at Cloud Next 2026; no migration needed).
- Agent Engine → **Agent Runtime** (rename; supports custom containers, sub-second cold starts, long-running ops up to 7 days). We still target **Cloud Run** because Track 3 mandates it.
- **A2A v1.0 GA** (~150 orgs in production); ADK ships `to_a2a()` wrapper.
- ADK has a **graph-based framework** for sub-agent networks — we will *not* rebuild around it for Stage 2 (timebox); we'll use sequential delegation per the current `root_agent` shape.
- Spanner Graph in **asia-south1**: still unconfirmed via public docs. Will probe empirically in Phase 2 (Step 2.1); fallback `us-central1`.

---

## 1. Current state (post-Phase 0, verified today)

| Layer | State | File(s) |
|---|---|---|
| Branch | `stage-2`, 2 commits ahead of `main` | — |
| Env / auth | Service account active; `scripts/env.sh` exports `GOOGLE_APPLICATION_CREDENTIALS` | `scripts/env.sh`, `.secrets/SA_aidnicloudcurator.json` |
| GCP APIs | All needed APIs enabled (`aiplatform`, `documentai`, `spanner`, `run`, `cloudbuild`, `pubsub`, `storage`, `cloudtrace`, `discoveryengine`, `secretmanager`, `artifactregistry`, …) | — |
| CLI tooling | `agents-cli 0.1.3`, `adk 1.33.0` | — |
| Data contracts | `AmendmentInput`, `AmendedClause`, `Obligation` + `DeonticType`, `PolicyDocument`/`PolicySection`, `PolicyMatch`, `PolicyDiff`, `ImpactSummary`, `AgentState`, `QnATurn` — all pydantic, strict | `app/models.py` |
| Sub-agent ADK objects | All 5 sub-agents have real ADK `Agent(...)` factories with quality instructions; each also has a deterministic `stub_*` function | `app/sub_agents/{decompose,map_,diff,judge,qna}.py` |
| Orchestrator | Root agent with `sub_agents=[...]` wiring; lazy `vertexai.init()` and `google.auth.default()` | `app/agent.py` |
| Offline chain | `python -m app.chain` works; produces `4 clauses → 6 obligations → 6 matches (1 missing) → 5 diffs → priority medium` | `app/chain.py` |
| Grounding | `MockGroundingBackend` reads fixtures; `VertexRagBackend` is a stub to be **replaced** by `SpannerGraphBackend` (per DECISIONS-2) | `app/grounding.py` |
| Fixtures | 1 amendment (4 clauses, fans out to 6 obligations), 2 master directions, 4 bank policies, manifest | `data/fixtures/` |
| Eval | 5-case evalset + 5-rubric LLM-as-judge config | `tests/eval/evalsets/curator.evalset.json`, `tests/eval/eval_config.json` |
| Tests | 4 passed, 4 skipped | `tests/{unit,integration}/` |
| Docs | `STAGE1_ACTUAL.md`, `DECISIONS.md` (5 entries), `RESEARCH_NOTES.md`, `.claude/skills/curator-build/SKILL.md` | `docs/`, `.claude/` |

### 1.1 Key code-level observations that shape the plan

- **Two orchestration patterns coexist** today: (a) ADK delegation via `root_agent.sub_agents=[...]` (used by `adk run app`); (b) Python sequential pipeline in `app/chain.py` calling `stub_*`. We will keep both. The ADK path becomes the live agent; the chain path remains the deterministic offline harness. **No code path is deleted.**
- **The `stub_*` functions are surprisingly capable** — they already produce the canonical fan-out (e.g. CRCB → 2 obligations). They are an honest baseline, not throwaway. We keep them as the offline reference and the regression fence.
- **Sub-agent instructions are already real**, not "TODO". Phase 1 work is mostly: (i) shape structured output, (ii) build a runner adapter, (iii) iterate prompts against the evalset.

---

## 2. The plan — phases, gates, and orchestration

### Phase 1 — Real Gemini reasoning on mock data (target: **2 days**, days 1–2)

**Goal:** make all 5 sub-agents produce real, validated, structured output via Gemini, still grounded on `MockGroundingBackend` and `data/fixtures/`. The fan-out moment must be visibly correct without any hand-coded heuristic.

#### 1.1 Build shared runner scaffolding (sequential, me)

**Why first:** all 5 sub-agents need identical plumbing — ADK Runner setup, structured-output parsing, error handling. Building this once prevents 5 divergent implementations.

**Deliverables:**
- New `app/runners.py` — defines `run_agent(agent, input_payload, output_schema) -> pydantic_model | list[pydantic_model]`. Uses `google.adk.runners.Runner` under the hood. Handles retries, JSON repair, schema validation.
- `app/__init__.py` exports the new helper.
- Env flag `CURATOR_REAL_LLM={0,1}` (default 0, preserving offline behavior).
- Smoke test: `tests/integration/test_runner_adapter.py` — single-shot Gemini call returning a schema-validated `Obligation`. Skipped when `CURATOR_REAL_LLM=0`.

**Definition of done:** runner adapter passes the new smoke test under `CURATOR_REAL_LLM=1`; offline tests untouched.

#### 1.2 Implement `decompose` as the gold standard (sequential, me + 1 subagent for prompt iteration)

**Why next, alone:** the fan-out moment is the demo's key innovation. Set the bar here; then parallelize the rest using this pattern.

**Deliverables:**
- `real_decompose(clauses) -> list[Obligation]` in `app/sub_agents/decompose.py`. Same signature as `stub_decompose`. Keep `stub_decompose` intact.
- Update the ADK `decompose_agent` `build_agent()` to wire `output_schema=list[Obligation]` (or equivalent structured-output pattern — verify exact ADK API in `app/runners.py` work).
- Few-shot examples for fan-out (CRCB → steady + phase-in; Pillar-3 → policy + template) baked into the instruction.
- New eval cases (3+) probing fan-out depth.
- Run `agents-cli eval run` against just the decompose rubric → ≥0.7 score.
- **A2A multi-skill verification (advisor's point 2):** wrap `root_agent` with `to_a2a()` locally and confirm the agent card lists distinct skills for the 5 sub-agents. If it doesn't, hand-write `agent.json` enumerating them. ~1 hour, done during Phase 1.

**Subagent brief:** "Iterate the decompose instruction against the evalset; measure rubric scores; report best-of-5 prompt." Self-contained; in/out clearly defined.

**Definition of done:** real-LLM decompose produces **strictly more obligations than `stub_decompose`** on the fixture amendment AND captures at least one fan-out the stub misses (suggested target: the "immediately upon any material change" branch of clause #7 — the stub flattens it to one obligation); rubric ≥0.7. Cut work as soon as both are true — do not over-iterate.

#### 1.3 Parallelize the remaining 4 sub-agents (4 subagents in parallel)

**Why parallel:** once 1.1 and 1.2 set the pattern, the per-agent work is largely independent — different files (`map_.py`, `diff.py`, `judge.py`, `qna.py`), different prompts, different schemas. Shared files (`app/models.py`, `app/grounding.py`, `app/runners.py`) are frozen at this point.

**Orchestration:**
- Spawn 4 `general-purpose` subagents in one message (max parallelism).
- Each gets the same template brief: "Implement `real_<X>` paralleling `stub_<X>` in `app/sub_agents/<X>.py`. Pattern: see how decompose does it (path provided). Constraints: do not edit any file outside `app/sub_agents/<X>.py` and the corresponding test file. Use the existing instruction string; refine if needed. Validate output via pydantic. Report rubric score from `agents-cli eval run`."
- Each subagent owns exactly one file in `app/sub_agents/` and one matching test file in `tests/integration/`. Zero file overlap.
- I monitor: run `pytest` and `agents-cli eval run` after each subagent reports complete; spot-check the prompts.

**Definition of done (each):** real path implemented; rubric ≥0.7 on that node's rubric; offline `stub_*` path still callable.

#### 1.4 Wire the real path into the chain runner (sequential, me)

**Deliverables:**
- `app/chain.py`: when `CURATOR_REAL_LLM=1`, call `real_*` functions; else call `stub_*`. Single shim function `pick_decompose / pick_map / ...`.
- Same signature so callers don't change.
- Smoke: `CURATOR_REAL_LLM=1 python -m app.chain` produces a sensible end-to-end output.

#### 1.5 Expand the evalset (1 subagent)

**Subagent brief:** "Expand `tests/eval/evalsets/curator.evalset.json` from 5 to **15** cases. Coverage targets: 3 fan-out cases, 3 missing-coverage cases, 2 contradictory-coverage cases, 2 stale-policy cases, 2 multi-hop Q&A cases, 3 downstream-effect cases. Use only existing fixtures or extend `data/fixtures/` minimally. Do not edit any code."

**Why 15 not 25:** each case costs tokens to grade; 15 gives meaningful breadth without bloating run time. We expand further in Phase 5.

#### 1.6 Prompt tuning loop (sequential, me — iterative)

Run `agents-cli eval run` repeatedly; tighten prompts per the rubric reports. **Stop when all 5 rubrics ≥0.7 simultaneously — do NOT iterate past that.** Move to Phase 2 immediately; further prompt polish belongs to Phase 5.

#### Gate 1 (regression-prevented):

- `uv run python -m app.chain` (offline, `stub_*`) → identical summary line as today. **Mandatory.**
- `CURATOR_REAL_LLM=1 uv run adk run app` → full real-LLM chain produces correct fan-out on the fixture.
- `agents-cli eval run` → all 5 rubrics ≥0.7.
- `pytest tests/unit tests/integration -q` → green.
- Commit tag: `gate-1`.

---

### Phase 2 — Runtime GraphRAG ingestion (target: **4 days**, days 3–6)

**Goal:** replace fixtures with real two-PDF runtime ingestion through Document AI → Gemini graph construction → Spanner Graph.

#### 2.1 Provision Spanner Graph (sequential, me, with user approval)

**Why first:** schema, ingestion, and backend all depend on a live Spanner instance. Provisioning is destructive enough to require user approval.

**Deliverables:**
- Try `gcloud spanner instances create curator-graph --config=regional-asia-south1 --processing-units=100 ...`. If asia-south1 is rejected, retry with `regional-us-central1`. Record outcome in `DECISIONS.md` as DECISIONS-6.
- Create database `curator` with the schema designed in 2.2.
- Document teardown command (`gcloud spanner instances delete curator-graph`) and rough cost (~$0.40/hr for 100 PUs in regional; ~$10/day if left up).
- **Cost discipline:** plan to use a single dev instance, idle-shutdown disabled (Spanner doesn't support pause). Document the manual teardown when done.

#### 2.2 Design the graph schema (1 subagent, careful review)

**Subagent brief:** "Design a Spanner Graph schema that stores: (i) clause-and-obligation nodes per uploaded document, (ii) policy section nodes for the second document if it's a policy, (iii) edges for `CONTAINS`, `OBLIGATES`, `AMENDS`, `MAPS_TO`, `CONFLICTS_WITH`, (iv) text + vector embedding (768-dim, text-embedding-005) on each node. Produce SQL DDL, an ER diagram (Mermaid), and a brief rationale. Constraints: don't touch other files; output ONLY a new `app/ingest/spanner_schema.sql` and an addendum to `RESEARCH_NOTES.md`."

**I review:** check it matches our pydantic data contracts; sanity-check indexing.

#### 2.3 Build the ingestion modules (2 subagents in parallel)

**Subagent A — Document AI integration:**
- Brief: "Implement `app/ingest/docai.py` with `parse_pdf(path) -> list[ChunkedSection]`. Use `google-cloud-documentai` SDK against the Layout Parser processor in `us` location. Output preserves `chunk.text`, `chunk.layout_type`, `chunk.page_span`. Constraints: own only `app/ingest/docai.py` + `tests/integration/test_docai.py`. The test must skip when `CURATOR_LIVE_GCP=0`."

**Subagent B — Gemini graph extractor:**
- Brief: "Implement `app/ingest/graph_extractor.py` with `extract_graph(chunks) -> GraphTriples` using Gemini structured output (entity, relationship, target). Use LangChain `LLMGraphTransformer` for the reference pattern, but verify a more ADK-native option doesn't exist first; record choice. Constraints: own only `app/ingest/graph_extractor.py` + matching test."

**I monitor:** check that subagent B doesn't inadvertently choose a dependency that conflicts with subagent A's choices; resolve at integration time.

#### 2.4 Implement `SpannerGraphBackend` (1 subagent, sequential after 2.2 & 2.3)

**Subagent brief:** "Implement `SpannerGraphBackend(GroundingBackend)` in `app/grounding.py`, replacing the `VertexRagBackend` stub. Use `app/ingest/spanner_schema.sql` for the schema and ADK's `SpannerToolset` + raw `google-cloud-spanner` SDK for writes. Functions required: `ingest_document(pdf_path, doc_id, namespace) -> None`, `search_md`, `get_md_text`, `get_amendment_text`, `load_policies`. Constraints: own only `app/grounding.py`. Keep `MockGroundingBackend` working unchanged. Add factory switch via `CURATOR_GROUNDING={mock,spanner}` env var."

#### 2.5 Wire the ingestion pipeline (sequential, me)

- Add `app/ingest/pipeline.py` with `ingest_two_pdfs(pdf_a, pdf_b, namespace) -> AgentState`.
- Update `app/chain.py` so that when `CURATOR_GROUNDING=spanner`, the chain starts from the ingestion pipeline instead of fixtures.
- End-to-end smoke test: ingest `data/fixtures/master_directions/MD-RBI-CAP-2025.md` (converted to PDF) + the amendment → chain runs through to ImpactSummary.

#### 2.6 Demo PDFs — already staged (no work needed)

The four RBI PDFs are already in `data/fixtures/source_pdfs/` (see DECISIONS-8 and the per-file README). Phase 2 ingestion targets the **`02` vs `03` pair** for the primary demo and end-to-end smoke. `04` is treated as the *reference corpus that those amendments modify* — useful for citations in Q&A. `05` is held back for the Phase-5 cross-corpus moment.

#### Gate 2 (regression-prevented):

- Upload the 2 real PDFs → graphs in Spanner → chain runs end-to-end → correct comparison + change log + actionables.
- Offline `stub_*` chain still produces the canonical summary line (no regression).
- `pytest` green; new integration tests in `tests/integration/test_ingestion.py` pass with `CURATOR_LIVE_GCP=1`.
- Commit tag: `gate-2`.

---

### Phase 3 — Cloud Run + A2A + UI + Observability (target: **4 days**, days 7–10). **THIS IS THE SUBMITTABLE FLOOR.**

**Goal:** judge can hit a public URL or run `adk deploy cloud_run` on a clean checkout and get the full experience.

#### 3.1 A2A wrap (sequential, me)

**Deliverables:**
- Update `app/agent.py`: add `app = to_a2a(root_agent)` (or expose a separate `a2a_app` symbol — verify what `adk deploy cloud_run --a2a` expects). Verify the agent card is auto-generated at `/.well-known/agent.json`.
- Add `agent.json` (manual override) only if the auto-generated card is insufficient.
- Validate locally via the A2A inspector (already gitignored at `tools/a2a-inspector/`).

#### 3.2 First Cloud Run deploy (sequential, me, user approval gate)

**Why user approval:** deploys are visible state changes; cost; rollbacks are manual.

**Deliverables:**
- Run `~/.local/bin/agents-cli infra single-project` to provision Terraform-managed prerequisites (Cloud Run service, Artifact Registry, IAM bindings). Record outputs.
- Run `adk deploy cloud_run --service_name=curator-a2a --project=curator-research --region=<spanner-region-from-2.1> --trace_to_cloud --otel_to_cloud --with_ui --a2a --service_account=curator-ai-engine@curator-research.iam.gserviceaccount.com .`
- Validate `/health`, `/a2a/<name>`, `/.well-known/agent.json`, `/dev-ui` endpoints respond.

#### 3.3 Minimal UI — FastAPI + Jinja (1 subagent, parallel with 3.2)

**Subagent brief:** "Extend `app/fast_api_app.py` with three Jinja-rendered routes: (1) `GET /` — upload form for two PDFs; (2) `POST /analyse` — kicks off the chain, shows ingestion progress (HTMX or SSE polling), then renders the final ImpactSummary, diffs table, and a Q&A chat box; (3) `POST /qna` — stateless Q&A turn against the current AgentState. Templates in `app/templates/`. Constraints: own only `app/fast_api_app.py`, `app/templates/*.html`, `tests/integration/test_ui_smoke.py`. Style: clean, monospace, no marketing. The agent is the star, not the UI."

**Why FastAPI + Jinja (not Streamlit):** single Cloud Run service co-located with A2A; one URL judges hit; one deploy command; the existing scaffold already gives us `app/fast_api_app.py` as a head-start. Streamlit-style polish is Phase-5 if time allows.

#### 3.4 Observability surfacing (sequential, me, 30 min)

- `--trace_to_cloud --otel_to_cloud` flags (3.2) already wire Cloud Trace.
- Add a single Markdown note to README pointing judges at `console.cloud.google.com/traces?project=curator-research` for the reasoning trace. This visible trace is strong Technical-Implementation evidence.

#### 3.5 Smoke test the deployed system end-to-end (sequential, me)

- Upload the 2 real PDFs through the deployed UI → verify the full output.
- Verify A2A discovery works from `tools/a2a-inspector/`.
- Run `agents-cli eval run --target=deployed` (if supported) or invoke the deployed URL with cURL.

#### Gate 3 — SUBMITTABLE FLOOR. Tag this commit `gate-3`.

- Deployed Cloud Run URL works.
- A2A-discoverable.
- Gemini reasoning.
- B2B.
- A judge can upload 2 PDFs and get the full output.
- All four Track-3 mandates met.
- Offline path still green.

**If anything after Gate 3 slips, the project is still submittable and scores respectably.**

---

### Phase 4 — Devpost submission assets (target: **3 days**, days 11–13; overlaps with end of Phase 3)

#### 4.1 Three parallel subagent tasks

**Subagent A — Architecture diagram:** "Produce `docs/submission/architecture.svg` (or `.png`) showing the runtime GraphRAG pipeline (PDFs → Doc AI → Gemini graph construction → Spanner Graph → ADK chain → Cloud Run + A2A). Use Mermaid syntax in a markdown file, render to SVG, save both. Source: `docs/RESEARCH_NOTES.md` §4."

**Subagent B — Devpost written fields:** "Draft `docs/submission/devpost_fields.md` with: Problem (regulatory change blindness in BFSI), Solution, Technologies, Data sources, Findings & learnings (mine `docs/DECISIONS.md`), Third-party integrations, Business case (Marketplace listing path, BFSI market). Tone: confident, specific, not buzzword-heavy. 1500 words max total."

**Subagent C — Repo hygiene:** "Audit the repo for submission readiness: confirm public-ready (no `bbb` references — grep is enough), Apache 2.0 LICENSE present (it is), README has one-command setup, no secrets in any committed file, no `.env`/`.secrets` artifacts. Report findings; suggest README rewrites where unclear. Constraints: edits to README and LICENSE allowed; no other files."

#### 4.2 Demo video (manual, user-led)

Spec: ~3 min — hook (BFSI regulatory pain) → upload 2 PDFs live → fan-out moment + reasoning trace → architecture diagram + tech stack → business case → close. YouTube public.

I will produce a written script + shot list once Gate 3 is confirmed, but the user records the actual video.

#### 4.3 Submit on Devpost (manual, user — with my support)

48-hour buffer minimum. Submission complete by **2026-06-03 EOD** at the latest.

#### Gate 4

Submission visible on Devpost; all assets attached; verified by re-opening as a viewer.

---

### Phase 5 — Polish to win (days 14–18; everything Phase-5 lives on its own branch)

In rough priority order (highest-leverage first):

1. **Agent Simulation** — generate synthetic comparison scenarios at scale; stress-test the chain.
2. **Agent Optimizer** — feed failure traces in; let it refine prompts. Measure before/after on the evalset.
3. **Deeper fan-out** — make decomposition richer. The Innovation differentiator.
4. **Sharper demo** — re-record if a cleaner run exists.
5. **Output polish** — change log and actionables genuinely compliance-officer-ready.
6. **Marketplace-readiness** — `agents-cli publish gemini-enterprise` and document the path.
7. **Eval breadth** — 15 → 30+ cases; harder edge cases.
8. **Robustness** — weird PDFs, large files, edge cases.

**Rule for Phase 5:** each improvement is its own branch; if it doesn't clearly help, revert. **Never let polish break Gate 3.**

---

## 3. Subagent orchestration discipline

### 3.1 Brief structure (template every subagent gets)

```
Goal: <one sentence — what should be true when you finish>
Files you may edit: <strict allowlist>
Files you must NOT touch: <strict denylist>
Inputs: <pointers to specific docs / files / fixtures>
Constraints: <test that must still pass; rubric to hit; line budget>
Definition of done: <exact criteria>
Report format: <what to send back>
```

### 3.2 File ownership matrix (no two subagents touch the same file in the same phase)

| Phase | Subagent | Owns (edit allowed) | Strictly forbidden |
|---|---|---|---|
| 1.2 | decompose | `app/sub_agents/decompose.py`, `tests/integration/test_decompose_real.py` | everything else |
| 1.3a | map | `app/sub_agents/map_.py`, `tests/integration/test_map_real.py` | "" |
| 1.3b | diff | `app/sub_agents/diff.py`, `tests/integration/test_diff_real.py` | "" |
| 1.3c | judge | `app/sub_agents/judge.py`, `tests/integration/test_judge_real.py` | "" |
| 1.3d | qna | `app/sub_agents/qna.py`, `tests/integration/test_qna_real.py` | "" |
| 1.5 | evalset | `tests/eval/evalsets/curator.evalset.json` | "" |
| 2.2 | schema | `app/ingest/spanner_schema.sql`, append-only to `docs/RESEARCH_NOTES.md` | "" |
| 2.3a | docai | `app/ingest/docai.py`, `tests/integration/test_docai.py` | "" |
| 2.3b | graph_extractor | `app/ingest/graph_extractor.py`, `tests/integration/test_graph_extractor.py` | "" |
| 2.4 | grounding | `app/grounding.py` only | "" |
| 3.3 | ui | `app/fast_api_app.py`, `app/templates/*.html`, `tests/integration/test_ui_smoke.py` | "" |
| 4.1a | diagram | `docs/submission/architecture.*` | "" |
| 4.1b | devpost | `docs/submission/devpost_fields.md` | "" |
| 4.1c | hygiene | `README.md`, `LICENSE` | "" |

### 3.3 Monitoring loop

After every subagent completes:
1. `git diff` — verify file scope honored. If any out-of-scope file changed, revert and re-spawn with tighter brief.
2. Run **regression fence:** `uv run python -m app.chain` + `uv run python -m pytest tests/unit tests/integration -q` — must remain green.
3. Run **phase fence:** `agents-cli eval run` for any node touched.
4. Spot-check the actual code change for correctness, not just passing tests.

### 3.4 Concurrency policy

- Parallel: only when file ownership is disjoint AND the work is conceptually independent.
- Sequential: anything touching `app/models.py`, `app/grounding.py`, `app/runners.py`, `app/chain.py`, `app/agent.py`, or any deployment / infra command.

---

## 4. Risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Spanner Graph not available in asia-south1 | medium | low | fallback to us-central1; document in DECISIONS-6; demo narrative shifts from "residency-clean" to "managed-Spanner-Graph in us-central1" |
| R2 | Sub-agent parallel work conflicts in shared files | medium | medium | strict file-ownership matrix (§3.2); I monitor `git diff` after each subagent; revert on overreach |
| R3 | Real-LLM path flaky → Gate-1 slips | medium | high | keep stub path as airlock; Gate-1 doesn't require deterministic rendering, just "≥0.7 per rubric"; budget time for prompt iteration (Step 1.6) |
| R4 | Document AI Layout Parser cost ($10/1k pages) | low | low | typical regulation is 50–100 pages → ~$1/PDF; cap at 10 ingestion test runs total during build |
| R5 | Cloud Run cold-start unacceptable in demo | low | medium | use `--min-instances=1` after Gate 3 confirmed; budget ~$5/day |
| R6 | Spanner instance left running → cost overrun | medium | medium | scripted teardown at `scripts/spanner_teardown.sh`; manual teardown when stepping away >4h; total Stage-2 budget cap **$200** |
| R7 | Sub-agent context blow-up | low | low | tight briefs (§3.1); cap each subagent at "implement one file"; review prompts before spawning |
| R8 | Deadline slip past Gate 3 | low (with discipline) | catastrophic | submit at Gate 3 quality if behind; never trade off Phase 4 for Phase 5 |
| R9 | Demo PDFs not available / not impressive | medium | medium | source 2 public RBI documents in week 1; have backup synthetic PDFs |
| R10 | Inadvertent IP-boundary leak | low | catastrophic | grep-based pre-commit check (Phase 4 hygiene subagent) for `bbb`, `tailscale`, `milvus`, `neo4j`, `matryoshka` |
| R11 | `output_schema` ADK pattern doesn't work as expected | medium | medium | Step 1.1 is exactly the de-risk for this — implement and test the adapter before touching any sub-agent |
| R12 | Gemini Enterprise rebrand breaks references in code | low | low | code uses `vertexai`, `google.adk`, Cloud Run — all still work; only marketing names changed |

---

## 5. Decisions locked in (sign-off received)

| # | Decision | Choice |
|---|---|---|
| D1 | **Spanner region** | `asia-south1` only. Empirically verified today — `regional-asia-south1` config exists and supports Spanner GoogleSQL (and therefore Spanner Graph). Recorded as DECISIONS-6. |
| D2 | **Spanner cadence** | Spin up/down per dev session. I will add `scripts/spanner_up.sh` and `scripts/spanner_down.sh` in Phase 2.1; ~10 min instance + schema bootstrap per session, but the cost drops to ~$50 over the whole build. |
| D3 | **Repo visibility** | Private until Gate 4. Flip public as part of submission. |
| D4 | **Demo PDFs (target documents)** | Four public RBI publications, **staged at `data/fixtures/source_pdfs/`**: `02_second_amendment` (2026-02-13), `03_third_amendment` (2026-03-10), `04_master_direction_AFTER` (consolidated post-Third-Amendment, 2026-03-10), `05_credit_risk_standardised` (2026-04-27). Full intake metadata in `data/fixtures/source_pdfs/README.md`. |
| D5 | **Demo PDF sourcing path** | **Resolved.** User staged the four PDFs directly into the project. The pre-Third-Amendment MD does NOT exist as a byte-perfect snapshot (RBI overwrites URLs in place; no Wayback copy). Demo version-pair is therefore **`02` vs `03`** (consecutive amendments), not v1-vs-v2 of the MD. Narrative shift: "diff this amendment against the previous one to surface what's marginally new" — arguably the more commercially interesting question. |
| D6 | **Eval breadth Phase 1 → 5** | 15 cases in Phase 1; 30 in Phase 5. Default; you didn't redirect. |
| D7 | **CI / GitHub Actions** | Skip. Default; you didn't redirect. |

### 5.1 PDF intake — resolved

Path B (user staged the four PDFs). All four PDFs now sit at `data/fixtures/source_pdfs/`:

```
data/fixtures/source_pdfs/
├── 02_second_amendment_2026-02-13_RBI-dbecd9fe73f6.pdf
├── 03_third_amendment_2026-03-10_RBI-aaafe4b91697.pdf
├── 04_master_direction_AFTER_2026-03-10_RBI-0d6a477d11ba.pdf
├── 05_credit_risk_standardised_2026-04-27_RBI-087798ec1547.pdf
└── README.md
```

Only the PDFs are part of the project; the parallel HTML/Markdown/JSON sidecars at the user's external staging path are reference-only and not copied in.

**Phase 2 ingestion test path:** Phase 2.5's end-to-end smoke uses `02` vs `03` (the primary demo pair). Phase 5 extends to the `04` vs `05` cross-corpus comparison.

### Things already decided (no input needed)

- Demo orchestration: Python chain (deterministic), not ADK delegation. ADK delegation is Phase 5.
- UI tech: FastAPI + Jinja co-located with A2A on one Cloud Run service.
- Comparison mode: version-pair only in Phase 1; cross-document (D4-d vs D4-c) becomes the Phase-5 cross-corpus moment.
- Model: `gemini-flash-latest` universally per CLAUDE.md.
- Subagent monitoring: auto-review after every code-writing subagent.
- Push to `origin` after each Gate (1/2/3): yes.
- Runtime: Cloud Run (Track 3 mandate), not Agent Runtime.
- A2A multi-skill verification: opportunistic Phase 1, not late discovery in Phase 3.
- LICENSE: Apache 2.0, in place.
- `output_schema=list[Obligation]`: works against `gemini-flash-latest`, verified today.

---

## 6. What I'll do once you sign off

I'll start Phase 1, Step 1.1 (the runner adapter) right after you confirm. The first parallel subagent fan-out happens at Step 1.3, after the decompose template is proven.

Each phase ends with a git-tagged commit and a regression check; I'll surface any deviations from this plan before continuing. The plan itself lives at this path (`docs/STAGE2_IMPLEMENTATION_PLAN.md`) and I'll edit it in place if any phase needs to course-correct.
