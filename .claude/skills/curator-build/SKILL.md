---
name: curator-build
description: Operational knowledge for building the Curator Stage-2 agent — a Google ADK regulatory-change-intelligence agent for the Google for Startups AI Agents Challenge (Track 3). Use when working anywhere under ~/bs/agent/ on tasks involving ADK, agents-cli, Spanner Graph, A2A, Document AI, Cloud Run deploys, or the decompose/map/diff/judge/qna agent chain. Triggers on "curator agent", "stage 2", "agent platform", "ADK", "agents-cli", "spanner graph", "A2A agent", "regulatory change", and any reference to the build plan or the gates.
---

# Curator — Build Operations Skill

This skill bundles the durable, project-specific knowledge needed to work the Curator Stage-2 build effectively. Read it whenever you start a session in `~/bs/agent/` or when any of the trigger keywords above appear.

For the deep reference (architecture details, ADK code patterns, API costs, etc.), open `docs/RESEARCH_NOTES.md`. For decisions already made, open `docs/DECISIONS.md`. For the canonical multi-phase plan, open `CURATOR AGENT BUILD PLAN.md`. **This skill is the operating manual; those three files are the encyclopedia.**

## 0. Two hard rules that override everything else

1. **The IP boundary is absolute.** Nothing from the production `bbb` / Curator system (14-stage pipeline, deontic extraction, Matryoshka embeddings, Milvus/Neo4j/TSDB, Tailscale mesh, Azure/AWS) enters this repo. Ever. The submission is a separate, smaller agent built on standard public GCP only.
2. **The deadline is `2026-06-05 17:00 PT` and fixed.** Scope flexes; the date doesn't. Always optimize for *submittable at Gate 3*, then make it win.

## 1. Project orientation

- **Identity:** Curator — Regulatory Change Intelligence Agent. Judge uploads **two PDFs**; agent ingests, builds a per-document knowledge graph, runs a 5-step chain (decompose → map → diff → judge → qna), returns a comparison + change log + actionables + Q&A.
- **Hackathon:** Google for Startups AI Agents Challenge, Track 3 (Refactor for Cloud Marketplace & Gemini Enterprise). Mandates: Cloud Run runtime, Gemini reasoning, A2A interop, B2B.
- **Repo:** `~/bs/agent/`. Branch: **`stage-2`** (never commit to `main` during stage work). Python 3.11 via `uv`.
- **GCP project:** `curator-research` (id same). Service account: `curator-ai-engine@curator-research.iam.gserviceaccount.com` (role `Owner`). Key at `.secrets/SA_aidnicloudcurator.json` (gitignored).

## 2. Environment setup — first thing every session

```bash
cd ~/bs/agent
source scripts/env.sh           # sets GOOGLE_APPLICATION_CREDENTIALS + Gemini env vars
```

That export sets:
- `GOOGLE_APPLICATION_CREDENTIALS=$REPO/.secrets/SA_aidnicloudcurator.json`
- `GOOGLE_CLOUD_PROJECT=curator-research`
- `GOOGLE_CLOUD_LOCATION=global`   ← Gemini location, **not** a regional value
- `GOOGLE_GENAI_USE_VERTEXAI=True`

If you see `DefaultCredentialsError` or `404` on Gemini, the env vars are wrong, not the model name.

## 3. The command surface

### Daily

| Need | Command |
|---|---|
| Run offline deterministic chain | `uv run python -m app.chain` |
| Unit + integration tests | `uv run python -m pytest tests/unit tests/integration -q` |
| Interactive ADK CLI | `uv run adk run app` |
| Local web UI | `~/.local/bin/agents-cli playground` |
| Single prompt | `~/.local/bin/agents-cli run "<prompt>"` |
| Lint | `~/.local/bin/agents-cli lint` |

### Evaluation loop (Phase 1, expect 5–10 iterations)

```bash
~/.local/bin/agents-cli eval run
# or:
.venv/bin/adk eval app tests/eval/evalsets/curator.evalset.json \
    --config_file_path=tests/eval/eval_config.json
```

### Infrastructure (Phase 2+ — require user approval before running)

| Step | Command |
|---|---|
| Provision Terraform-managed prereqs | `agents-cli infra single-project` |
| Add Cloud Run deployment target | `agents-cli scaffold enhance --deployment-target cloud_run` |
| Deploy | `agents-cli deploy` |
| Deploy A2A directly via ADK | `adk deploy cloud_run --service_name=curator-a2a --project=curator-research --region=asia-south1 --trace_to_cloud --otel_to_cloud --with_ui --a2a .` |
| CI/CD scaffold | `agents-cli infra cicd` |
| Register in Gemini Enterprise | `agents-cli publish gemini-enterprise` |

**Never run deploys without explicit user sign-off.** Per CLAUDE.md Phase 5.

## 4. Architecture cheat-sheet (Phase 2 target)

```
Upload 2 PDFs
  → Document AI Layout Parser   (chunks preserving tables/headers)
  → Gemini + LLMGraphTransformer (per-document knowledge graph)
  → Spanner Graph (asia-south1)  (GraphRAG store; KNN + ANN)
  → ADK chain: decompose → map → diff → judge → qna
  → Cloud Run + A2A (Gemini reasoning, A2A-exposed)
```

Sub-agent contracts live in `app/models.py` — `AmendmentInput`, `AmendedClause`, `Obligation` + `DeonticType`, `PolicyMatch` (CoverageLevel = full/partial/missing/stale/contradicts), `PolicyDiff`, `ImpactSummary`, `AgentState`. Treat these as the authoritative typed boundary.

## 5. Key code patterns

**Wrap the existing root agent for A2A** (Phase 3):
```python
from google.adk.a2a.utils.agent_to_a2a import to_a2a
app = to_a2a(_root_agent)   # exposes /.well-known/agent.json
```

**Spanner toolset for an ADK agent** (Phase 2):
```python
from google.adk.tools.spanner.spanner_credentials import SpannerCredentialsConfig
from google.adk.tools.spanner.settings import SpannerToolSettings, Capabilities
from google.adk.tools.spanner.spanner_toolset import SpannerToolset
import google.auth

creds, _ = google.auth.default()
toolset = SpannerToolset(
    credentials_config=SpannerCredentialsConfig(credentials=creds),
    spanner_tool_settings=SpannerToolSettings(capabilities=[Capabilities.DATA_READ]),
)
```

**New grounding backend** (replaces `VertexRagBackend` per DECISIONS-2): implement `SpannerGraphBackend(GroundingBackend)` in `app/grounding.py`. Keep `MockGroundingBackend` working — offline tests must still pass.

## 6. The five phases & their gates

| Phase | Output | Gate (don't pass until this is true) |
|---|---|---|
| 0 | Reconciled docs, env, APIs enabled | `STAGE1_ACTUAL.md`, `DECISIONS.md`, offline chain green. **DONE.** |
| 1 | Real Gemini reasoning in all 5 sub-agents, on mock data | `adk run app` runs full real-LLM chain on fixtures; evalset passes at a high bar; fan-out visible & correct |
| 2 | Runtime two-PDF GraphRAG ingestion | Upload 2 PDFs → graphs in Spanner Graph → chain end-to-end → correct comparison; mock path still green |
| 3 **(submittable floor)** | Cloud Run + A2A + UI + observability | Deployed URL; A2A-exposed; Gemini; B2B; judge can upload 2 PDFs and get full output. **Tag this commit.** |
| 4 | Devpost assets (video, diagram, write-up) | Submission complete on Devpost, verified by re-opening as a viewer |
| 5 | Polish to win | Each improvement on its own branch; revert if it doesn't help; never break Gate 3 |

**Cut Phase 5 depth first if behind. Then Phase 4 polish. Never ship past Gate 3 quality without submitting.**

## 7. Decision discipline

Every non-obvious choice goes into `docs/DECISIONS.md` as an `DECISIONS-N` entry: decision, why, open follow-ups. This file is also the raw source for the Devpost "Findings & learnings" field. Don't skip it — Phase 4 will be painful otherwise.

## 8. Common gotchas

- **Model 404:** Check `GOOGLE_CLOUD_LOCATION` — must be `global` for Gemini, not `us-central1`. Don't change the model string.
- **ADK tool imports:** import the tool instance, not the module: `from google.adk.tools.load_web_page import load_web_page`.
- **Terraform 409:** use `terraform import` rather than retrying creation.
- **Spanner Graph in `asia-south1`:** unconfirmed in public docs (404). Attempt it; fall back to `us-central1` if creation fails. Note the result in `DECISIONS.md`.
- **Repeated error 3+ times:** stop, find the root cause; don't keep retrying.
- **Two binaries for the CLI:** `agents-cli` and `google-agents-cli` are both installed and identical (uv tool entrypoints). Use `agents-cli`.
- **Authlib / pluggable-auth warnings** on agent build: cosmetic; ignore.

## 9. When to consult — not duplicate — research

- For architectural detail or exact code patterns: `docs/RESEARCH_NOTES.md`.
- For "why did we choose X": `docs/DECISIONS.md`.
- For the full multi-phase plan and gates: `CURATOR AGENT BUILD PLAN.md`.
- For ADK API surface: `https://adk.dev/`. For agents-cli: `https://google.github.io/agents-cli/`.
- For the GraphRAG reference: `https://docs.cloud.google.com/architecture/gen-ai-graphrag-spanner`.

If you find yourself rediscovering something already in those files, stop and read them. If you discover something new, append to `RESEARCH_NOTES.md` and (if it changes behavior) record a decision in `DECISIONS.md`.

## 10. Commit hygiene

- `stage-2` branch only; tag the Gate-3 commit.
- Commit often; clear, why-focused messages.
- Don't push without explicit user approval.
- Don't commit `.secrets/`, `.env`, or any `bbb`/Curator-proprietary artefact.
