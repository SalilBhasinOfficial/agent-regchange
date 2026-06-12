# Curator — Devpost Submission Packet (paste-ready)

**Use this for the 15-minute submission. Everything below is copy-paste-ready.
Deadline: 2026-06-11 17:00 PT (= 2026-06-12 05:30 IST).**

---

## ☑️ Step-by-step (do these in order)

1. **Upload the demo video to YouTube** (unlisted):
   - File: `docs/submission/curator_demo.mp4`
   - Title / description / tags: see "YouTube metadata" below.
   - Copy the resulting watch URL.
2. **Open Devpost** → the Google for Startups AI Agents Challenge project page.
3. **Paste the written fields** (see "Devpost fields" below) into each section.
4. **Theme / Track:** select **Track 3 — Build (Net-New Agents)**.
5. **Region:** select **India** (this is what makes you eligible for the regional prize).
6. **Media:**
   - Upload `docs/submission/architecture.png` as the project image.
   - Paste the YouTube URL into the video field.
7. **Links:**
   - Repo: `https://github.com/SalilBhasinOfficial/agent-regchange`
   - Live demo (chain): `https://curator-chain-890675948352.asia-south1.run.app`
   - A2A skill card: `https://curator-chain-890675948352.asia-south1.run.app/a2a/app/.well-known/agent-card.json`
8. **Press Submit.** Confetti = done.
9. **Verify:** open the public project page in a logged-out browser tab; confirm video plays, image renders, links work.

---

## 🎬 YouTube metadata

**Title:**
```
Curator — Autonomous Regulatory-Change Intelligence for Indian BFSI (Google ADK + Cloud Run + A2A)
```

**Description:**
```
Curator is an autonomous regulatory-intelligence agent team built on Google's
Agent Development Kit (ADK) for the Google for Startups AI Agents Challenge
(Track 3 — Build).

Every fortnight an RBI / SEBI / IRDAI circular lands on a Chief Compliance
Officer's desk. One in three is material — 2 to 4 weeks of work to read it,
map each obligation to internal policy, and draft a board memo. Curator does
the proposal in minutes (proposals only — a human always approves).

How it works:
• A Discovery service polls regulator RSS feeds every 30 min (Cloud Scheduler →
  Pub/Sub → Spanner dedupe).
• Document AI Layout Parser extracts structure from the amendment PDF.
• A four-stakeholder-lens debate panel (banker / compliance / auditor /
  customer-protection) decomposes obligations in parallel via ADK ParallelAgent.
• A Reconciler merges and a Reflector re-queries Spanner Graph on low confidence.
• A four-critic judge panel scores impact (ICAAP / Pillar-3 / ops-risk).
• Output: a board-ready impact assessment in a Discovery Inbox UI.

On the demo amendment the debate panel surfaces 3.7× more obligations and 9×
more missing-coverage gaps than a single-shot agent.

Built with: Google ADK 1.34, Gemini 2.5 Flash-Lite (Vertex AI), Spanner Graph
(asia-south1), Document AI, Cloud Run × 2, A2A protocol, Cloud Scheduler +
Pub/Sub, Cloud Trace. Apache 2.0, public repo.

Repo: https://github.com/SalilBhasinOfficial/agent-regchange
Live: https://curator-chain-890675948352.asia-south1.run.app
```

**Tags:**
```
Google ADK, AI agents, Gemini, Cloud Run, Vertex AI, Spanner, A2A protocol,
RegTech, compliance automation, Indian BFSI, multi-agent, agentic AI
```

**Visibility:** Unlisted (judges can view via link; not public-searchable).

---

## 📝 Devpost fields (paste each block)

> Source of truth is `docs/submission/devpost_fields.md`. The blocks below are
> the same content with this session's facts corrected (A2A card path, model id,
> test counts, plug-and-play multi-regulator, cost tracking).

### Elevator pitch (≤200 chars)
```
Autonomous regulatory-change intelligence for Indian banks: a four-lens ADK
debate panel turns an RBI/SEBI amendment into a board-ready impact assessment
in minutes. Proposals only; human approves.
```

### Inspiration
*(paste the "Inspiration" section from devpost_fields.md verbatim — unchanged)*

### What it does
*(paste "What it does" from devpost_fields.md — unchanged)*

### How we built it
*(paste "How we built it" from devpost_fields.md, with these two corrections:)*
- Model is **Gemini 2.5 Flash-Lite** via Vertex AI `global` (centralised in
  `app/llm.py`, env-overridable via `CURATOR_GEMINI_MODEL`).
- The A2A skill card is served at **`/a2a/app/.well-known/agent-card.json`**
  (a2a-sdk spec path), exposing 6 skills.

### Challenges we ran into
*(paste "Challenges" from devpost_fields.md — unchanged; all disclosures still true)*

### Accomplishments we're proud of
*(paste "Accomplishments" from devpost_fields.md, correcting:)*
- Test suite now **24 passed / 13 skipped / 0 failed**.
- Per-call **USD cost tracking** writes to `agent_runs.cost_usd_estimated`; a
  live `/cost` endpoint rolls up spend by agent.
- **Plug-and-play multi-regulator**: a source registry (SEBI, RBI, IRDAI, EU
  EBA, US SEC) selectable by env var — adding a regulator is one dict entry.

### What we learned
*(paste "What we learned" from devpost_fields.md — unchanged)*

### What's next for Curator
*(paste "What's next" from devpost_fields.md — unchanged)*

### Built With
```
Google ADK 1.34, Gemini 2.5 Flash-Lite, Vertex AI, Spanner Graph (asia-south1),
Document AI Layout Parser, Cloud Run, A2A protocol, Cloud Scheduler, Pub/Sub,
Cloud Trace, Python 3.12, uv, FastAPI, Jinja2, Apache 2.0
```

---

## 🔗 Canonical links (copy block)

```
Repo:        https://github.com/SalilBhasinOfficial/agent-regchange
Live chain:  https://curator-chain-890675948352.asia-south1.run.app
Inbox:       https://curator-chain-890675948352.asia-south1.run.app/inbox
A2A card:    https://curator-chain-890675948352.asia-south1.run.app/a2a/app/.well-known/agent-card.json
Cost:        https://curator-chain-890675948352.asia-south1.run.app/cost
Discovery:   https://curator-discovery-890675948352.asia-south1.run.app
Architecture image: docs/submission/architecture.png
Demo video:  docs/submission/curator_demo.mp4  (upload to YouTube first)
```

---

## ⚠️ If you have 10 extra minutes (optional, makes the live demo smoother)
- Set `--min-instances=1` on `curator-chain` so judges hitting the live URL get
  no cold start: `gcloud run services update curator-chain --region=asia-south1 --min-instances=1`
  (≈$5/day — revert after judging).
- Bring Spanner up if you want the live `/inbox` and `/impact` to work for
  judges during the judging window: `bash scripts/spanner_up.sh`.
- Without those, the **video** still carries the full demo; the live URL shows
  the UI shells + A2A card + /cost regardless.
