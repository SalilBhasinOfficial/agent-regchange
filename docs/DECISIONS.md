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

## DECISIONS-5 — agents-cli installed as a uv tool, version 0.1.3

**Date:** 2026-05-18
**Decision:** Installed `google-agents-cli` via `uv tool install google-agents-cli` (resulting binary at `~/.local/bin/agents-cli`). The corresponding ADK is `adk 1.33.0`.
**Why:** Matches the CLAUDE.md guidance, gives an isolated tool environment, and surfaces both `agents-cli` and `google-agents-cli` entrypoints. `uvx google-agents-cli setup` is the alternative one-shot, but `uv tool install` is more durable across sessions.
