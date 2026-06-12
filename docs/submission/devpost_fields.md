# Curator — Devpost Written Fields

*Google for Startups AI Agents Challenge — Track 3 (Build), Net-New submission.*

---

## Inspiration

Every fortnight an RBI, SEBI, or IRDAI circular lands in a Chief Compliance Officer's inbox. About one in three is material — meaning two to four weeks of CCO-team time to read it end-to-end, map each new obligation against existing internal policies, draft a board memo, refresh Pillar-3 templates, and update the Risk Management Committee's standing agenda. The tools in use today are document portals (eGazette, RBI search) and Excel gap-analyses. There is no agentic layer. We watched a compliance lead at an Indian private bank lose a weekend to a 14-page master direction amendment and realised the work is structurally a multi-perspective reading exercise: a banker, an auditor, a compliance officer, and a customer-protection advocate each see different obligations in the same paragraph. That is exactly what an ADK ParallelAgent can do — and the Spanner Graph of prior policy decisions is exactly the missing memory layer.

## What it does

Curator is an autonomous regulatory-intelligence agent for Indian BFSI. A Cloud Scheduler cron triggers a Discovery service every 30 minutes; it polls the SEBI RSS feed, dedupes against Spanner, and publishes new circulars to a Pub/Sub topic. The Discovery Inbox is also seeded with the full RBI capital-adequacy regulatory trail — 24 circulars spanning Basel III master circulars, the New Capital Adequacy Framework, the prudential-norms Master Directions and the 2026 credit-risk Standardised Approach, each with its public rbi.org.in source. The subscriber wakes the chain service, which (1) parses the PDF via Document AI Layout Parser, (2) ingests structure into Spanner Graph as nodes and edges, (3) runs a **quantitative parameter-diff** that places the new framework side-by-side with the prior one and extracts every regulatory number that moved — risk weights by exposure class, LTV bands, credit-conversion factors, capital charges, effective dates — each as an old→new pair with its direction and Pillar-1 CRAR impact, (4) runs a four-lens decompose panel — banker, compliance officer, auditor, customer-protection — in parallel, (5) a Reconciler merges and dedupes obligations and records per-lens dissent, (6) a Reflector inspects aggregate confidence and re-queries the Spanner Graph neighbourhood for low-confidence items, (7) a four-critic judge panel (impact, ICAAP, Pillar-3, ops-risk) scores severity using the parameter movements, and (8) the result lands as a board-ready impact assessment in a Discovery Inbox UI. Every output is a proposal — a human approves before anything goes to the RMC. An optional A2A consumer interface exposes the same skills to an external regulatory corpus so other agents can consume Curator's findings.

The headline demo diffs the **2026 Direction on Capital Charge for Credit Risk (Standardised Approach)** against the **prior Master Circular – Basel III Capital Regulations**: Curator surfaces the actual movements — e.g. credit-conversion factors on other commitments 50% → 40%, unconditionally-cancellable commitments 0% → 5% then 0% → 10% phased over 2027→2030, undrawn-limit CCFs 20% → 30% — each with the direction of the CRAR effect. This is the diff a Chief Compliance Officer actually needs, not a generic "you must implement the SA" obligation.

## How we built it

The whole agent is Google ADK 1.34. Decompose and judge are each a `SequentialAgent(ParallelAgent(4 lenses), Reconciler)`, wrapped so the Reflector can trigger a one-pass re-query against Spanner Graph when aggregate confidence falls below 0.6. Models are Gemini-flash served through Vertex AI on the `global` endpoint (region routing is documented in DECISIONS-9). Spanner Graph runs in `asia-south1` (Mumbai) — all ingested regulatory text and internal policy data is in-country; only Document AI Layout Parser is cross-region, since that processor is US-only. PDFs are parsed by a Doc AI Layout Parser processor and the structured layout is written to Spanner as a graph of clauses, obligations, and policy edges. Observability writes ~62 `agent_runs` rows per chain run, lens-tagged, with `pipeline_run_id` propagated through a `ThreadPoolExecutor` so map and diff fan out without losing trace context. Cloud Trace captures the parallel spans for the demo. Deployment is two Cloud Run services — the chain (UI + ADK API + A2A skill card at `/.well-known/agent.json`) and the discovery service (HTTP poller invoked by Cloud Scheduler) — both behind the `curator-ai-engine` service account. The A2A protocol is the GA `to_a2a` helper that auto-builds the skill card from `sub_agents`. For the self-improvement loop we logged every real-LLM call to `agent_runs`, then ran `SimplePromptOptimizer` over a 5-case evalset; the optimizer proposed a measurable prompt delta for $0.84 and we promoted it. The `--algo=gepa` flag is wired but currently raises `NotImplementedError`; SimplePromptOptimizer is the production default. A 30-case evalset is staged for the next pass.

## Challenges we ran into

A few honest disclosures. The Reconciler's `_normalize_action` collapses obligations on a stemmed-action key; an audit caught 4 of 8 edge-case mismatches (e.g. "climate" vs "credit", "quarterly" vs "annually") that are documented in `RECONCILER_AUDIT_2026-06-02.md` and are a Phase-5 fix. Confidence is calibrated to lens-agreement, not eval pass rate, because the 5-case set is too coarse to discriminate — also disclosed in `CALIBRATION_AUDIT_2026-06-02.md`. RBI's `/Scripts/RssNotification.aspx` no longer returns valid RSS, so the demo defaults to SEBI's RSS feed with a `CURATOR_RSS_FEED_URL` override for operators. The real-LLM chain wall-clock is 7-8 minutes end-to-end under Vertex AI rate limits even with map/diff parallelization — the bottleneck is quota, not code. And `reflect_and_requery` is callable and unit-tested but not yet wired into the demo path; the chain ships one-pass at Gate 3 to keep latency bounded.

## Accomplishments we're proud of

Measurable, not marketing. On the demo fixture the four-lens debate surfaces **22 obligations** vs **6** from a single-shot agent (3.7× fan-out), catches **9 missing-coverage gaps** vs **1**, and correctly escalates priority from `medium` to `critical` when capital-impact obligations only one lens spots would otherwise be missed. The 5-case evalset passes 5/5 at 1.0; a 30-case set is staged. SimplePromptOptimizer produced a usable prompt delta for **$0.84**. The test suite runs 22 passed / 12 skipped with 0 failures. Spanner writes ~62 lens-tagged `agent_runs` rows per chain run for full observability and future GEPA training. Total GCP spend through Gate 2 is **~$10 of a $200 cap**. All four Track-3 mandates are met: Gemini reasoning, B2B target, Cloud Run × 2, A2A-discoverable skill card.

## What we learned

Three things stand out. First, ADK's `ParallelAgent` plus a Reconciler is genuinely the right primitive for stakeholder-style reasoning — the 3.7× fan-out is not prompt magic, it is structurally what happens when four prompts with different priors read the same paragraph. Second, observability has to be designed in from day one: routing `pipeline_run_id` through `ThreadPoolExecutor` was the single highest-leverage change for debugging parallel runs, and the `agent_runs` table doubled as the optimizer's training set. Third, honesty in the rubric matters more than the rubric score — calibrating confidence to lens-agreement when the eval set is too coarse, and shipping the Reflector inert rather than faking a re-query, gave us cleaner numbers and a clearer Phase-5 plan than chasing a 1.0 we could not defend.

## What's next for Curator

Three tracks. (1) **Marketplace** — publish via `agents-cli publish gemini-enterprise` post-submission and onboard partners through Google Cloud India; the WTP is ₹5-20 lakhs/year per institution per regulator, ~₹50 crore ($6M) addressable across Indian BFSI within two years. (2) **GEPA wiring** — replace the `NotImplementedError` stub with the real `GEPARootAgentPromptOptimizer` consuming the `agent_runs` corpus that is already accumulating in Spanner; SimplePromptOptimizer is a proven scaffold, GEPA is the multi-step upgrade. (3) **Multi-tenant** — namespace Spanner Graph by tenant, scope the Discovery service per regulator subscription, and wire the Reflector's re-query into the demo path now that the one-pass chain is stable. We will also extend coverage to a proper BeautifulSoup parser for RBI's HTML notifications page, restoring full three-regulator discovery alongside SEBI and IRDAI.

## Built With

- Google ADK 1.34 (`ParallelAgent`, `SequentialAgent`, `LoopAgent`, `Runner`)
- Quantitative parameter-diff stage (old→new risk-weight / CCF / capital-charge extraction with CRAR impact)
- Gemini 2.5 Flash-Lite via Vertex AI (`global` endpoint)
- Spanner Graph (`asia-south1`, Mumbai)
- Document AI Layout Parser (US processor)
- Cloud Run × 2 (chain + discovery)
- A2A protocol GA (`to_a2a` skill card at `/.well-known/agent.json`)
- Cloud Scheduler + Pub/Sub (`curator-discoveries` topic)
- ADK `SimplePromptOptimizer` (production default; GEPA staged)
- Cloud Trace (parallel span observability)
- Python 3.12, `uv`, FastAPI + Jinja2 (Discovery Inbox UI)
- Apache 2.0 licensed, public repo
