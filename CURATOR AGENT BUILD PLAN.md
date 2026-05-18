# Curator Agent — Build Plan to Hackathon Submission

**For:** Claude Code, running in the `~/bs/agent/` working tree
**Owner:** Salil Bhasin, Aidni (sole founder)
**Goal:** Build, submit, and then iteratively improve a Google ADK agent for the
**Google for Startups AI Agents Challenge** — targeting the top prize.

-----

## 0. How to use this document

This is a **plan, not a script**. It gives you context, a target architecture,
a phased sequence, and quality gates. You are expected to:

- **Re-verify everything against reality.** This plan was written from a Stage-1
  *report*, not the live Stage-1 code. Your FIRST job (Phase 0) is to read the
  actual codebase and reconcile it with this plan. Where they differ, trust the
  code and adapt.
- **Research independently.** APIs named here (ADK, Spanner Graph, Document AI
  Layout Parser, Agents CLI) move fast. Before using any API, check current
  docs. If a better service or pattern exists, use it — and note why in
  `docs/DECISIONS.md`.
- **Course-correct.** If a phase reveals the plan is wrong, stop, write down
  what you found, pick the better path, and continue. Don’t follow this plan
  off a cliff.
- **Respect the gates.** Each phase ends with a gate. Do not start the next
  phase until the gate passes. The gates exist so that there is always a
  submittable artifact.
- **Commit often.** Work on the `stage-2` branch. Commit at each checkpoint
  with clear messages. Push regularly. Never work directly on `main`.

When in doubt, optimize for: **a working, submittable, honest demo first** —
polish and winning-grade depth second.

-----

## 1. Context — what this project is and why

### 1.1 The hackathon

- **Google for Startups AI Agents Challenge** (Devpost project #16636).
- **Deadline:** June 5, 2026, 5:00 PM PT. This is hard. Everything else flexes.
- **Track chosen:** Track 3 — *Refactor for Google Cloud Marketplace & Gemini
  Enterprise*.
- **Judging:** Technical Implementation 30%, Business Case 30%, Innovation &
  Creativity 20%, Demo & Presentation 20%.
- **Prizes:** Overall Grand Prize; Best-of-Theme (per track); Regional Winner
  (APAC / EMEA). Target = Grand Prize, with Best-of-Theme (Refactor) and APAC
  Regional as strong fallbacks.
- **Track 3 hard mandates:** B2B focus; runtime deployed natively on Google
  Cloud (Cloud Run or GKE); reasoning engine on Gemini (or third-party LLM
  exclusively via Agent Platform); A2A protocol interoperability.

### 1.2 Competitive position (from analysis of 383 scraped projects)

- Refactor track is the **least crowded**: ~13 registered, only 1 submitted at
  analysis time, and that one is unrelated (a code-review agent).
- Only one true domain-adjacent rival: **ARIA** (Build track, idea stage) —
  a narrow KYC-onboarding flow for PMS firms. Much thinner than this project.
- ~38 of 40 submitters are solo. Solo is normal here, not a disadvantage.
- **Implication:** the field is winnable. The edge is *depth and polish*, not
  novelty of idea. Execution wins this.

### 1.3 The product behind the submission — Curator Research by Aidni

Curator Research is a production regulatory-intelligence platform for Indian
BFSI: it ingests RBI/SEBI/IRDAI/etc. publications through a proprietary 14-stage
GPU pipeline into a 322K-node knowledge graph, and maps regulatory change onto
each bank’s internal policies and SOPs.

**CRITICAL IP BOUNDARY — do not cross it.** The hackathon submission is NOT
Curator. It is a separate, smaller, self-contained agent. The submission must
NEVER include, describe, or depend on: the 14-stage pipeline, the deontic
extraction methodology, the entity-resolution cascade, the Matryoshka embedding
strategy, the Milvus/Neo4j/TSDB production stores, the Tailscale mesh, or any
Azure/AWS infrastructure. The submission is built ONLY from standard, public
Google Cloud services. It is genuinely a different system — keep it that way.

### 1.4 What the submission agent actually does

**Curator — Regulatory Change Intelligence Agent.** A judge uploads **two PDFs**
(typically two versions of a regulation — e.g., an RBI Master Direction and its
amended version; optionally a regulation vs. an internal bank policy). The agent:

1. **Ingests** both PDFs at runtime (no pre-seeded corpus).
1. **Builds a knowledge graph** from each document at runtime.
1. **Decomposes** amended/changed clauses into distinct atomic obligations —
   one clause can fan out into several obligations with different owners and
   timelines. *(This fan-out is the signature innovation moment.)*
1. **Maps** each obligation against the other document (gap / coverage).
1. **Diffs** — produces a clause-level change log with suggested edits.
1. **Judges** — scores impact/priority, surfaces non-obvious downstream effects.
1. **Answers follow-up Q&A**, grounded in the graphs, with citations.

Output: an in-depth comparison, a structured change log, and a prioritized
actionable list.

### 1.5 Stage-1 state (from the Stage-1 report — VERIFY in Phase 0)

Stage 1 already scaffolded the project at `~/bs/agent/` via the Agents CLI
(`google-agents-cli`, template 3 = `agentic_rag`):

- `app/agent.py` — ADK App with 5 sub-agents (decompose / map / diff / judge /
  qna), real instruction prompts, lazy GCP-free imports.
- `app/models.py` — pydantic contracts: `AmendmentInput`, `AmendedClause`,
  `Obligation` (+ `DeonticType` enum), `PolicyDocument`/`PolicySection`,
  `PolicyMatch`, `PolicyDiff`, `ImpactSummary`, `QnATurn`, `AgentState`.
- `app/grounding.py` — `GroundingBackend` ABC with `MockGroundingBackend`
  (works offline against `data/fixtures/`) and a `VertexRagBackend` stub.
- `data/fixtures/` — a real RBI Capital Adequacy MD extract, a synthetic KYC MD,
  one amendment fanning out across 4 clauses, 4 hand-authored bank policy docs.
- `tests/eval/` — 5-case evalset + LLM-as-judge rubrics.
- `docs/STAGE2_PLAN.md` — prior Stage-2 checklist.
- Offline chain verified: 4 clauses → 6 obligations → 6 matches (1 missing) →
  5 diffs → priority medium. `pytest -q` → 4 passed, 4 skipped. Zero bbb/Azure
  coupling confirmed by grep.

### 1.6 Key architecture decision (supersedes the old Stage-2 plan)

The original Stage-2 idea (seed a VM with a corpus copied from the `bbb` repo)
is **abandoned**. The submission instead does **runtime GraphRAG from two
uploaded PDFs**, using a published Google reference architecture. This is
better because it is self-contained (a judge can run it with no seeded data),
it protects the Curator IP boundary, and it removes data-residency problems.

**Runtime pipeline (all managed GCP services):**

```
Upload 2 PDFs
   → Document AI Layout Parser   (OCR + Gemini layout understanding;
                                   preserves tables/headers/hierarchy)
   → Gemini + graph construction (build a knowledge graph per document;
                                   LangChain LLMGraphTransformer is the
                                   reference pattern — VERIFY current best
                                   option, see Phase 2)
   → Spanner Graph               (store both graphs; GraphRAG = graph search
                                   + vector search; provision in asia-south1)
   → ADK multi-agent chain       (decompose → map → diff → judge → qna,
                                   reasoning over the two graphs)
   → Output: comparison + change log + actionables + Q&A
   → Deployed on Cloud Run, A2A-exposed, Gemini reasoning
```

This satisfies all four Track-3 mandates natively. Note: this uses **Spanner
Graph directly**, NOT Vertex AI RAG Engine — so the RAG Engine us-central1
residency limitation does not apply. Provision Spanner Graph in `asia-south1`
for a clean residency story.

**Open product question (decide in Phase 0, default given):** the two PDFs may
be a *version pair* (v1 vs amended v2) or *regulation vs internal policy*.
Default: support both, optimize the demo for the version-pair case. The
decompose/map prompts should branch on an input “comparison mode”.

-----

## 2. Target architecture (the definition of done for the build)

|Layer             |Choice                                                     |Notes                                                                                           |
|------------------|-----------------------------------------------------------|------------------------------------------------------------------------------------------------|
|Orchestration     |Google ADK, multi-agent                                    |No LangGraph. Keep the 5-agent chain.                                                           |
|Reasoning model   |Gemini (latest stable in ADK)                              |Verify exact model string from ADK docs.                                                        |
|Doc ingestion     |Document AI Layout Parser                                  |Handles regulatory PDF tables/hierarchy.                                                        |
|Graph construction|Gemini-driven, at runtime                                  |Reference: LangChain `LLMGraphTransformer`. Verify a more ADK-native option doesn’t exist first.|
|Graph + retrieval |Spanner Graph (asia-south1)                                |GraphRAG: graph search + vector search.                                                         |
|Grounding seam    |`GroundingBackend` ABC                                     |Add `SpannerGraphBackend`; keep `MockGroundingBackend` for offline tests.                       |
|Runtime           |Cloud Run                                                  |Track-3 mandate. Agent logic only — stateless.                                                  |
|Interop           |A2A protocol                                               |Track-3 mandate. Agent must be A2A-discoverable.                                                |
|Observability     |Agent Observability / Cloud Trace                          |Largely inherited via ADK+Agent Runtime; surface it deliberately in the demo.                   |
|Quality tooling   |Agent Simulation, Agent Evaluation, Agent Optimizer        |Use to harden and to generate submission evidence.                                              |
|Front end         |Minimal web UI: upload 2 PDFs, show progress, render output|Simple. The agent is the star, not the UI.                                                      |

**Non-negotiables:** zero `bbb`/Azure/Tailscale coupling; public repo with an
OSI license; Gemini-only reasoning; everything deployable by a judge.

-----

## 3. Phased plan

Five phases. Each ends with a **gate**. The ordering guarantees a submittable
artifact exists well before the deadline; later phases add winning-grade depth.

### Phase 0 — Reconcile, set up, decide (do this first, ~0.5 day)

**Purpose:** replace assumptions with facts before building.

1. Read the actual Stage-1 codebase end to end. Produce
   `docs/STAGE1_ACTUAL.md` — what really exists, how it differs from §1.5 of
   this plan.
1. Read `docs/STAGE2_PLAN.md` (the prior checklist) and reconcile it with this
   document. This document supersedes it where they conflict.
1. Confirm environment: `gcloud` installed and authenticated, GCP project set,
   billing active, `stage-2` branch created off `main`.
1. Confirm/enable required GCP APIs: Vertex AI / Gemini, Document AI, Spanner,
   Cloud Run, Cloud Trace, plus whatever the Agents CLI needs.
1. Verify the credit situation is understood (the $500 challenge credit; the
   separate Google for Startups Cloud Program Start tier ~$2,000). Keep all
   dev infra small; shut down anything stateful when idle.
1. Make the comparison-mode decision (§1.6). Record it in `docs/DECISIONS.md`.
1. Start `docs/DECISIONS.md` — an append-only log of every non-obvious choice,
   with rationale. This becomes raw material for the submission write-up.

**Gate 0:** `docs/STAGE1_ACTUAL.md` and `docs/DECISIONS.md` exist; environment
and APIs verified; offline Stage-1 chain (`pytest -q`, mock run) still green.

### Phase 1 — Real agent reasoning on mock data (~2–3 days)

**Purpose:** make the 5-agent chain genuinely intelligent, still offline. This
de-risks everything: the hardest logic is proven before any cloud wiring.

1. Replace each sub-agent’s stub logic with real Gemini-powered reasoning,
   still reading from `MockGroundingBackend` / `data/fixtures/`:
- **decompose** — clause → multiple atomic `Obligation`s. Invest here: the
  fan-out is the Innovation score. One amended clause must reliably produce
  several obligations with distinct owner/timeline/condition fields.
- **map** — obligation → coverage against the other document
  (full / partial / missing / stale / contradicts) with confidence.
- **diff** — produce clause-level change log + suggested edits + rationale.
- **judge** — impact/priority scoring; surface non-obvious downstream
  effects (the “a human reviewer would miss this” moment).
- **qna** — grounded follow-up answers with citations.
1. Strengthen the data contracts in `app/models.py` as needed; keep them strict.
1. Expand `tests/eval/` well beyond 5 cases — cover fan-out depth, missing-
   coverage, contradiction, citation correctness, multi-hop Q&A.
1. Tune prompts against the evalset until quality is consistently high.

**Gate 1:** `adk run app` executes the full real-LLM chain on fixture data;
evalset passes at a high bar; the fan-out moment is visible and correct.

### Phase 2 — Runtime GraphRAG ingestion (~3–4 days)

**Purpose:** replace fixtures with real two-PDF runtime ingestion.

1. **Research first.** Confirm the current best way to build a knowledge graph
   from a document on GCP. The reference architecture uses LangChain
   `LLMGraphTransformer` + `SpannerGraphStore`; check whether ADK now offers a
   more native path. Record the choice in `docs/DECISIONS.md`.
1. Build the ingestion front of the pipeline:
- PDF upload → **Document AI Layout Parser** → structured content.
- Structured content → **Gemini** graph construction → per-document graph.
- Persist both graphs in **Spanner Graph** (provisioned in `asia-south1`),
  namespaced per upload session so two documents stay distinct.
1. Implement `SpannerGraphBackend` against the existing `GroundingBackend` ABC.
   The agent chain from Phase 1 should run unchanged on top of it.
1. Keep `MockGroundingBackend` working — offline tests must still pass.
1. Handle the messy realities: large PDFs, OCR noise, scanned pages, tables,
   footnotes. Fail gracefully with clear messages.

**Gate 2:** upload two real regulatory PDFs → graphs built in Spanner Graph →
the agent chain runs end to end on them → correct comparison + change log +
actionables. Offline mock path still green.

### Phase 3 — Deploy, interoperate, demonstrate (~3–4 days)

**Purpose:** meet all Track-3 mandates and make it judge-runnable.

1. **Cloud Run deployment** of the agent (stateless agent logic; Spanner Graph
   and Document AI are managed dependencies). Use the Agents CLI deploy path.
1. **A2A interoperability** — expose the agent via the A2A protocol so it is
   discoverable/coordinatable. Research the minimum-viable correct A2A
   implementation; don’t over-build.
1. **Minimal web UI** — upload two PDFs, show progress through the pipeline,
   render the comparison/change log/actionables, allow a Q&A follow-up. Clean
   and clear; the UI serves the demo, it is not the demo.
1. **Observability** — ensure Agent Observability / Cloud Trace shows the
   decompose→map→diff→judge reasoning trace. This visible trace is strong
   evidence for the Demo and Technical scores.
1. **Testing access** — make sure a judge can actually run it: a deployed URL,
   or a clean repo with one-command setup, with credentials/instructions.

**Gate 3 — THIS IS THE SUBMITTABLE FLOOR.** Deployed on Cloud Run; A2A-exposed;
Gemini reasoning; B2B; a judge can upload two PDFs and get the full output.
All four Track-3 mandates met. **If everything after this slips, the project is
still submittable and scores respectably.** Do not start Phase 4 until Gate 3
passes. Tag this commit.

### Phase 4 — Submission assets (~2–3 days, overlaps Phase 3 polish)

**Purpose:** produce everything Devpost requires. Judging is 40% Demo +
Business Case, so these assets matter as much as the code.

1. **Demo video (~3 minutes, the spec):** hook (problem) → live upload of two
   PDFs → the agent working, including the fan-out moment and the reasoning
   trace → architecture (Gemini, ADK, Spanner Graph, Document AI, Cloud Run,
   A2A) → business case → close. Public on YouTube. Do not exceed ~3 minutes.
1. **Architecture diagram** — the runtime GraphRAG pipeline, clean and clear.
1. **Written submission fields** — Problem, Solution, Technologies, Data
   sources, Findings & learnings, Third-party integrations. Draw “Findings”
   straight from `docs/DECISIONS.md`. Business Case section: be explicit about
   the path to a real Gemini Enterprise Marketplace listing and the BFSI
   market — that is the Track-3 / Business-Case story.
1. **Repo hygiene** — public, OSI license, clean README, one-command setup,
   no secrets, no `bbb` artifacts, no proprietary Curator detail.
1. **The 5 submission questions** — answer honestly from real build experience
   (GCP familiarity, AI Studio familiarity, launch readiness, most-critical
   Agent Platform feature + what it’s missing, the one API capability that
   would have saved 2+ hours).
1. **Submit on Devpost** with buffer before June 5, 5 PM PT. Do not wait for
   the last hour.

**Gate 4:** submission complete on Devpost, all required assets attached,
verified by re-opening the submission as a viewer.

### Phase 5 — Iterate to win (from Gate 3 until the deadline)

**Purpose:** once a submittable artifact exists, raise it from “respectable” to
“winning”. Run these as independent, low-risk improvement loops — each must
leave the project still-submittable.

Improvement directions, roughly highest-leverage first:

- **Agent Simulation** — generate synthetic document-comparison scenarios at
  scale; stress-test the chain; fix what breaks. Strongest reliability evidence.
- **Agent Optimizer** — feed it real failure traces; let it refine agent
  instructions; measure before/after on the evalset.
- **Deepen the fan-out** — make clause decomposition richer and more obviously
  valuable; this is the Innovation differentiator.
- **Sharpen the demo** — re-record if a cleaner, more compelling run exists.
- **Polish the output** — make the change log and actionables genuinely look
  like something a compliance officer would act on.
- **Agent Registry / Marketplace-readiness** — demonstrate listing-readiness
  to strengthen the Track-3 Refactor narrative.
- **Eval breadth** — more documents, more amendment types, harder Q&A.
- **Robustness** — handle weird PDFs, large files, edge cases gracefully.

Rule for Phase 5: each improvement is its own branch/commit; if it doesn’t
clearly help, revert it. Never let a polish attempt break Gate 3.

-----

## 4. Standing instructions for the whole build

- **Research before using any API.** ADK, Spanner Graph, Document AI, A2A, and
  Agents CLI all change. Check current docs; prefer official sources.
- **The IP boundary (§1.3) is absolute.** Nothing proprietary to Curator enters
  this repo or the submission, ever.
- **Honesty in the submission.** The agent does runtime two-document GraphRAG —
  that is genuinely impressive, but it is two-document depth, not a full
  corpus. Describe it accurately. The Business Case is where you talk about
  scaling to a corpus and to a Marketplace listing.
- **The deadline is fixed; scope flexes.** If behind, cut Phase 5 depth, then
  Phase 4 polish, but never ship past Gate 3 quality without a submission.
- **Cost discipline.** Keep dev infra small. Shut down stateful resources
  (Spanner instances especially) when idle. Credits are limited.
- **Commit discipline.** `stage-2` branch; clear messages; push regularly; tag
  the Gate-3 commit; keep `main` clean.
- **Keep `docs/DECISIONS.md` current.** Every non-obvious choice, with why. It
  is both an audit trail and the source for the submission’s Findings section.
- **Verify, don’t assume.** After each phase, actually run the thing. Report
  what passed, what failed, what surprised you.

-----

## 5. Definition of done

- **Minimum (Gate 3):** a Cloud Run-deployed, A2A-exposed, Gemini-reasoned
  agent; a judge uploads two regulatory PDFs and gets an in-depth comparison,
  a clause-level change log, and prioritized actionables, with grounded Q&A;
  all four Track-3 mandates met; clean public repo.
- **Submitted (Gate 4):** all Devpost assets — ~3-min video, architecture
  diagram, written fields, submission questions — complete and verified.
- **Winning-grade (Phase 5):** Simulation- and Optimizer-hardened; rich,
  obviously-valuable fan-out; a crisp compelling demo; Marketplace-readiness
  demonstrated; broad evals; robust on messy input.

Target: Grand Prize. Realistic strong outcome: Best-of-Theme (Refactor) and/or
APAC Regional. The field is winnable; execution and polish decide it.

-----

*Plan ends. Claude Code: start at Phase 0. Reconcile before you build. Respect
the gates. Keep it submittable at every step. Then make it win.*