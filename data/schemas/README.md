# Reference Schemas (READ-ONLY)

These files are *reference only* — they describe shape choices from a sibling
project for Stage 2 alignment. They are NOT imported, executed, or required
by the Curator agent. Do not depend on them at runtime.

Files copied here:
- `curator_documents.sql.reference` — bank-side document/version registry
  (TimescaleDB hypertable shape). Stage 2 will likely re-implement against
  Cloud SQL / Spanner; the columns are useful as a starting taxonomy.
- `curator_proposals.sql.reference` — policy-proposal record shape. Maps
  closely to the `PolicyDiff` + `ImpactSummary` produced by this agent.
