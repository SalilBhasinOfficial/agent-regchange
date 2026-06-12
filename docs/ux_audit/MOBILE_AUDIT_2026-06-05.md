# Mobile UX audit + honesty fixes — 2026-06-05

## "Under 60 seconds" was aspirational; replaced with honest copy

The upload page used to read: *"…produces obligations, coverage gaps,
suggested edits, and impact — in under 60 seconds."* That number was a
Phase-3 planning target that did not survive contact with Vertex AI
rate limits. Even with `CURATOR_FAST_MODE=1` + `CURATOR_FAST_MAX_OBLIGATIONS=5`
+ `CURATOR_*_CONCURRENCY=4`, the demo fixture chain takes **~3 minutes
of wall-clock under free-quota gemini-flash-latest** because individual
calls retry-with-backoff every time they hit a 429.

Verified live this session: fast-mode run at T0=11:49:29 was still in
`running_chain` at T+2:51 with 28 map calls inflated from 5 unique
obligations.

### What the copy says now

> Upload an amendment (PDF A) and the prior or master direction (PDF B).
> Curator's four-stakeholder-lens debate panel produces obligations,
> coverage gaps, suggested edits, and impact — **typically in a few
> minutes on the demo fixture, faster on lighter notifications.** Compare
> with **2–4 weeks of compliance-officer time** per material amendment
> today.

That framing matches reality and still keeps the headline win
(2–4 weeks → minutes).

### How to actually get sub-60s

`CURATOR_FAST_MODE=1` caps obligation fan-out before map/diff and is
deployed by default. To genuinely beat 60s you need to **dedicate
Vertex AI quota** (a paid pinned-deployment endpoint or a provisioned
throughput SKU). On dedicated quota the 20-ish chain calls fire without
429 retries and the wall-clock collapses to 15–30s. Documented in the
new README §"Fast-mode (sub-60s triage)".

---

## Mobile audit — iPhone 14 viewport (390×844)

Screenshots in this directory: `mobile-01-upload.png`,
`mobile-02-inbox.png`, `mobile-03-impact.png`, `mobile-04-upload-after-fix.png`,
`mobile-05-inbox-after-fix.png`.

### Findings (BEFORE fixes)

| # | Issue | Evidence |
|---|---|---|
| M1 | **Nav meta text overflows viewport** | Meta tag positioned at x=422 on a 390-wide viewport. Flex container had no `flex-wrap` so the right-aligned tagline pushed off-screen. Nav was 137px tall trying to fit. |
| M2 | **Inbox 6-column table overflows horizontally** | Hash + long titles + status pills jammed into <390px caused unreadable squish. No scroll wrapper. |
| M3 | **CTAs/buttons cramped** | `.footer-actions` row didn't wrap; buttons collided with secondary links. |
| M4 | **Stat-row 4 columns × 90px** | Four discovery stats squeezed past their content widths on 390px. |

### Fixes shipped (`docs/ux_audit/mobile-04-*`, `mobile-05-*`)

`app/templates/base.html` got a mobile media-query block:

```css
.nav { flex-wrap: wrap; }
.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
.table-wrap table { min-width: 640px; }

@media (max-width: 640px) {
  .nav { padding: 10px 14px; gap: 14px; }
  .nav .meta { display: none; }     /* tagline hidden on mobile */
  main { padding: 18px 14px; }
  h1 { font-size: 20px; }
  h2 { font-size: 14px; line-height: 1.4; }
  .grid-2 { grid-template-columns: 1fr; }   /* upload row stacks */
  .stat-row { grid-template-columns: repeat(2, 1fr); }
  .footer-actions { flex-wrap: wrap; }
  .card { padding: 16px 14px; }
  button, .btn { width: 100%; text-align: center; }
  .footer-actions .btn { width: auto; }
}
```

Plus `app/templates/inbox.html` now wraps its `<table>` in
`<div class="table-wrap">` so the inbox scrolls horizontally on mobile
without breaking the desktop layout.

### After-fix verification (via Playwright snapshots at 390×844)

| Page | Before | After |
|---|---|---|
| Nav height | 137px (meta wrapped 3 lines) | **48px** (meta hidden, nav links wrap once if needed) |
| Inbox table | overflowed page | **horizontal scroll inside `.table-wrap`**, page width unchanged |
| Stat-row | 4 collapsed columns at ~85px each | **2 × 2 grid**, readable |
| Buttons | side-by-side, cramped | **full-width primary**, secondary inline |
| Upload `.grid-2` | two 134px cards side-by-side | **single column stack**, each input full-width |

The fixes are CSS-only (no JS, no template restructure beyond the table
wrapper). Desktop appearance is unchanged.

---

## Bonus bug spotted (separate from mobile audit)

`/impact/<run_id>` returned **"Run not found or still in progress"**
shortly after the chain completed. Root cause: `_RUNS` is an in-process
dict in `app/fast_api_app.py` — it dies when the Cloud Run container
scales to zero (and there's no min-instances=1 set). The user's URL
bookmark then 404s the moment they refresh.

**Fix path (not done in this session):** persist `_RUNS` to Spanner
(reuse the `discovered_items` table or add a small `pipeline_runs`
table). Until then, judges should `--min-instances=1` the chain
service during the demo window. Added to known-limitations.

---

## Cumulative cost

This audit cycle (mobile + fast-mode + redeploy + one capped chain
run): ~$0.40 in LLM calls, ~$0.10 in Cloud Build. Session total
~$13 of $200 cap.
