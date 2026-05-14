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

## License
Apache 2.0 (inherited from `agents-cli` scaffold).
