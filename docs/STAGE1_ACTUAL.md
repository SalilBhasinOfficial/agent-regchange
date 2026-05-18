# Stage 1 — Actual State (Phase 0 reconciliation)

Snapshot taken at the start of Stage 2 work, reconciling the
**CURATOR AGENT BUILD PLAN.md** §1.5 against the live codebase.

## What the plan said vs what exists

| Plan §1.5 claim | Reality on disk | Status |
|---|---|---|
| `app/agent.py` — ADK App with 5 sub-agents | Present. Orchestrator + `decompose / map_ / diff / judge / qna`. | ✅ matches |
| Real instruction prompts | `ORCHESTRATOR_INSTRUCTION` is real. Sub-agent prompts are real (TBD: inspect depth in Phase 1). | ✅ matches |
| Lazy GCP-free imports | `app/__init__.py` and `app/agent.py` use PEP-562 `__getattr__` to defer `vertexai.init()` and `google.auth.default()` until `app` / `root_agent` is touched. | ✅ matches |
| `app/models.py` — pydantic contracts | `AmendmentInput`, `AmendedClause`, `Obligation` + `DeonticType`, `PolicyDocument`/`PolicySection`, `PolicyMatch`, `PolicyDiff`, `ImpactSummary`, `QnATurn`, `AgentState` — all present. | ✅ matches |
| `app/grounding.py` — `GroundingBackend` ABC + `MockGroundingBackend` + `VertexRagBackend` stub | All three present. `MockGroundingBackend` reads from `data/fixtures/`. `VertexRagBackend` is a `NotImplementedError` stub. | ✅ matches — but `VertexRagBackend` will be replaced by `SpannerGraphBackend` (see DECISIONS-2). |
| `data/fixtures/` — RBI Capital Adequacy MD, synthetic KYC MD, 1 amendment fanning out across 4 clauses, 4 bank policies | Present: `MD-RBI-CAP-2025.md`, `MD-RBI-KYC-2024.md`, `AMD-2026-capital-adequacy.{md,json}`, `POL-CAP-001 / POL-DISC-003 / POL-ICAAP-002 / POL-RMC-004` + `manifest.json`. | ✅ matches |
| `tests/eval/` — 5-case evalset + LLM-as-judge | `evalsets/` + `eval_config.json` present. | ✅ matches (depth not re-verified) |
| `docs/STAGE2_PLAN.md` — prior Stage-2 checklist | Present. **Superseded** by the new build plan (different runtime architecture). Kept for history. | ⚠️ superseded |
| Offline chain: 4 clauses → 6 obligations → 6 matches (1 missing) → 5 diffs → priority medium | Re-ran today: identical output. | ✅ matches |
| `pytest -q` → 4 passed, 4 skipped | Re-ran today: same. | ✅ matches |

## Files in the repo not mentioned in the plan

- `app/chain.py` — deterministic offline runner exercising the stub functions (`stub_decompose`, etc.). Used by the smoke test, eval harness, and `python -m app.chain`.
- `app/fast_api_app.py`, `app/retrievers.py`, `app/app_utils/` — leftovers from the original `agentic_rag` scaffold; kept for the Cloud Run deploy path.
- `deployment/terraform/` — untouched scaffold.
- `Dockerfile`, `pyproject.toml`, `uv.lock` — uv/Python 3.11 build config.
- `sample_data/getting_started.pdf` — scaffold artifact, not used by the agent.
- `DESIGN_SPEC.md` — Stage-1 design notes.

## Tooling baseline

- `python` 3.11 via `uv` 0.11.14
- `adk` 1.33.0 (system install at `/usr/local/bin/adk`)
- `agents-cli` 0.1.3 (installed today via `uv tool install google-agents-cli`)
- `gcloud` SDK 568.0.0

## GCP project state

- **Project:** `curator-research`
- **Active gcloud account:** `curator-ai-engine@curator-research.iam.gserviceaccount.com` (also `salil@aidni.cloud` available as fallback)
- **Service-account roles on the project:** `roles/owner`
- **Credential file:** `.secrets/SA_aidnicloudcurator.json` (gitignored)
- **ADC mechanism:** `GOOGLE_APPLICATION_CREDENTIALS` env var, set per-shell. Verified: `google.auth.default()` returns project `curator-research`, SA email matches.

## APIs enabled (curator-research)

Already on before Stage 2:
`aiplatform`, `agentregistry`, `artifactregistry`, `bigquery*`, `cloudtrace`, `compute`, `discoveryengine`, **`documentai`**, `iam`, `iamcredentials`, `logging`, `monitoring`, `notebooks`, `observability`, `pubsub`, `run`, `secretmanager`, `serviceusage`, `storage`, plus standard infrastructure APIs.

Enabled today as part of Phase 0:
- `spanner.googleapis.com` (needed for Spanner Graph in Phase 2)
- `cloudbuild.googleapis.com` (needed for `agents-cli deploy` / Cloud Run source builds)
- `generativelanguage.googleapis.com` (optional, AI-Studio fallback path)

## Sanity checks passed today

- `uv run python -m app.chain` → expected one-line summary.
- `uv run python -m pytest tests/unit tests/integration -q` → 4 passed, 4 skipped.
- `google.auth.default()` resolves to the SA on `curator-research`.

## Gate 0 status

All Gate 0 conditions met:
- `docs/STAGE1_ACTUAL.md` exists (this file).
- `docs/DECISIONS.md` initialised.
- Environment + APIs verified.
- Offline chain green.
