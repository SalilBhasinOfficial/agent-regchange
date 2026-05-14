# Stage 2 — Plan

Stage 1 delivered a runnable, deterministic skeleton with real ADK
`Agent` definitions and clean seams. Stage 2 turns it into the live
hackathon submission.

## Checklist

### A. Replace stubs with real agent-node logic

For each sub-agent in `app/sub_agents/`:

- [ ] `decompose.py` — replace `stub_decompose` with a Gemini call.
      Structured output validated against `Obligation`. Few-shot
      examples for clause fan-out (climate buffer, ICAAP cadence,
      board reporting) lifted from `data/fixtures/`.
- [ ] `map_.py` — replace `stub_map` with retrieval over the bank's
      policy corpus, then a Gemini classification against the five
      coverage levels. Calibrate `confidence`.
- [ ] `diff.py` — replace `stub_diff` with Gemini edit synthesis.
      Preserve numbering and tone. Constrain to JSON-schema output.
- [ ] `judge.py` — replace `stub_judge` with Gemini reasoning over
      the full `AgentState`. Maintain a curated downstream-effects
      checklist (ICAAP, capital plan, Pillar 3 templates, RMC agenda,
      training, audit trail, vendor contracts) and force the model
      to consider each one.
- [ ] `qna.py` — replace `stub_qna` with a Gemini call grounded in
      `AgentState` plus retrieval over the underlying corpus.

The orchestrator's `__getattr__` lazy-build pattern is already
correct — no changes needed there.

### B. Vertex AI RAG Engine wiring

- [ ] Provision a RAG corpus per tenant: one for RBI Master
      Directions (shared), one for the bank's internal policies
      (tenant-scoped).
- [ ] Region: `us-central1` (RAG Engine managed Spanner allow-list).
      **Residency review before ingesting Indian-resident regulatory
      data.**
- [ ] Implement `VertexRagBackend` in `app/grounding.py` against the
      Vertex AI RAG Engine retrieval API. Surface source citations
      into `RetrievalHit['source']` so `qna_agent` can cite them.
- [ ] Flip `get_backend()` to return `VertexRagBackend` when
      `CURATOR_GROUNDING=vertex` env var is set; keep
      `MockGroundingBackend` for tests.
- [ ] Run `agents-cli data-ingestion` to populate the corpus.

### C. A2A interface

- [ ] `agents-cli scaffold enhance --base-template adk_a2a` to add
      A2A wiring without losing the current Cloud Run scaffold.
- [ ] Publish an Agent Card for `root_agent` advertising the five
      sub-agents as A2A skills.
- [ ] Authentication: bearer token from Secret Manager.

### D. Cloud Run deployment

- [ ] `agents-cli infra single-project` to set up the GCP project's
      Terraform-managed prerequisites.
- [ ] `agents-cli deploy` to push the image.
- [ ] Validate `/health` and a single `adk run` round-trip from the
      deployed URL before declaring deploy success.
- [ ] CI/CD: `agents-cli infra setup-cicd --cicd-runner github_actions`
      with branch protection on `main`.

### E. Agent Observability + Simulation + Optimizer

- [ ] Agent Observability: enable BigQuery Agent Analytics (the
      `--bq-analytics` flag from `agents-cli create`) on the deployed
      service. Dashboards: turn-latency, tool-call mix,
      coverage-distribution, missing-obligation rate.
- [ ] Agent Simulation: build a simulation set from historical RBI
      amendments (mine `bbb`/`rbi` history). Replay against the chain
      nightly; alert on regressions against the eval rubric
      thresholds.
- [ ] Agent Optimizer: run `adk optimize` with GEPA over each
      sub-agent's instruction prompt. Lock the optimized prompts
      behind a version flag.

### F. Agent Registry listing

- [ ] Register `curator` in Gemini Enterprise Agent Registry via
      `agents-cli publish gemini-enterprise`.
- [ ] Provide an Agent Card with the chain's safety constraints
      surfaced as `policies` (proposal-only, human-in-the-loop).

### G. Eval expansion

Stage 1 has 5 thin cases. Stage 2:

- [ ] Add 5+ cases per node (25+ total) covering edge cases:
      contradictory coverage, stale policy, cross-policy
      dependencies, non-binding ("should") obligations.
- [ ] Add adversarial cases (amendment with no real change; clause
      with embedded reference to a withdrawn circular).
- [ ] Tighten rubric thresholds to 0.85.

### H. Stage-1 carry-overs

- [x] ~~`pyproject.toml` declares `packages = ["app","frontend"]` for
      the wheel build, but no `frontend` package exists.~~ Fixed in
      Stage 1 — wheel packages is now `["app"]` only.
- [ ] `tests/eval/evalsets/basic.evalset.json` and the sample
      `README.md` were removed (Stage 1). The eval-set selector is
      hard-wired to `curator.evalset.json` — make this configurable.

## Stage-2 dependencies on me (the user)

1. A GCP project with billing enabled and the IAM permissions to
   create RAG corpora, Cloud Run services, and Spanner instances.
2. The exact tenant id taxonomy for multi-tenant grounding (one corpus
   per bank, or shared with per-tenant filters?).
3. Sign-off on residency: Vertex AI RAG Engine's managed Spanner is
   not in `asia-south1` today; is `us-central1` acceptable for the
   demo? If not, fall back to Vertex AI Search (which has
   `asia-south1` regions).
4. Access to a richer set of historical RBI amendments for the
   Simulation set — the Stage-1 fixture is one amendment.
