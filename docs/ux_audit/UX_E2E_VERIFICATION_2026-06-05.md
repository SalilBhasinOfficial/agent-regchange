# Post-fix verification — 2026-06-05

Re-run of the Playwright UX + E2E test after phase-4.2 ship (`fd3fdc1`).

**Pipeline run id under test:** `fd586238aaaa4a68b5cc68251614a713`

## Status of each audit finding

| # | Issue | Result | Evidence |
|---|---|---|---|
| **B1** | Chain hangs in diff/judge | ✅ **FIXED** | Diff_agent reached **50 calls** (previous run produced 0 — stuck forever). Chain progresses past the prior hang point. |
| **B2** | `pipeline_run_id` NULL on `agent_runs` | ✅ **FIXED** | Every lens row + every diff/map row now tagged with `fd586238aaaa4a68b5cc68251614a713` — matches the URL the user sees. ContextVar+mirror+explicit bind path all align. |
| **U1** | Nav A2A link → 404 | ✅ **FIXED** | Snapshot shows nav href `/a2a/app/.well-known/agent-card.json` (200 OK). |
| **U2** | Hard-coded "0 clauses" header | ✅ **FIXED** | Header reads "Pipeline run X · four-lens debate panel." Status fragment dynamically reports "2 amended clause(s) extracted · debate panel running." |
| **U4** | RBI-only Inbox copy | ✅ **FIXED** | Inbox now reads "Curator polls each configured regulator feed (RBI · SEBI · IRDAI by default)…" Manual poll button: "Poll regulators now (manual)". |
| **U5** | Missing favicon | ✅ **FIXED** | `/static/favicon.svg` served; `<link rel="icon">` in `base.html`. |
| **U3** | No per-row Inbox Analyse + auto-trigger | ✅ **WIRED** | Each `new`/`error` row in Inbox now renders an `Analyse` button → `POST /inbox/{item_hash}/analyse` → builds synthetic `AgentState` from title/URL → spawns chain → redirects to `/analyse/{pid}`. |

## Plug-and-play headline

- `app/discovery/sources.py` registry with 5 built-ins (SEBI, RBI, IRDAI, EU EBA, US SEC) selectable via `CURATOR_RSS_FEEDS=...`
- New `GET /sources` endpoint on the discovery service confirms which feeds the process polls
- Discovery `/poll` isolates per-source failures so a broken feed cannot stop the rest
- A2A card URL auto-templates via `CURATOR_PUBLIC_URL` so a fresh redeploy doesn't advertise the wrong host
- README §"Plug-and-play other regulators / jurisdictions" walks through adding a new regulator

## Chain run timing (this verification)

| t (relative) | Stage | agent_runs rows tagged with this pipeline_run_id |
|---|---|---|
| 0:00 | upload submitted, status `ingesting` | 0 |
| ~5:00 | status `running_chain`, lens panel done | 8 (4 lenses × 2 clauses) |
| ~6:00 | map fan-out in flight | 25 (8 lens + ~17 map+retries) |
| ~12:00 | map done, diff in flight | 68 (8 lens + 46 map + 22 diff) |
| ~17:00 | diff still chewing through rate limits | 96 (8 lens + 46 map + 50 diff) |

The chain is **not hung** — every check shows new rows since the previous check. The end-to-end wall-clock under the current Vertex AI quota and `CURATOR_*_CONCURRENCY=2` is ~20-25 minutes for 22 obligations × 22 diffs. Recording the demo video should pre-bake a completed run and seek to `/impact/<known_run_id>` to keep the cut tight.

## Deployed env state (revision `curator-chain-00004-wnr`)

```
CURATOR_MAP_CONCURRENCY=2
CURATOR_DIFF_CONCURRENCY=2
CURATOR_RUN_TIMEOUT_S=180
CURATOR_RSS_FEEDS=sebi
CURATOR_PUBLIC_URL=https://curator-chain-890675948352.asia-south1.run.app
CURATOR_GROUNDING=spanner
CURATOR_REAL_LLM=1
CURATOR_AGENT_RUN_LOG=1
CURATOR_DOCAI_PROCESSOR_ID=projects/890675948352/locations/us/processors/4c036f5845e938e7
CURATOR_DISCOVERY_SUBSCRIBE=1
CURATOR_DISCOVERY_SUBSCRIPTION=curator-chain-pull
GOOGLE_CLOUD_PROJECT=curator-research
GOOGLE_CLOUD_PROJECT_NUMBER=890675948352
GOOGLE_CLOUD_LOCATION=global
GOOGLE_GENAI_USE_VERTEXAI=True
SPANNER_INSTANCE=curator-graph
SPANNER_DATABASE=curator
```

Discovery revision `curator-discovery-00002-tcs` advertises:

```bash
$ curl /sources | jq '.sources | length'
1
```

with `CURATOR_RSS_FEEDS=sebi`. Flip to `sebi,eu_eba,us_sec` and the count goes to 3 on the next deploy with no code change.
