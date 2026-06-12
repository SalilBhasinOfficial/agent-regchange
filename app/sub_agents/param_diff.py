"""Parameter-diff — old framework × new framework → ParameterChange[].

This is the stage that makes Curator a *change* analyser rather than a
generic obligation extractor. The existing decompose → map → diff → judge
chain reads only the amending document (Doc A) and maps it against the
bank's internal policy. It never actually diffs Doc A against Doc B (the
prior / consolidated framework) — so quantitative movements like
"corporate unrated 100% → external-rating-banded", "listed equity
125% → 250%", "consumer credit 125% → LTV-banded" are never surfaced.

``real_param_diff`` puts BOTH documents' full text side-by-side in one
Gemini call (Gemini 2.5 Flash-Lite has a 1M-token context, so a 412-page
Master Direction + a credit-risk SA direction fit comfortably) and
extracts a structured table of old→new parameter changes with direction,
effective date, and CRAR/RWA impact.

Offline-safe: ``stub_param_diff`` returns [] (no parameters without an
LLM); the canonical smoke line is unaffected.
"""

from __future__ import annotations

import os

from app.models import AmendedClause, ParameterChange

PARAM_DIFF_INSTRUCTION = """You are a senior prudential-regulation analyst at
an Indian bank. You are given TWO regulatory documents:

  * NEW FRAMEWORK — the amending / latest document.
  * PRIOR FRAMEWORK — the consolidated or earlier document it changes.

Your single job: produce an exhaustive, precise table of the QUANTITATIVE
parameters that MOVED between the prior and the new framework. This is for a
Chief Compliance Officer who needs to know exactly what numbers changed and
the effect on regulatory capital — not generic obligations.

Extract one ParameterChange per moved lever. Look hard for, at minimum:
  * Risk weights by exposure class (corporate rated/unrated, sovereign,
    bank, retail, consumer credit / personal loans, residential mortgage,
    CRE, equity — listed/unlisted, NPA secured/unsecured, startups, MSME,
    venture capital).
  * LTV bands / ratios and how they band the risk weight.
  * Credit conversion factors (CCF) for off-balance-sheet items.
  * Capital charges (%), capital conservation buffer, CCyB, leverage ratio.
  * Provisioning rates, haircuts, thresholds, materiality limits.
  * Effective / commencement dates and transitional arrangements.

For EACH ParameterChange emit:
  * parameter       — the lever, e.g. "Risk weight — listed equity exposures".
  * exposure_class  — the segment it applies to (null if global).
  * old_value       — the value under the PRIOR framework (null if newly
                      introduced). Quote the number with its unit, e.g. "125%".
  * new_value       — the value under the NEW framework, e.g. "250%".
  * direction       — increase | decrease | new | removed | restructured |
                      unchanged. Use "restructured" when a flat number becomes
                      a formula/band (e.g. flat 100% → external-rating-banded).
  * unit            — "%", "bps", "x", "ratio", "LTV band", etc.
  * effective_date  — commencement language exactly as written, if stated.
  * crar_impact     — the directional capital effect in one phrase, e.g.
                      "higher risk weight → higher RWA → lower CRAR, all else
                      equal" or "lower CCF → lower RWA → CRAR relief".
  * source_old / source_new — clause or paragraph reference in each document.
  * confidence      — 0.0–1.0; lower when the old value had to be inferred.
  * notes           — any caveat (e.g. "subject to external rating availability").

Rules:
  * Quote actual numbers from the text. NEVER invent a value. If the prior
    value is genuinely not stated in the PRIOR FRAMEWORK text provided, set
    old_value to null, direction to "new", and say so in notes.
  * Emit a row ONLY when a value actually MOVED (direction increase, decrease,
    new, removed, or restructured). DO NOT emit rows where old_value equals
    new_value or direction would be "unchanged" — those waste the response and
    are not changes. If nothing in a batch moved, return an empty list [].
  * Prefer many precise rows over a few vague ones. A real credit-risk
    standardised-approach change has dozens of risk-weight movements.
  * Do not emit obligations or policy edits here — only parameter movements.
"""


def _clean_param_changes(rows: list[ParameterChange]) -> list[ParameterChange]:
    """Drop non-changes and duplicates the model emits despite instructions.

    The model frequently returns ``direction='unchanged'`` rows (e.g. CET1
    5.5%→5.5%) and repeats the same parameter across batches. These are not
    changes and inflate the count (observed: 470 rows, 241 of them
    'unchanged'). Remove them deterministically.
    """
    seen: set[tuple] = set()
    cleaned: list[ParameterChange] = []
    for r in rows:
        direction = (r.direction or "").strip().lower()
        old_v = (r.old_value or "").strip()
        new_v = (r.new_value or "").strip()
        # Not a movement: explicitly unchanged, or old == new with no signal.
        if direction == "unchanged":
            continue
        if old_v and new_v and old_v == new_v and direction not in {"new", "removed"}:
            continue
        key = (
            (r.parameter or "").strip().lower(),
            (r.exposure_class or "").strip().lower(),
            old_v,
            new_v,
        )
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(r)
    return cleaned


def stub_param_diff(
    amended_clauses: list[AmendedClause],
    *,
    comparison_title: str | None = None,
    comparison_text: str | None = None,
) -> list[ParameterChange]:
    """Offline placeholder — no LLM, so no parameter extraction. Returns []."""
    return []


def _truncate(text: str | None, max_chars: int) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    head = int(max_chars * 0.85)
    tail = max_chars - head
    return text[:head] + "\n\n[...truncated...]\n\n" + text[-tail:]


def real_param_diff(
    amended_clauses: list[AmendedClause],
    *,
    new_title: str,
    new_text: str,
    comparison_title: str | None = None,
    comparison_text: str | None = None,
) -> list[ParameterChange]:
    """Extract old→new quantitative parameter changes between two frameworks.

    Needs both the new framework text and the prior framework
    (``comparison_text``). With no comparison document this degrades to an
    empty list — a parameter *diff* needs two sides. The whole extraction is
    a single large-context Gemini call; flash-lite's 1M-token window fits a
    full Master Direction alongside the amending document.
    """
    if not (comparison_text and comparison_text.strip()):
        return []

    from app.runners import require_real_llm, run_agent

    require_real_llm("param_diff")

    # Input sizing is bounded by the model's OUTPUT limit, not its context
    # window: too much input makes the model emit more ParameterChange rows
    # than fit in the ~64K output-token budget, truncating the JSON mid-row
    # so the ENTIRE extraction is lost (invalid JSON). Empirically ~500K
    # input chars yields a complete, rich extraction (~340 changes) that
    # serialises cleanly; higher values silently lose everything. So the
    # cap PROTECTS the analysis rather than restricting it. Tunable via env.
    max_chars = int(os.environ.get("CURATOR_PARAM_DIFF_MAX_CHARS", "500000"))

    # The amending document's clause texts are the densest signal for what
    # the new framework actually says; prepend them so they aren't lost to
    # truncation, then the full new-doc text, then the prior framework.
    clause_blob = "\n\n".join(
        f"[{c.clause_id}] {c.heading or ''}\n{c.new_text}"
        for c in amended_clauses
        if (c.new_text or "").strip()
    )
    new_full = (clause_blob + "\n\n" + (new_text or "")).strip()

    # Pre-diff gate: instead of dumping two full documents (which forces the
    # model to hunt for changes and blows the output-token budget), do the
    # paragraph alignment in plain Python first and feed the model only the
    # aligned old→new deltas, IN BATCHES. Batching bounds the OUTPUT size: a
    # large cross-framework diff yields hundreds of ParameterChange rows that
    # cannot fit in one ~64K-token response, truncating the JSON mid-array and
    # losing everything. Each batch emits a bounded number of rows that
    # serialise cleanly; results are concatenated. Disable with CURATOR_PREDIFF=0.
    if os.environ.get("CURATOR_PREDIFF", "1") != "0":
        import logging

        from app.ingest.prediff import prediff, render_change_blocks, split_paragraphs

        log = logging.getLogger(__name__)
        result = prediff(split_paragraphs(comparison_text), split_paragraphs(new_full))
        log.info("param_diff: %s", result.summary())
        changes = result.ordered_changes()
        if changes:
            batch_size = int(os.environ.get("CURATOR_PARAM_DIFF_BATCH", "60"))
            agent = build_agent()
            all_changes: list[ParameterChange] = []
            n_batches = (len(changes) + batch_size - 1) // batch_size
            for bi in range(n_batches):
                batch = changes[bi * batch_size : (bi + 1) * batch_size]
                blob = render_change_blocks(batch)[:max_chars]
                prompt = (
                    f"NEW FRAMEWORK — {new_title}\n"
                    f"PRIOR FRAMEWORK — "
                    f"{comparison_title or 'consolidated / earlier framework'}\n"
                    f"=================================================\n"
                    f"The blocks below are batch {bi + 1} of {n_batches} of ONLY the\n"
                    f"regions that changed between the prior and new framework, already\n"
                    f"aligned old→new (unchanged text removed in a deterministic pre-pass).\n"
                    f"Extract every quantitative parameter movement per your instructions.\n"
                    f"=================================================\n"
                    f"{blob}\n\n"
                    f"Produce the ParameterChange rows for THIS batch only."
                )
                try:
                    rows = run_agent(agent, prompt, output_schema=list[ParameterChange])
                    all_changes.extend(rows)
                except Exception as exc:  # noqa: BLE001 — one bad batch ≠ lost run
                    log.warning("param_diff batch %d/%d failed: %s", bi + 1, n_batches, exc)
            cleaned = _clean_param_changes(all_changes)
            log.info(
                "param_diff: %d raw → %d real parameter changes across %d batch(es).",
                len(all_changes),
                len(cleaned),
                n_batches,
            )
            return cleaned
        # Fall through to full-document mode if the pre-diff found nothing
        # (e.g. paragraph splitting failed) — never silently return empty.

    new_blob = _truncate(new_full, max_chars)
    old_blob = _truncate(comparison_text, max_chars)

    prompt = (
        f"NEW FRAMEWORK — {new_title}\n"
        f"=================================================\n"
        f"{new_blob}\n\n"
        f"PRIOR FRAMEWORK — {comparison_title or 'consolidated / earlier framework'}\n"
        f"=================================================\n"
        f"{old_blob}\n\n"
        f"Now produce the exhaustive ParameterChange table per your instructions."
    )

    agent = build_agent()
    return _clean_param_changes(
        run_agent(agent, prompt, output_schema=list[ParameterChange])
    )


def build_agent():  # type: ignore[no-untyped-def]
    from google.adk.agents import Agent
    from google.adk.models import Gemini

    from app.llm import curator_model_name

    return Agent(
        name="param_diff_agent",
        model=Gemini(model=curator_model_name()),
        instruction=PARAM_DIFF_INSTRUCTION,
        description=(
            "Diffs two regulatory frameworks and extracts the quantitative "
            "parameters (risk weights, LTV bands, capital charges, effective "
            "dates) that moved, old → new, with CRAR impact."
        ),
        output_schema=list[ParameterChange],
    )
