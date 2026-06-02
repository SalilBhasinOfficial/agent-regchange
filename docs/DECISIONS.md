# Curator — Decisions Log

Append-only log of every non-obvious choice made during the Stage-2 build,
with rationale. Source material for the Devpost **Findings & learnings** field.

---

## DECISIONS-1 — Branch: `stage-2`, off `main` at `46bbf06`

**Date:** 2026-05-18
**Decision:** All Stage-2 work happens on a dedicated `stage-2` branch. `main` stays at Stage-1 quality until a successful Gate-3 cut.
**Why:** The build plan §0 mandates this; it preserves a known-good fallback if any phase goes sideways.

---

## DECISIONS-2 — Grounding backend: Spanner Graph, not Vertex AI RAG Engine

**Date:** 2026-05-18
**Decision:** The Stage-2 grounding backend is **Spanner Graph** (runtime GraphRAG over two uploaded PDFs), provisioned in `asia-south1` if available, falling back to `us-central1` otherwise. The existing `VertexRagBackend` stub will be replaced by a new `SpannerGraphBackend` implementing the same `GroundingBackend` ABC.
**Why:**
- The new build plan supersedes `docs/STAGE2_PLAN.md` — the corpus-seeded RAG-Engine approach is abandoned.
- Spanner Graph supports the runtime two-document GraphRAG architecture the demo is built around.
- Spanner Graph in `asia-south1` (Mumbai) gives a clean residency story for Indian regulatory data; Vertex AI RAG Engine's managed store is restricted to `us-central1/east1/east4`.
- The Google Cloud reference architecture for GraphRAG (Cloud Architecture Center: *GraphRAG infrastructure for generative AI using Vertex AI and Spanner Graph*) confirms Spanner Graph as the canonical store.
**Open:** Region for the first Spanner instance — to be set on first Phase-2 provisioning. Default attempt: `asia-south1`.

---

## DECISIONS-3 — Service-account auth, not user ADC

**Date:** 2026-05-18
**Decision:** The agent and CLI tooling authenticate via the project's service-account JSON (`curator-ai-engine@curator-research.iam.gserviceaccount.com`, role: `Owner`) sourced from `.secrets/SA_aidnicloudcurator.json` via the `GOOGLE_APPLICATION_CREDENTIALS` environment variable.
**Why:**
- The SA has `roles/owner`, so it can provision and deploy without falling back to the user account.
- Avoids accidental coupling to a developer's personal `gcloud auth application-default login`.
- Same credential is reusable in CI / Cloud Run (mount as secret, set env var).
- Key file is gitignored (`.secrets/`) — never committed.

---

## DECISIONS-4 — Comparison mode default: support both, demo version-pair

**Date:** 2026-05-18
**Decision:** The agent supports two comparison modes:
1. **Version-pair** (regulation v1 vs v2) — the demo path. Decompose targets *amended* clauses.
2. **Cross-document** (regulation vs internal policy) — the “gap-coverage” path. Decompose targets every binding clause in the regulation; map targets policy coverage.

A `comparison_mode` field on `AmendmentInput` (or a new `ComparisonInput` wrapper) selects which prompt branch to use in `decompose` and `map`.
**Why:** Plan §1.6 leaves this open with a default. The version-pair case is the more legible demo moment (the fan-out is anchored on what *changed*), while the cross-document case is the more commercially interesting B2B story. Supporting both costs little (a prompt branch), and the Devpost write-up can lean on whichever is stronger after Phase 1.
**Implementation note:** Phase 1 should add the field to the pydantic contract and branch the decompose/map prompts; default value = `"version_pair"`.

---

## DECISIONS-6 — Spanner Graph region: `asia-south1` only

**Date:** 2026-05-18
**Decision:** Spanner Graph is provisioned **only in `asia-south1`**. No fallback to `us-central1`. Verified `regional-asia-south1` instance config is available on `curator-research` via `gcloud spanner instance-configs list`.
**Why:** User direction. The Indian-residency story is core to the BFSI Track-3 narrative; we accept the risk of having to debug any asia-south1-specific Spanner Graph quirks rather than weaken it.
**Implication:** If a Spanner-Graph-only feature lands us-only mid-build, we either work around it or surface a hard blocker to the user immediately.

---

## DECISIONS-7 — Spanner provisioning cadence: spin up / spin down per session

**Date:** 2026-05-18
**Decision:** Do NOT leave a Spanner instance running for the whole build. Provision it at the start of each session, tear it down at session end. Helpers: `scripts/spanner_up.sh` (create instance, create database, apply schema) and `scripts/spanner_down.sh` (delete instance).
**Why:** Cost discipline — user preference. Estimated total Stage-2 Spanner cost falls from ~$180 to ~$50 across 18 days. The ~10 min per-session bootstrap is acceptable.
**Implication:** Graph data is ephemeral between sessions. Phase 2 ingestion must therefore be **fast** (target: <2 min per PDF re-ingestion); Phase 3 deploy needs an automatic schema-bootstrap step on Cloud Run cold start.

---

## DECISIONS-8 — Demo PDFs: 4 public RBI publications, intake complete

**Date:** 2026-05-18
**Decision:** Demo corpus is four public RBI documents, now staged at `data/fixtures/source_pdfs/`. See `data/fixtures/source_pdfs/README.md` for the full intake metadata. Sourcing path resolved: user staged the PDFs directly (option B from STAGE2_IMPLEMENTATION_PLAN §5.1) — fastest, IP-clean. Only the PDFs are used in the project; the parallel `.html`, `.md`, and `.json` sidecars at the staging path are reference-only and not part of the agent's working corpus.

**The four files:**

  - `02_second_amendment_2026-02-13_RBI-dbecd9fe73f6.pdf` — Second Amendment Directions, 2026 (1.3 MB)
  - `03_third_amendment_2026-03-10_RBI-aaafe4b91697.pdf` — Third Amendment Directions, 2026 (350 KB)
  - `04_master_direction_AFTER_2026-03-10_RBI-0d6a477d11ba.pdf` — Master Direction on Prudential Norms on Capital Adequacy, post-Third-Amendment consolidation (2.0 MB)
  - `05_credit_risk_standardised_2026-04-27_RBI-087798ec1547.pdf` — Capital Charge for Credit Risk – Standardised Approach Directions, 2026 (892 KB)

**Important constraint from intake:** RBI overwrites Master Direction URLs in place. There is **no byte-perfect pre-Third-Amendment MD snapshot** anywhere (S3, Wayback, or RBI's own site). The post-Third MD (`04`) is the only MD available. This forces a *different* demo pair than originally planned:

**Updated demo pairings:**
  - **Primary (Phase 1–3 demo):** `02` vs `03` — two consecutive amendments to the same MD. Clean version-pair, no missing pre-state problem. Decompose the Third Amendment's clauses, map against the Second Amendment's clauses, surface what was added/changed.
  - **Alternative (amendment-vs-doc):** `03` (the amendment notification) vs `04` (the resulting consolidated MD). Demonstrates "trace this amendment back into the document it modifies."
  - **Phase 5 cross-corpus moment:** `04` vs `05` — capital-adequacy MD vs the new Capital Charge SA Directions. "How do the new Basel III SA Directions interact with the existing capital-adequacy regime?"

**Implication for the plan:** §0.1 of the build plan describes the input as "two PDFs (typically two versions of a regulation)". With the intake constraint, our flagship pair is amendment-vs-amendment rather than v1-vs-v2 of the MD itself — but the agent logic is identical (decompose changed clauses, map against the prior instrument, diff, judge, qna). The narrative shifts slightly: "diff this amendment against the previous one to surface what's *new* this time" — which is arguably the more interesting commercial question anyway, since compliance teams care most about the marginal change.

---

## DECISIONS-5 — agents-cli installed as a uv tool, version 0.1.3

**Date:** 2026-05-18
**Decision:** Installed `google-agents-cli` via `uv tool install google-agents-cli` (resulting binary at `~/.local/bin/agents-cli`). The corresponding ADK is `adk 1.33.0`.
**Why:** Matches the CLAUDE.md guidance, gives an isolated tool environment, and surfaces both `agents-cli` and `google-agents-cli` entrypoints. `uvx google-agents-cli setup` is the alternative one-shot, but `uv tool install` is more durable across sessions.

---

## DECISIONS-9 — Region split: Vertex AI `us-central1`, Spanner `asia-south1`

**Date:** 2026-06-02
**Decision:** Vertex AI initialisation (`vertexai.init(project=..., location=...)` in `app/agent.py` and runner adapters) stays on **`us-central1`**. Spanner Graph stays on **`asia-south1`** per DECISIONS-6. These are unrelated regions — Vertex AI region only affects model-serving endpoints and Vertex API metadata; Spanner region governs data residency. Keeping them split is correct, not a drift.
**Why:** Avoids the recurrent confusion of "the code says us-central1 but DECISIONS-6 says asia-south1." Documenting the split here closes that gap. The Indian-residency narrative depends only on Spanner being in `asia-south1` — `gemini-flash-latest` is served via `global` model routing anyway, so the Vertex region label is largely cosmetic.
**Implication:** No code change required today. Cloud Run service deploy (D6) will be in `asia-south1` to co-locate compute with Spanner data; Document AI Layout Parser is `us` location (only available there).
