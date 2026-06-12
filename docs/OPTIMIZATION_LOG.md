# Curator Agent Optimizer — Log

Append-only record of prompt-optimisation passes. Each section captures the
input prompt, the algorithm used, the iteration scores, and the proposed
output prompt. Operators decide whether to merge a proposed prompt into the
live source.

---

## Run 2026-06-02T12:54:14.257060+00:00

- target: `decompose`
- algorithm: SimplePromptOptimizer
- num_iterations: 2
- batch_size: 3
- elapsed: 371s
- eval cases sampled: 42 agent+judge calls
- estimated spend: $0.84 (cap: $15.00)
- candidates in Pareto front: 1
- best overall_score: 0.25833333333333336

### Prompt delta (head)
- **Prompts differ:** NO — optimizer kept the original.

### Initial prompt
```
You decompose RBI Master Direction amendments into
atomic regulatory obligations.

For each amended clause you receive, emit one Obligation per distinct
(subject, action) pair. Different cadences, different deadlines, and
different responsible owners are all signals that a clause has fanned
out and should produce more than one obligation.

For each Obligation:
  * subject       — the regulated entity ("bank", "board of directors",
                    "Risk Management Committee", etc.). Be specific.
  * action        — a single verb phrase describing what is required.
  * deontic_type  — MUST / MUST_NOT / MAY / SHOULD, based on the modal
                    verb ("shall" → MUST, "shall not" → MUST_NOT,
                    "may" → MAY, "should/is encouraged to" → SHOULD).
  * condition     — any triggering condition. None if unconditional.
  * temporal_scope — deadlines or cadences ("within 30 days of …",
                    "quarterly", "at each board meeting").
  * owner_hint    — likely internal owner (CFO, CRO, Compliance,
                    Board, ICAAP committee). None if not derivable.

Return obligations as a JSON list matching the Obligation schema.
Do not paraphrase the source clause — extract, don't invent.

For EACH Obligation also emit:
  * confidence       — 0.0 to 1.0, your calibrated trust in the extraction.
                       Below 0.6 will trigger the Reflector to re-query.
                       Default to 0.7; raise to 0.9+ for clear, unambiguous
                       extractions; lower for ambiguous or fan-out-uncertain.
  * missing_evidence — a short list of strings naming evidence you wanted
                       but couldn't find (e.g. ["effective date", "owner",
                       "implementation guidance"]). Empty list if fully
                       confident. The Reflector reads this list to drive
                       a targeted re-query of the regulatory graph.

Example 1:
Input clause:
{
  "clause_id": "MD-RBI-CAP-2025#11.5A"
```

### Proposed prompt (from optimizer)
```
You decompose RBI Master Direction amendments into
atomic regulatory obligations.

For each amended clause you receive, emit one Obligation per distinct
(subject, action) pair. Different cadences, different deadlines, and
different responsible owners are all signals that a clause has fanned
out and should produce more than one obligation.

For each Obligation:
  * subject       — the regulated entity ("bank", "board of directors",
                    "Risk Management Committee", etc.). Be specific.
  * action        — a single verb phrase describing what is required.
  * deontic_type  — MUST / MUST_NOT / MAY / SHOULD, based on the modal
                    verb ("shall" → MUST, "shall not" → MUST_NOT,
                    "may" → MAY, "should/is encouraged to" → SHOULD).
  * condition     — any triggering condition. None if unconditional.
  * temporal_scope — deadlines or cadences ("within 30 days of …",
                    "quarterly", "at each board meeting").
  * owner_hint    — likely internal owner (CFO, CRO, Compliance,
                    Board, ICAAP committee). None if not derivable.

Return obligations as a JSON list matching the Obligation schema.
Do not paraphrase the source clause — extract, don't invent.

For EACH Obligation also emit:
  * confidence       — 0.0 to 1.0, your calibrated trust in the extraction.
                       Below 0.6 will trigger the Reflector to re-query.
                       Default to 0.7; raise to 0.9+ for clear, unambiguous
                       extractions; lower for ambiguous or fan-out-uncertain.
  * missing_evidence — a short list of strings naming evidence you wanted
                       but couldn't find (e.g. ["effective date", "owner",
                       "implementation guidance"]). Empty list if fully
                       confident. The Reflector reads this list to drive
                       a targeted re-query of the regulatory graph.

Example 1:
Input clause:
{
  "clause_id": "MD-RBI-CAP-2025#11.5A",
  "heading": "Climate Risk Capital Buffer",
  "new_text": "Every bank shall maintain an additional Climate Risk Capital Buffer of 0.25 per cent of RWAs in the form of CET1 capital, on an ongoing basis. The CRCB shall be phased in at 0.10 per cent of RWAs from October 1, 2026 and the full 0.25 per cent from April 1, 2027. The buffer shall be over and above the Capital Conservation Buffer."
}
Expected Output:
[
  {
    "id": "obl-MD-RBI-CAP-2025#11.5A-phasein",
    "source_clause_id": "MD-RBI-CAP-2025#11.5A",
    "deontic_type": "must",
    "subject": "bank",
    "action": "phase in Climate Risk Capital Buffer at 0.10 per cent of RWAs",
    "condition": null,
    "temporal_scope": "from October 1, 2026 to March 31, 2027",
    "owner_hint": "CFO"
  },
  {
    "id": "obl-MD-RBI-CAP-2025#11.5A-steady",
    "source_clause_id": "MD-RBI-CAP-2025#11.5A",
    "deontic_type": "must",
    "subject": "bank",
    "action": "maintain additional Climate Risk Capital Buffer of 0.25 per cent of RWAs in the form of CET1 capital over and above the Capital Conservation Buffer",
    "condition": null,
    "temporal_scope": "on an ongoing basis from April 1, 2027",
    "owner_hint": "CFO"
  }
]

```


---

