# Reconciler Dedup Audit — 2026-06-02

Exercises `app/sub_agents/reconciler.py::_normalize_action` on 8 hand-curated
action pairs that probe its over- and under-dedup behaviour. The fingerprint
is `lowercase → strip punctuation → drop ≤3-char tokens → sort → first 8`.

## Results

| Action A | Action B | Expected | Actual | Verdict | Note |
|---|---|---|---|---|---|
| `maintain climate risk capital buffer of 0.25% of RWAs` | `maintain credit risk capital buffer of 1% of RWAs` | distinct | distinct | OK | climate vs credit — different regulatory concepts; must NOT merge |
| `phase in CRCB at 0.10% from October 1, 2026` | `phase in Climate Risk Capital Buffer at 0.10 per cent from O` | merge | distinct | MISMATCH | abbreviation vs full name; SHOULD merge (same obligation) |
| `review ICAAP policy quarterly` | `review ICAAP policy annually` | distinct | distinct | OK | quarterly vs annually — distinct cadence; must NOT merge |
| `establish Board-approved policy for climate concentration` | `establish Board approved policy for climate concentration ri` | merge | distinct | MISMATCH | punctuation variant; SHOULD merge |
| `disclose CRCB quantitatively by exposure class` | `disclose CRCB qualitatively in narrative` | distinct | distinct | OK | quantitative vs qualitative disclosure — distinct obligations |
| `update Pillar 3 disclosure to include CRCB` | `update Pillar 3 disclosure template to include Climate Risk ` | merge | distinct | MISMATCH | abbreviation + 'template'; SHOULD merge |
| `notify Board of material changes immediately` | `notify Board of material changes within 30 days` | distinct | distinct | OK | immediate vs 30-day deadline — distinct obligations |
| `maintain CRCB buffer over and above the CCB` | `maintain Climate Risk Capital Buffer over and above the Capi` | merge | distinct | MISMATCH | abbreviation variants; SHOULD merge |

## Summary

- **Test cases:** 8
- **Mismatches:** 4
- **Verdict:** FAIL — 4 mismatch(es) found, listed below.

## Mismatches

- **Note:** abbreviation vs full name; SHOULD merge (same obligation)
  - A: `phase in CRCB at 0.10% from October 1, 2026` → normalised: `2026 crcb from october phase`
  - B: `phase in Climate Risk Capital Buffer at 0.10 per cent from October 1, 2026` → normalised: `2026 buffer capital cent climate from october phase`
  - Expected: merge

- **Note:** punctuation variant; SHOULD merge
  - A: `establish Board-approved policy for climate concentration` → normalised: `approved board climate concentration establish policy`
  - B: `establish Board approved policy for climate concentration risk` → normalised: `approved board climate concentration establish policy risk`
  - Expected: merge

- **Note:** abbreviation + 'template'; SHOULD merge
  - A: `update Pillar 3 disclosure to include CRCB` → normalised: `crcb disclosure include pillar update`
  - B: `update Pillar 3 disclosure template to include Climate Risk Capital Buffer` → normalised: `buffer capital climate disclosure include pillar risk template`
  - Expected: merge

- **Note:** abbreviation variants; SHOULD merge
  - A: `maintain CRCB buffer over and above the CCB` → normalised: `above buffer crcb maintain over`
  - B: `maintain Climate Risk Capital Buffer over and above the Capital Conservation Buffer` → normalised: `above buffer buffer capital capital climate conservation maintain`
  - Expected: merge

## Remediation policy

- If a pair that should merge does NOT, raise the token-floor (currently 3
  chars) so more tokens stay in the fingerprint.
- If a pair that should distinct does NOT, lower the token-cap (currently
  first 8 sorted tokens) or include source_clause_id (already in the key
  alongside the action — see `reconciler.py::reconcile_obligations`).

Action specificity is intentionally permissive — over-merging is the safer
error than surfacing cosmetic duplicates. Re-run this audit if either
heuristic is touched.
