# Lens Diversity Audit — 2026-06-02

Computes Jaccard similarity between each pair of the four debate-panel
lenses on the (source_clause_id, action[:120]) fingerprint. Drawn from
the most-recent 100 `agent_runs` rows tagged with a lens.

A pair with Jaccard > 0.85 is **redundant** — the two lenses are
extracting nearly the same obligations and the panel isn't earning its
keep on those.

## Lens sample sizes (post-reconciliation; one row per obligation per lens-call)

- `auditor_lens`: 15 unique obligations
- `banker_lens`: 15 unique obligations
- `compliance_lens`: 19 unique obligations
- `customer_protect_lens`: 13 unique obligations

## Pair-wise Jaccard

| Lens A | Lens B | Jaccard | |A| | |B| |
|---|---|---|---|---|
| `auditor_lens` | `compliance_lens` | **0.21** | 15 | 19 |
| `banker_lens` | `compliance_lens` | **0.21** | 15 | 19 |
| `auditor_lens` | `banker_lens` | **0.20** | 15 | 15 |
| `compliance_lens` | `customer_protect_lens` | **0.19** | 19 | 13 |
| `auditor_lens` | `customer_protect_lens` | **0.17** | 15 | 13 |
| `banker_lens` | `customer_protect_lens` | **0.17** | 15 | 13 |

## Verdict

**PASS** — no pair exceeded 0.85. All four lenses produce meaningfully different obligation sets.

## Methodology limitations

- Fingerprint is `(source_clause_id, action[:120])` — paraphrases of
  the same action with different wording will register as distinct.
  The Reconciler's `_normalize_action` fingerprint is stricter (sorted
  tokens), but using that here would mask paraphrase diversity which
  is part of the value the panel surfaces.
- Sample size: most-recent 100 `agent_runs` rows. For statistical
  significance run a 1000+ row sample over a Phase-5 batch.
