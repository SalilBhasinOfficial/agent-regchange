# Curator — Regulatory Change Intelligence Agent

A multi-agent system that takes an RBI regulatory amendment plus the
revised Master Direction and produces, for a bank, the specific
proposed edits to its internal policies and SOPs.

The chain has five steps:

1. **decompose** — break each amended clause into atomic obligations
   (one clause can yield several obligations with different owners
   and timelines — that fan-out is the demo's key moment).
2. **map** — match each obligation against the bank's existing
   policies and SOPs. Coverage is one of: `full`, `partial`, `missing`,
   `stale`, `contradicts`.
3. **diff** — generate concrete suggested policy edits with rationale.
   Proposals only — the agent never applies edits.
4. **judge** — score impact and priority, and surface non-obvious
   downstream effects (capital plan, ICAAP, Pillar 3, training,
   board reporting cadence).
5. **qna** — answer follow-up questions about the analysis, with
   citations to obligation ids and policy section ids.

Built on Google's Agent Development Kit (ADK), scaffolded via
`agents-cli` v0.1.3. Target deployment: Cloud Run. Stage-2 grounding:
Vertex AI RAG Engine.

---

## Stage 1 status

| Step | Status |
|------|--------|
| 1. Environment (Python 3.11, uv) | done |
| 2. Scaffold via `agents-cli create` (`agentic_rag` template, `cloud_run` target) | done |
| 3. DESIGN_SPEC + data contracts (`app/models.py`) | done |
| 4. Multi-agent skeleton — orchestrator + 5 sub-agents, real ADK `Agent` defs | done (stubs) |
| 5. Pydantic models threaded through every node | done |
| 6. Grounding seam — `MockGroundingBackend` works today; `VertexRagBackend` stub | done (mock) |
| 7. Domain fixtures (2 MDs, 1 amendment, 4 bank policies) | done |
| 8. Eval set (5 cases, LLM-as-judge criteria) | done (thin by design) |
| 9. End-to-end deterministic chain | done (`python -m app.chain`) |
| 10. README + STAGE2_PLAN | done |

Stage 2 work — full agent-node logic, Vertex AI RAG Engine wiring,
A2A interface, Cloud Run deploy, Agent Observability + Agent
Simulation + Agent Optimizer, Agent Registry listing — is tracked in
[`docs/STAGE2_PLAN.md`](docs/STAGE2_PLAN.md).

---

## Setup

Requirements: `uv` (which fetches Python 3.11 for you) and, for the
LLM-driven path, the Google Cloud SDK with Application Default
Credentials configured.

```bash
cd ~/bs/agent
uv sync --python 3.11        # creates .venv with all deps
```

### Run the offline deterministic chain (no GCP, no LLM)

The Stage-1 chain executes every node end-to-end on fixture data with
no network calls:

```bash
.venv/bin/python -m app.chain
```

Expected output:

```
amendment=AMD-2026-capital-adequacy | clauses=4 | obligations=4 | matches=4 (missing=1) | diffs=2 | priority=medium
```

### Run the LLM-driven chain (needs GCP auth)

```bash
.venv/bin/adk run app                  # CLI
.venv/bin/agents-cli playground        # web UI
```

Both reach into `app/__init__.py` for the lazy `app` symbol, which
calls `google.auth.default()`. If you haven't set up ADC, you'll see:

```
DefaultCredentialsError: Your default credentials were not found.
```

To fix:

```bash
# 1. Install gcloud (https://cloud.google.com/sdk/docs/install).
# 2. Authenticate:
gcloud auth application-default login
gcloud config set project YOUR_GCP_PROJECT
```

The CLI does not guess your project id; run those two commands
yourself before invoking `adk run` / `agents-cli playground`.

### Tests

```bash
.venv/bin/python -m pytest tests/integration/test_chain_smoke.py tests/unit -q
```

### Eval

```bash
.venv/bin/adk eval app tests/eval/evalsets/curator.evalset.json \
    --config_file_path=tests/eval/eval_config.json
```

The eval set uses the same `gemini-flash-latest` model as the judge;
it requires the same GCP auth as `adk run`.

---

## Project layout

```
~/bs/agent/
├── app/
│   ├── __init__.py               # lazy re-export of `app` / `root_agent`
│   ├── agent.py                  # orchestrator + sub-agent registration
│   ├── chain.py                  # deterministic offline chain runner
│   ├── models.py                 # pydantic data contracts
│   ├── grounding.py              # Mock + Vertex RAG backends
│   ├── retrievers.py             # original scaffold retriever (kept for Stage 2)
│   ├── fast_api_app.py           # scaffold FastAPI wrapper (kept for Cloud Run)
│   ├── app_utils/
│   └── sub_agents/
│       ├── decompose.py          # clause → obligations
│       ├── map_.py               # obligation × policy → match
│       ├── diff.py               # match → suggested edit
│       ├── judge.py              # package → impact summary
│       └── qna.py                # follow-up Q&A
├── data/
│   ├── fixtures/
│   │   ├── master_directions/    # MD-RBI-CAP-2025.md, MD-RBI-KYC-2024.md
│   │   ├── amendments/           # AMD-2026-capital-adequacy.{md,json}
│   │   └── sample_bank_policy/   # 4 bank policies + manifest
│   └── schemas/                  # reference-only schemas (Stage 2)
├── deployment/terraform/         # untouched scaffold (Stage 2 Cloud Run)
├── docs/STAGE2_PLAN.md
├── tests/{unit,integration,eval}/
├── DESIGN_SPEC.md
├── README.md
└── pyproject.toml
```

---

## Stage-2 deployment (Cloud Run × 2)

The Curator stack ships as **two** Cloud Run services that share one container image:

- **`curator-chain`** — the main agent surface. FastAPI UI (upload, Discovery Inbox, impact view, Q&A) + A2A skill card + ADK `/run_sse` + `/feedback`. Front door for judges.
- **`curator-discovery`** — a tiny standalone service that polls a public regulator RSS feed every 30 minutes, dedupes against Spanner, and publishes new items to a Pub/Sub topic that the chain service consumes.

### Prereqs
- A GCP project (`curator-research` in the dev environment) with these APIs enabled: Cloud Run, Cloud Build, Artifact Registry, Pub/Sub, Cloud Scheduler, Spanner, Document AI, Vertex AI.
- A Spanner instance + database with `app/ingest/spanner_schema.sql` applied (use `bash scripts/spanner_up.sh`).
- A Document AI Layout Parser processor in the `us` location. Capture its full resource name.
- A service account (e.g. `curator-ai-engine@…`) with `roles/spanner.client`, `roles/documentai.apiUser`, `roles/pubsub.publisher`, `roles/pubsub.subscriber`, plus the standard Cloud Run defaults.

### One-time setup
```bash
# Pub/Sub topic + subscription
gcloud pubsub topics create curator-discoveries --project=curator-research
gcloud pubsub subscriptions create curator-chain-pull \
    --topic=curator-discoveries --ack-deadline=300 --project=curator-research
```

### Deploy
```bash
# Chain service (UI + A2A + observability + Spanner-backed grounding)
gcloud run deploy curator-chain \
  --source=. \
  --region=asia-south1 \
  --project=curator-research \
  --service-account=curator-ai-engine@curator-research.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --memory=2Gi --cpu=2 --port=8080 \
  --min-instances=0 --max-instances=5 --timeout=600 \
  --set-env-vars="\
GOOGLE_CLOUD_PROJECT=curator-research,\
GOOGLE_CLOUD_LOCATION=global,\
GOOGLE_GENAI_USE_VERTEXAI=True,\
SPANNER_INSTANCE=curator-graph,\
SPANNER_DATABASE=curator,\
CURATOR_AGENT_RUN_LOG=1,\
CURATOR_GROUNDING=spanner,\
CURATOR_REAL_LLM=1,\
CURATOR_DOCAI_PROCESSOR_ID=projects/890675948352/locations/us/processors/4c036f5845e938e7,\
CURATOR_DISCOVERY_SUBSCRIBE=1,\
CURATOR_DISCOVERY_SUBSCRIPTION=curator-chain-pull"

# Discovery service (tiny — RSS poll + Pub/Sub publish only)
gcloud run deploy curator-discovery \
  --source=. \
  --region=asia-south1 \
  --project=curator-research \
  --service-account=curator-ai-engine@curator-research.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --memory=512Mi --cpu=1 --port=8080 \
  --min-instances=0 --max-instances=2 --timeout=120 \
  --command=uv \
  --args="run,uvicorn,app.discovery.service:app,--host,0.0.0.0,--port,8080" \
  --set-env-vars="\
GOOGLE_CLOUD_PROJECT=curator-research,\
SPANNER_INSTANCE=curator-graph,\
SPANNER_DATABASE=curator,\
CURATOR_DISCOVERY_TOPIC=curator-discoveries"

# Cloud Scheduler — every 30 minutes, invoke /poll
DISCOVERY_URL=$(gcloud run services describe curator-discovery \
  --region=asia-south1 --project=curator-research --format='value(status.url)')
gcloud scheduler jobs create http curator-discovery-poll \
  --location=asia-south1 \
  --schedule="*/30 * * * *" \
  --uri="${DISCOVERY_URL}/poll" \
  --http-method=POST \
  --oidc-service-account-email=curator-ai-engine@curator-research.iam.gserviceaccount.com \
  --oidc-token-audience="${DISCOVERY_URL}"
```

### Verify
```bash
CHAIN_URL=$(gcloud run services describe curator-chain --region=asia-south1 --project=curator-research --format='value(status.url)')

curl -sS "${CHAIN_URL}/health"                                       # 200 OK
curl -sS "${CHAIN_URL}/.well-known/agent.json" | jq '.skills | length'  # ≥ 5
# Browser: open ${CHAIN_URL}/ → Curator upload page
# Browser: open ${CHAIN_URL}/inbox → Discovery Inbox (populated after the first scheduler tick)
```

A2A inspector (gitignored at `tools/a2a-inspector/`) can be pointed at `${CHAIN_URL}` to enumerate skills.

### Note on the RSS feed source
RBI's `/Scripts/RssNotification.aspx` endpoint no longer returns RSS XML (returns an ASP.NET error page). The default feed in `app/discovery/rss_poller.py` is **SEBI's** `https://www.sebi.gov.in/sebirss.xml` — same BFSI vertical, valid feed, 30 entries verified as of 2026-06-02. Operators can override via the `CURATOR_RSS_FEED_URL` environment variable.

### Region split (DECISIONS-9)
- **Cloud Run + Spanner Graph**: `asia-south1` (Mumbai). All ingested regulatory text + bank policy data lives in-country.
- **Vertex AI / Gemini-flash**: routed via `global`. Vertex AI region label (`us-central1` in the agent.py constant) is cosmetic.
- **Document AI Layout Parser**: `us` only — the one cross-region call.

---

## Optional A2A bridge to an external corpus

Curator can optionally enrich Q&A answers with snippets from a remote
A2A/MCP gateway over a regulatory corpus. Set:

```bash
export BBB_MCP_BEARER="<token>"
# optional overrides
# export BBB_MCP_ENDPOINT="https://mcp.aidni.cloud/mcp"
# export BBB_MCP_TOOL_NAME="regulatory_deep_lookup"
```

With the bearer set, `real_qna` prepends up to 5 cited snippets to its
prompt before calling Gemini, and the Reflector falls back to the same
gateway when the local Spanner Graph re-query returns nothing.

With the bearer unset (the default for this public repo), every call is
a silent no-op — the offline path and all unit + integration tests stay
green. The bridge is intentionally consume-only: Curator never exposes
the remote corpus' internals; it sees an A2A surface and nothing more.

---

## License
Apache 2.0 (inherited from `agents-cli` scaffold).
