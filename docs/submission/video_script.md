# Curator — 3-minute demo video script

**Target length:** 2:50–3:00. Track 3 Build, Net-New. Google for Startups AI Agents Challenge. Submission deadline 2026-06-11 17:00 PT.

**Style notes:** confident, specific, no buzzwords. Honest about proposal-only / human-in-the-loop. Time-lapse the real-LLM chain (it runs 7–8 min under Vertex AI rate limits) so the on-screen wall-clock stays under 30 seconds in the cut. Use NVIDIA-green accent for the UI shots (already in `app/templates/`); keep voice-over warm, not pitch-deck.

---

## Shot list

### 0:00 – 0:20 — Hook (cold open on the Inbox UI)

**Visual:** browser at `${CHAIN_URL}/inbox`. Three auto-discovered RBI/SEBI items visible as cards, each with timestamp and a "process" button. Cursor moves toward one — but cut before clicking.

**Voice-over:**
> An Indian compliance officer at a commercial bank gets an RBI amendment every fortnight. Today, she spends two to four weeks reading it, mapping it to her bank's internal policy, drafting board memos, updating ICAAP and Pillar-3 templates. Curator does the proposal in under ten minutes.

**On-screen text (lower third):** `2–4 weeks → <10 minutes. Proposals only. Human approves.`

---

### 0:20 – 0:50 — Discovery Inbox (autonomy proof)

**Visual:** zoom into the inbox card. Show that each card has: source (SEBI), title, published_at, first_seen, and a green "auto-discovered" tag. Click one; it routes to `${CHAIN_URL}/analyse`. Hold on the upload pane briefly to show "process from Inbox" pre-populated.

**Voice-over:**
> Curator runs a continuous discovery agent on a 30-minute Cloud Scheduler cron. It polls SEBI's RSS feed, dedupes through Spanner, and publishes new items to Pub/Sub. The chain service subscribes and processes the amendment without anyone clicking anything. This is what "always on" actually looks like for a B2B compliance team.

**On-screen text:** `Cloud Scheduler · Pub/Sub · Spanner dedup · Cloud Run`

---

### 0:50 – 1:50 — Debate panel + impact (the differentiator)

**Visual:** start chain run (or jump to a pre-recorded run for time-lapse). Cut to Cloud Trace dashboard showing the fan-out: four parallel decompose-lens spans (banker / compliance / auditor / customer_protect) converging at the Reconciler span. Then the four-critic judge panel. Highlight the Reflector span where it fires.

Cut back to UI at `${CHAIN_URL}/impact/<run_id>`. Show:
- 22 obligations (was 6 in single-shot)
- 9 missing-coverage gaps (was 1)
- Priority: **CRITICAL** (was medium)

**Voice-over:**
> Four stakeholder lenses — a banker, a compliance officer, an auditor, and a customer-protection advocate — debate every amendment in parallel. A Reconciler merges their findings; a Reflector catches what they missed by querying Spanner Graph for prior decisions. On the demo amendment, this fan-out surfaces three-point-seven times more obligations and nine times more coverage gaps than a single-shot agent. And it correctly escalates priority from medium to critical because the panel notices the capital-impact obligations a single agent misses.

**On-screen text (lower third, callouts):** `4 lenses · Reconciler · Reflector → 3.7× obligations · 9× gaps`

---

### 1:50 – 2:20 — Self-improvement (Tech Implementation axis)

**Visual:** open `docs/OPTIMIZATION_LOG.md` in the editor pane. Highlight: 42 candidates, $0.84 spent, before/after rubric delta. Cut to a quick `gcloud spanner databases execute-sql` showing the `agent_runs` table row count.

**Voice-over:**
> Every agent call logs a structured row to a Spanner observability table — prompt hash, inputs, outputs, confidence, latency, cost. The Agent Optimizer reads that log and proposes prompt deltas. One pass, eighty-four cents, and the decompose agent improved its own prompts measurably. The optimizer is the demo's "the agent improved itself" moment.

**On-screen text:** `agent_runs · SimplePromptOptimizer · Spanner Graph · asia-south1`

---

### 2:20 – 2:40 — A2A surface + architecture

**Visual:** A2A inspector (`tools/a2a-inspector/`) pointed at `${CHAIN_URL}/.well-known/agent.json`. Skill cards enumerate: decompose-panel, map, diff, judge-panel, qna, reflector. Then a 4-second flash of `docs/submission/architecture.svg`.

**Voice-over:**
> Curator exposes every sub-agent as an A2A skill, and consumes an external A2A surface for Q&A enrichment. Cloud Run runtime, Gemini reasoning, A2A protocol, B2B vertical — all four Track-3 mandates, in production posture.

**On-screen text:** `5 A2A skills · Cloud Run × 2 · Gemini 2.x flash · Apache 2.0`

---

### 2:40 – 3:00 — Business case + close

**Visual:** simple title card with three lines.
- `40 RBI commercial banks × ₹15L/yr = ₹6 Cr ($720K) addressable, Year 1`
- `500 SEBI PMS + 100 IRDAI insurers = ₹50 Cr ($6M) TAM by Year 2`
- `Marketplace path: agents-cli publish gemini-enterprise`

**Voice-over:**
> The first vertical is forty Indian banks. The marketplace path is one CLI command. The repo is Apache 2.0, the demo is live, and the next regulator amendment that drops will be processed without anyone reading email.

**End card:** Curator logo · `curator-chain-…run.app` · `github.com/SalilBhasinOfficial/agent-regchange`

---

## Recording checklist (D9 morning)

- [ ] Spanner instance up (`bash scripts/spanner_up.sh`)
- [ ] Both Cloud Run services healthy (`curl -fsS ${CHAIN_URL}/health` + discovery)
- [ ] At least 2 items pre-seeded into `discovered_items` (in case live RSS poll is empty)
- [ ] One real-LLM chain pre-run so `${CHAIN_URL}/impact/<run_id>` returns instantly during recording
- [ ] `agent_runs` row count > 100 for the optimizer screenshot
- [ ] Cloud Trace dashboard window pre-loaded with the fan-out trace
- [ ] A2A inspector preloaded with chain URL
- [ ] `docs/OPTIMIZATION_LOG.md` open at the rubric-delta line
- [ ] Architecture SVG open at full screen for the 4-second flash
- [ ] Screen recording at 1920×1080, 30fps minimum
- [ ] Audio: USB mic, no AC noise, room-tone check before first take
- [ ] OBS scenes pre-built: `inbox`, `cloud-trace`, `impact`, `optimization-log`, `a2a-inspector`, `architecture`, `endcard`

## Post-production

- Time-lapse the chain-run shot (real wall-clock 7–8 min → 8–10 sec on screen).
- Mute system notification sounds.
- Lower-thirds in NVIDIA green (#76B900).
- Upload to YouTube as **unlisted**; submit YouTube link to Devpost (avoid raw video upload).
- Final cut target 2:50–3:00.

## Honest disclosures (do NOT skip — Devpost "Findings" section already names these)

These are NOT mentioned in the voice-over, but the cut should not contradict them:
- Reconciler has 4/8 audit dedup mismatches (Phase 5).
- Confidence is calibrated to lens agreement, not eval pass rate.
- RBI's RSS endpoint is broken; we default to SEBI's.
- GEPA optimizer raises NotImplementedError; SimplePromptOptimizer is the production default.
- Reflector `reflect_and_requery` callable but the demo chain is one-pass.

These all live in `docs/eval_baselines/` and `docs/submission/devpost_fields.md`. Judges who dig in will find honest engineering; the video shows the headline.
