# DESIGN_SPEC — Curator Regulatory Change Intelligence Agent

## 1. Problem

A bank's compliance team receives an RBI amendment notification. Today
they re-read the affected Master Direction, then walk through every
relevant internal policy/SOP, identify what needs to change, draft the
edits, route them through the Risk Management Committee and the Board,
and update Pillar 3 templates and training material. The cycle is
weeks long, error-prone, and the most-missed work is *downstream*
effects (capital plan revision, ICAAP recalibration, RMC agenda,
disclosure templates).

Curator collapses this from weeks to minutes — as a *proposal*, never
an autonomous action. A human reviewer approves every edit.

## 2. Inputs and outputs

Input (typed: `app.models.AmendmentInput`):

* Amendment notification text + structural metadata.
* Pointer to the revised Master Direction.
* Bank's internal policy corpus (`PolicyDocument` × N).

Output (typed: `app.models.AgentState`):

* `AmendedClause[]` — clauses identified as changed.
* `Obligation[]` — atomic obligations (clauses fan out into many).
* `PolicyMatch[]` — coverage analysis against bank policies.
* `PolicyDiff[]` — concrete suggested edits.
* `ImpactSummary` — impact score, priority, affected departments,
  downstream effects.
* `QnATurn[]` — follow-up Q&A with citations.

## 3. The 5-step workflow

```
                       ┌──────────────────┐
   AmendmentInput  ──▶ │  Orchestrator    │ ─┐
   PolicyDocument[]    │  (root_agent)    │  │  shared AgentState
                       └──────────────────┘  │  (blackboard)
                                             ▼
   ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────┐
   │ decompose  │─▶│   map      │─▶│   diff     │─▶│   judge    │─▶│   qna    │
   │  agent     │  │   agent    │  │   agent    │  │   agent    │  │  agent   │
   └────────────┘  └────────────┘  └────────────┘  └────────────┘  └──────────┘
   clause→obligs   obl×policy→     match→edit      package→        follow-up
                   match            (proposal)     impact          Q&A w/ cites
```

Each sub-agent is a real `google.adk.agents.Agent` with a real
instruction prompt (see `app/sub_agents/*.py`). Stage 1 backs the
business logic with deterministic Python stubs (`stub_decompose`,
`stub_map`, `stub_diff`, `stub_judge`, `stub_qna`) so the chain is
runnable today without GCP credentials. Stage 2 replaces each stub
with the LLM path (Gemini reasoning + Vertex AI RAG retrieval).

## 4. Agent roles

| Agent | Role | Stage-1 stub | Stage-2 |
|-------|------|--------------|---------|
| `root_agent` | Orchestrates the 5-step chain. Owns the `AgentState` blackboard. Carries the enterprise-B2B safety constraints (proposals only, no autonomous external actions). | Constructed at import-time *lazily* (PEP 562). | Becomes the A2A-discoverable entrypoint. |
| `decompose_agent` | Amendment clauses → atomic `Obligation[]`. Fan-out is explicit: a single clause with multiple deontic targets must emit multiple obligations. | One obligation per clause (1:1). | Gemini extraction over real clause text with few-shot fan-out examples. |
| `map_agent` | `Obligation × PolicyDocument` → `PolicyMatch` (full / partial / missing / stale / contradicts). | Token-overlap with novel-concept downgrade. | Retrieval grounded in Vertex AI RAG Engine over the bank's policy corpus. |
| `diff_agent` | `PolicyMatch` → `PolicyDiff` (current_text + suggested_text + rationale). Only emits diffs for partial/missing/stale/contradicts. Never autonomously applies edits. | Template-based suggested text. | Gemini edit synthesis that preserves the bank's tone, numbering, and approval-trail conventions. |
| `judge_agent` | The change package as a whole → `ImpactSummary`. Calibrated priority + non-obvious downstream effects. | Score from `n_missing` + `n_must`. | Gemini reasoning over the full state + curated downstream-effects checklist. |
| `qna_agent` | Follow-up Q&A over the completed package, with citations to obligation ids and policy section ids. | Templated answer using state counts. | Gemini answer with retrieval over the state plus the underlying corpus. |

## 5. Data contracts

Defined in `app/models.py`. Authoritative summary:

```text
AmendmentInput     id, master_direction_id, title, effective_date,
                   notification_url, raw_text
AmendedClause      clause_id, md_id, heading, old_text, new_text,
                   change_type ∈ {insert, modify, delete, renumber}
Obligation         id, source_clause_id, deontic_type ∈ {must, must_not,
                   may, should}, subject, action, condition,
                   temporal_scope, owner_hint
PolicyDocument     policy_id, title, owner_department,
                   sections: PolicySection[]
PolicySection      policy_section_id, heading, text
PolicyMatch        obligation_id, policy_section_id?, coverage ∈
                   {full, partial, missing, stale, contradicts},
                   confidence ∈ [0,1], rationale
PolicyDiff         policy_section_id, current_text, suggested_text,
                   rationale, related_obligation_ids[]
ImpactSummary      impact_score ∈ [0,1], priority ∈ {low, medium, high,
                   critical}, affected_departments[],
                   downstream_effects[], summary
AgentState         amendment, amended_clauses[], obligations[],
                   policies[], matches[], diffs[], impact?,
                   qna_history: QnATurn[]
QnATurn            question, answer, citations[]
```

Each sub-agent reads what it needs from `AgentState` and appends its
output. The orchestrator owns mutation; sub-agents do not mutate
inputs.

## 6. Grounding

Two backends behind a single ABC (`app/grounding.py`):

* `MockGroundingBackend` — file-system, reads `data/fixtures/`. Used
  by Stage-1 tests, the offline chain, and the eval harness.
* `VertexRagBackend` (Stage 2) — wraps Vertex AI RAG Engine. The
  managed database runs on Spanner; region allow-list is `us-central1
  / us-east1 / us-east4`. Indian-resident regulatory data may need a
  residency review before Stage-2 ingestion (flagged in code).

## 7. Model selection

Stage 1 + Stage 2 default: `gemini-flash-latest` (per the scaffold's
choice). The `agents-cli` model docs caution against changing the
model unless explicitly requested — that constraint is honored. The
exact model string is reaffirmed in `app/sub_agents/*.build_agent()`.

## 8. Safety constraints (enterprise B2B)

* The agent only *proposes*. Every edit is reviewed and approved by a
  human compliance officer.
* No external actions. No emails. No DB writes outside the in-process
  `AgentState`. No autonomous policy publication.
* Stage 2 will add a deployment-time check that the running agent
  has *no tool capable of external write* — enforced by the
  orchestrator's tool allow-list, not by prompt instruction alone.
* On uncertainty, prefer `coverage = "missing"` or `priority = "low"`
  over invented compliance.

## 9. Why this scaffold (`agentic_rag` template)

The `agents-cli` `agentic_rag` template was selected over `adk` and
`adk_a2a` because:

* The change-analysis chain is fundamentally retrieval-grounded — we
  need RAG over the Master Direction corpus and the bank's policy
  corpus. The template pre-wires `data-ingestion` and the
  `VertexAiSearchTool` for exactly this.
* A2A discovery (template option 2) is a Stage-2 concern and can be
  layered on via `agents-cli scaffold enhance` once the chain is
  real.

## 10. Stage boundary

Stage 1 (this milestone): deterministic, runnable end-to-end on
fixture data, zero external dependencies beyond Python + uv.

Stage 2: see [`docs/STAGE2_PLAN.md`](docs/STAGE2_PLAN.md).
