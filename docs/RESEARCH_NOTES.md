# Research Notes — Curator Stage 2

Snapshot of everything discovered during Phase 0 research about Google's
Agent Platform / ADK / agents-cli / Spanner Graph / A2A / Document AI
landscape as of **May 2026**. Single-file reference; update as the build
progresses and reality shifts.

Sources are linked inline; a consolidated source list is at the bottom.

---

## 1. The platform: Gemini Enterprise Agent Platform

- **Vertex AI Agent Builder was rebranded to Gemini Enterprise Agent Platform** at Cloud Next 2026. Same underlying services, no migration required.
- Surfaces:
  - **Agent Studio** — no-code agent designer.
  - **Agent Development Kit (ADK)** — code-first multi-agent framework. **ADK 1.0 GA** in Python, Go, Java, TypeScript.
  - **Agent Engine** — managed runtime (alternative to Cloud Run for ADK agents). Sessions + Memory Bank are GA.
  - **Cloud API Registry** — central catalogue of approved tools for agents (governance layer).
  - **Agent Registry** — Gemini Enterprise listing target (`agents-cli publish gemini-enterprise`).
- For Track 3 of the Google for Startups AI Agents Challenge: **Cloud Run is the explicitly named runtime mandate**, so we deploy there, not Agent Engine. A2A is mandatory.

## 2. ADK — the framework we're on

- Local install in this repo: `adk 1.33.0` (system binary at `/usr/local/bin/adk`).
- Imports already used: `google.adk.agents.Agent`, `google.adk.apps.App`, `google.adk.models.Gemini`.
- **Agent loop primitives:** sequential / parallel / loop / hierarchical multi-agent composition; typed tools; built-in eval framework (evalsets + LLM-as-judge); local dev UI; one-command Cloud Run / GKE / Agent Engine deploy.
- **Spanner toolset** (added in ADK Python 1.11.0+): `SpannerToolset` exposes `list_table_names`, `list_table_indexes`, `list_table_index_columns`, `list_named_schemas`, `get_table_schema`, `execute_sql`, `similarity_search`. Instantiation pattern:
  ```python
  from google.adk.tools.spanner.spanner_credentials import SpannerCredentialsConfig
  from google.adk.tools.spanner.settings import SpannerToolSettings, Capabilities
  from google.adk.tools.spanner.spanner_toolset import SpannerToolset
  import google.auth

  creds, _ = google.auth.default()
  spanner_toolset = SpannerToolset(
      credentials_config=SpannerCredentialsConfig(credentials=creds),
      spanner_tool_settings=SpannerToolSettings(capabilities=[Capabilities.DATA_READ]),
  )
  ```
- **A2A wrapper** is in-tree: `from google.adk.a2a.utils.agent_to_a2a import to_a2a`. Wrap any `Agent` and you get an A2A-discoverable HTTP app with an auto-generated card.

## 3. agents-cli — the project toolchain

- Installed: `google-agents-cli 0.1.3` via `uv tool install google-agents-cli`. Resulting binary at `~/.local/bin/agents-cli`. Alternative one-shot: `uvx google-agents-cli setup`.
- Full subcommand list (from `agents-cli --help`):
  | Command | Purpose |
  |---|---|
  | `create` | Scaffold a new agent project from a template. |
  | `scaffold` | Subcommands: `enhance` (add deployment / CI-CD / RAG), `upgrade` (bump CLI version). |
  | `infra` | Subcommands: `single-project` (Terraform-managed prerequisites), `cicd` (staging+prod + CI/CD), `datastore` (RAG datastore). |
  | `install` | Install project deps (`uv sync`). |
  | `lint` | Ruff over the project. |
  | `playground` | Local ADK dev UI at `http://localhost:8080`. |
  | `run` | One-shot prompt against the agent. |
  | `eval` | Subcommands: `run` (evaluate against evalsets), `compare` (diff two eval runs). |
  | `data-ingestion` | Run the ingestion pipeline for RAG agents. |
  | `deploy` | Push to Cloud Run / configured target. |
  | `publish` | `gemini-enterprise` registers in the Agent Registry. |
  | `login` | Authenticate (GCP or AI Studio). |
  | `info` | Show project + CLI config (we used this to confirm region `us-east1`). |
  | `setup` | Install skills into supported coding agents. |
  | `update` | Force-reinstall skills. |
- **Auth model:** picks up Application Default Credentials automatically. `GEMINI_API_KEY` is the AI Studio fallback. The current setup uses ADC via the service-account key (DECISIONS-3).
- The plan's CLAUDE.md asserts `agents-cli playground` is the canonical local-testing surface and `agents-cli eval run` is the canonical eval loop — both confirmed in `--help`.

## 4. Reference GraphRAG architecture (the Phase-2 target)

From Google's *GraphRAG infrastructure for generative AI using Vertex AI and Spanner Graph* (Cloud Architecture Center):

```
[Cloud Storage] --(file uploaded)--> [Pub/Sub topic]
                                          │
                                          ▼
                                  [Cloud Run function]
                                          │
                       ┌──────────────────┼──────────────────┐
                       ▼                  ▼                  ▼
            [Document AI Layout    [Gemini + LangChain   [Vertex AI
             Parser — chunks]      LLMGraphTransformer   Embeddings
                                   — entities + edges]   — vectors]
                                          │
                                          ▼
                                   [Spanner Graph]
                                          │
                                          ▼  (query time)
                                   [ADK Agent]
                                          │
                                          ▼
                                   [Vertex AI Search Ranking]
```

**Components and roles:**
- **Cloud Storage** — landing zone for uploaded PDFs.
- **Pub/Sub** — fan-out trigger for the Cloud Run ingestion function.
- **Cloud Run function** — orchestrates Document AI → Gemini → Spanner writes.
- **Document AI Layout Parser** — chunks the PDF preserving tables/headings.
- **Gemini + `LLMGraphTransformer`** — derives entity-and-relationship triples per chunk.
- **Vertex AI Embeddings (`text-embedding-005`)** — vectorizes nodes/chunks for similarity search.
- **Spanner Graph** — stores the knowledge graph and vector index. KNN (exact, brute-force) + ANN (indexed, scalable) both supported.
- **Vertex AI Search Ranking API** — re-ranks combined graph-search + vector-search results at query time.

**Required APIs** to enable for this pipeline: `aiplatform`, `documentai`, `spanner`, `run` (and `cloudbuild` for source deploys), `pubsub`, `storage`, `logging`, `monitoring`, `cloudtrace`. On `curator-research` today, **all of these are enabled** (Spanner and Cloud Build were enabled during Phase 0).

**Region note:** Cloud Run respects the chosen region for residency. Spanner Graph's region availability for `asia-south1` was not directly confirmable from public docs (the regions page 404'd); we'll attempt `asia-south1` first in Phase 2 and fall back to `us-central1` if Spanner Graph rejects it. Recorded in DECISIONS-2.

## 5. Concrete Spanner-as-RAG pattern (what the ingestion writes)

From Karthi Thyagarajan's *Building a RAG agent using Google ADK + Spanner*:

- **Embedding model** is created inside Spanner as a remote model pointing at Vertex AI:
  ```sql
  CREATE MODEL EmbeddingsModel INPUT(content STRING(MAX))
  OUTPUT(embeddings STRUCT<statistics STRUCT<truncated BOOL, token_count FLOAT32>, values ARRAY<FLOAT32>>)
  REMOTE OPTIONS (
    endpoint = '//aiplatform.googleapis.com/projects/<PROJECT_ID>/locations/us-central1/publishers/google/models/text-embedding-005'
  );
  ```
- **Bulk embedding generation** uses partitioned DML:
  ```sql
  UPDATE products p1
  SET productDescriptionEmbedding =
    (SELECT embeddings.values FROM ML.PREDICT(MODEL EmbeddingsModel,
      (SELECT productDescription AS content FROM products p2 WHERE p2.productId = p1.productId)))
  WHERE categoryId = 1;
  ```
- **At query time the agent has two options:**
  1. `SpannerToolset.similarity_search(...)` — high-level, takes the query string, embedding column, top_k, distance type.
  2. `SpannerToolset.execute_sql(...)` with a hand-written KNN query — full control.

The same pattern generalizes to graph-shaped data — we replace `products` with the regulatory-clause graph schema in Phase 2.

## 6. A2A protocol — the Track-3 interoperability mandate

- **A2A v1.0 is GA** as of Cloud Next 2026; ~150 organisations in production.
- ADK has native support — wrap the root agent with `to_a2a()` and the result is a discoverable A2A app.
- **Minimal example** (from Mandie Quartly's deploy guide):
  ```python
  from google.adk.agents.llm_agent import Agent
  from google.adk.a2a.utils.agent_to_a2a import to_a2a
  import os, google.auth

  _, project_id = google.auth.default()
  os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
  os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
  os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

  root_agent = Agent(model="gemini-2.5-flash", name="root_agent", ...)
  app = to_a2a(root_agent)   # exposes the agent card at /.well-known/agent.json
  ```
- **Cloud Run deploy command** (ADK 1.x):
  ```bash
  adk deploy cloud_run \
    --service_name=curator-a2a \
    --project=curator-research \
    --region=asia-south1 \
    --trace_to_cloud --otel_to_cloud --with_ui --a2a \
    .
  ```
  Flags worth knowing: `--trace_to_cloud` (Cloud Trace), `--otel_to_cloud` (OTEL→Cloud), `--with_ui` (web UI), `--a2a` (A2A surface).
- **Agent card** is auto-generated at `/.well-known/agent.json` from agent metadata. An `agent.json` file in-repo can override.
- **A2A inspector tool** (`tools/a2a-inspector/`, already gitignored) is the local validator for compliance.

## 7. Document AI Layout Parser

- **Pricing (2026):** $10 / 1,000 pages for the initial chunking pass; $0.02 / 1,000 pages for re-chunking already-parsed documents. The Gemini Layout Parser is the premium tier — best table extraction, higher cost.
- **Python SDK:** `pip install --upgrade google-cloud-documentai`. The key output field for RAG is `document.chunked_document.chunks`. Each chunk preserves the source layout context (tables/headers).
- **Knobs:** optional `CHUNK_SIZE` parameter controls tokens per chunk.
- **Two integration paths:**
  1. **Vertex AI RAG Engine integration** — Document AI Layout Parser feeds chunks directly into a RAG Engine corpus. (We *don't* use this — DECISIONS-2 — but worth knowing.)
  2. **Direct API call** in our Cloud Run ingestion function — we want this path so we can route chunks through `LLMGraphTransformer` and into Spanner Graph ourselves.

## 8. Authentication patterns that work in this repo

- **Local dev:** `source scripts/env.sh` sets `GOOGLE_APPLICATION_CREDENTIALS` to `.secrets/SA_aidnicloudcurator.json`. ADC then resolves to `curator-ai-engine@curator-research.iam.gserviceaccount.com` (role `Owner`).
- **Cloud Run runtime:** mount the same SA via `--service-account=curator-ai-engine@curator-research.iam.gserviceaccount.com` on the deploy command; do **not** ship the key in the image.
- **CI:** same SA via Workload Identity Federation when we set up GitHub Actions in Phase 5 (out of scope for now).

## 9. Open questions / unresolved details

1. **Spanner Graph in `asia-south1`** — public docs page is 404. Empirically test by creating an instance there; fall back to `us-central1` if it fails.
2. **`LLMGraphTransformer` vs. a more ADK-native option** — the reference architecture uses LangChain's transformer. ADK doesn't (yet) ship a first-party graph extractor. Phase-2 research will revisit; for now, plan on LangChain.
3. **Vertex AI Search Ranking API** — referenced in the GraphRAG architecture but not strictly required for the demo. Treat as Phase-5 polish.
4. **Comparison mode** — supports both version-pair and cross-document; demo defaults to version-pair (DECISIONS-4). Phase-1 prompt branching is unimplemented.
5. **MCP Toolbox vs. raw Spanner queries** — Neo4j codelab leans on MCP Toolbox for pre-validated Cypher. ADK Spanner toolset is enough for our scale; revisit only if reliability evals show LLM-generated SQL failing.

## 10. Critical "do not break" rules (lifted from the build plan)

- **IP boundary:** nothing from the production `bbb` Curator pipeline goes anywhere near this repo. No 14-stage pipeline, no deontic extraction, no Matryoshka embeddings, no Milvus/Neo4j/TSDB, no Tailscale, no Azure.
- **Model name:** `gemini-flash-latest` (from `app/agent.py`). Don't change unless asked — CLAUDE.md is explicit.
- **`GOOGLE_CLOUD_LOCATION` for Gemini:** `global` (not a regional value). If you see 404s, fix the location, not the model.
- **Reasoning model must be Gemini** (Track 3 mandate). Third-party LLMs only via Agent Platform.
- **Runtime must be Cloud Run or GKE** (Track 3 mandate). Cloud Run is the choice.
- **A2A is mandatory** (Track 3 mandate).
- **Public repo, OSI license, no secrets** at submission time.

---

## Consolidated source list

- [Gemini Enterprise Agent Platform (product page)](https://cloud.google.com/products/gemini-enterprise-agent-platform)
- [Agent Builder release notes](https://docs.cloud.google.com/agent-builder/release-notes)
- [Tool governance — Cloud API Registry](https://cloud.google.com/blog/products/ai-machine-learning/new-enhanced-tool-governance-in-vertex-ai-agent-builder)
- [agents-cli on GitHub](https://github.com/google/agents-cli)
- [agents-cli docs site](https://google.github.io/agents-cli/)
- [agents-cli getting started](https://google.github.io/agents-cli/guide/getting-started/)
- [Gemini Enterprise ADK + agents-cli quickstart](https://docs.cloud.google.com/gemini-enterprise-agent-platform/agents/quickstart-adk)
- [ADK 1.0 GA / A2A v1.0 announcement](https://cloud.google.com/blog/products/ai-machine-learning/agent2agent-protocol-is-getting-an-upgrade)
- [ADK docs (canonical, post-redirect)](https://adk.dev/)
- [ADK Spanner integration](https://adk.dev/integrations/spanner/)
- [Building a RAG agent using Google ADK + Spanner](https://medium.com/google-cloud/building-a-rag-agent-using-google-adk-spanner-2acebbf80403)
- [The Surprisingly Simple Way to Create an A2A Agent with ADK (Mandie Quartly)](https://medium.com/google-cloud/surprisingly-simple-a2a-agents-with-adk-using-to-a2a-deploy-to-cloud-run-and-gemini-enterprise-e815bdef4a32)
- [Build and deploy an A2A agent on Cloud Run](https://docs.cloud.google.com/run/docs/deploy-a2a-agents)
- [Overview of A2A agents on Cloud Run](https://docs.cloud.google.com/run/docs/ai/a2a-agents)
- [GraphRAG infrastructure on Vertex AI + Spanner Graph](https://docs.cloud.google.com/architecture/gen-ai-graphrag-spanner)
- [Document AI Layout Parser quickstart](https://docs.cloud.google.com/document-ai/docs/layout-parse-quickstart)
- [Document AI Layout Parser — chunking guide](https://docs.cloud.google.com/document-ai/docs/layout-parse-chunk)
- [Codelab: Multi-Agent A2A with ADK + Cloud Run + Gemini CLI (xbill)](https://medium.com/google-cloud/multi-agent-a2a-with-the-agent-development-kit-adk-cloud-run-and-gemini-cli-52f8be838ad6)
- [Codelab: Neo4j ADK GraphRAG agents](https://codelabs.developers.google.com/neo4j-adk-graphrag-agents)
