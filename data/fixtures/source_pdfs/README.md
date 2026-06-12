# Demo PDF corpus — public RBI publications

These four PDFs are public publications of the **Reserve Bank of India**,
used as the demo corpus for the Curator agent. All were retrieved from
`rbi.org.in` / RBI's official mirror; no proprietary processing has been
applied.

| File | Title | Type | RBI date | Source |
|---|---|---|---|---|
| `02_second_amendment_2026-02-13_RBI-dbecd9fe73f6.pdf` | RBI (Commercial Banks – Prudential Norms on Capital Adequacy) Second Amendment Directions, 2026 | Amendment notification | 2026-02-13 | rbi.org.in |
| `03_third_amendment_2026-03-10_RBI-aaafe4b91697.pdf` | RBI (Commercial Banks – Prudential Norms on Capital Adequacy) Third Amendment Directions, 2026 | Amendment notification | 2026-03-10 | rbi.org.in |
| `04_master_direction_AFTER_2026-03-10_RBI-0d6a477d11ba.pdf` | Master Direction – Reserve Bank of India (Commercial Banks – Prudential Norms on Capital Adequacy) Directions, 2025 (Updated as on 2026-03-10) | Consolidated Master Direction (post-Third-Amendment) | 2026-03-10 | rbi.org.in |
| `05_credit_risk_standardised_2026-04-27_RBI-087798ec1547.pdf` | RBI (Commercial Banks – Capital Charge for Credit Risk – Standardised Approach) Directions, 2026 | New Directions (Basel III standardised approach) | 2026-04-27 | rbi.org.in |

## Demo pairings

- **Primary demo (version-pair, Phase 1–3):** `02` vs `03` — two consecutive
  amendments to the same Master Direction. Cleanest "what changed" story
  the agent can reason over without needing a pre-Third byte-perfect MD
  snapshot (which RBI overwrites in place on its site).
- **Alternative (amendment-vs-doc):** `03` (the amendment notification)
  vs `04` (the resulting consolidated MD). Demonstrates "trace the
  amendment into the document it modifies."
- **Phase 5 cross-corpus moment:** `04` (capital-adequacy MD) vs `05`
  (the new Capital Charge SA Directions, 2026) — shows the agent
  reasoning across two related-but-distinct regulatory instruments.

## Constraints noted at intake (2026-05-18)

- RBI overwrites Master Direction URLs in place. There is **no byte-perfect
  pre-Third-Amendment snapshot** of the MD available from RBI or the
  Wayback Machine. The pre-Third state is reconstructible via `02`'s
  superseded-clause references against `04`, but only at clause-level
  fidelity, not document-level.
- These PDFs are public regulatory publications. Including them in this
  repo is informational; the Apache 2.0 license in the repo root applies
  to the agent code, not to these documents (which carry RBI's terms).
