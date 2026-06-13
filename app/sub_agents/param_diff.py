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
import re

from app.models import AmendedClause, ParameterChange

PARAM_DIFF_INSTRUCTION = """You are a senior regulation analyst at an Indian
financial institution, reviewing a change from one of RBI / SEBI / IRDAI (or a
similar regulator). You are given TWO regulatory documents:

  * NEW FRAMEWORK — the amending / latest document.
  * PRIOR FRAMEWORK — the consolidated or earlier document it changes.

Your single job: produce a precise table of the QUANTITATIVE parameters that
MOVED between the prior and the new framework. This is for a Chief Compliance
Officer who needs to know exactly which numbers changed and their effect — not
generic obligations.

A "quantitative parameter" is ANY measurable lever the regulation sets, for
example (extract whichever apply to THIS document's domain):
  * Thresholds & limits — monetary limits, materiality thresholds, exposure
    caps, concentration limits, position limits, shareholding/holding limits.
  * Timelines & frequencies — reporting/filing deadlines, disclosure windows,
    cure/remediation periods, updation cycles, retention periods, cooling-off
    periods, "within N days/hours".
  * Rates, fees & charges — interest/penalty rates, fees, levies, commissions,
    haircuts, provisioning rates.
  * Ratios & percentages — any prescribed %, ratio, or band.
  * Prudential/capital levers (when the document is prudential) — risk weights
    by exposure class, LTV bands, credit-conversion factors (CCF), capital
    charges, capital conservation buffer, CCyB, leverage ratio.
  * Effective / commencement dates and transitional arrangements.

For EACH ParameterChange emit:
  * parameter       — the lever, e.g. "Risk weight — listed equity exposures",
                      "Periodic KYC updation cycle (low-risk)", "Disclosure
                      window for material events".
  * exposure_class  — the segment/category it applies to (null if global).
  * old_value       — the value under the PRIOR framework (null if newly
                      introduced). Quote the number with its unit, e.g. "125%",
                      "10 years", "₹50 lakh", "30 days".
  * new_value       — the value under the NEW framework, e.g. "250%", "12 years".
  * direction       — increase | decrease | new | removed | restructured |
                      unchanged. Use "restructured" when a flat number becomes
                      a formula/band (e.g. flat 100% → external-rating-banded).
  * unit            — "%", "bps", "x", "ratio", "days", "years", "₹", etc.
  * effective_date  — commencement language exactly as written, if stated.
  * crar_impact     — the directional effect in one phrase. For PRUDENTIAL
                      levers use the capital chain ("higher risk weight → higher
                      RWA → lower CRAR"). For non-prudential levers state the
                      relevant compliance/operational effect instead ("shorter
                      window → tighter reporting SLA") — never force a capital
                      framing onto a non-capital change.
  * source_old / source_new — clause or paragraph reference in each document.
  * confidence      — 0.0–1.0; lower when the old value had to be inferred.
  * notes           — any caveat (e.g. "subject to external rating availability").

Rules:
  * Quote actual numbers from the text. NEVER invent a value. If the prior
    value is genuinely not stated in the PRIOR FRAMEWORK text provided, set
    old_value to null, direction to "new", and say so in notes.
  * Emit a row ONLY when a value actually MOVED (direction increase, decrease,
    new, removed, or restructured). DO NOT emit rows where old_value equals
    new_value or direction would be "unchanged".
  * If this document is purely narrative / qualitative and contains NO
    quantitative parameters (e.g. a conduct or principles circular with no
    numbers, deadlines, or limits), return an empty list []. Do NOT manufacture
    parameters from section numbers, form numbers, or clause references.
  * Prefer many precise rows over a few vague ones where the document is genuinely
    quantitative (a credit-risk standardised-approach change has dozens of
    risk-weight movements); but do not pad a sparse document.
  * Do not emit obligations or policy edits here — only parameter movements.
"""


# Generic prudential vocabulary that does NOT distinguish one parameter from
# another — excluded when fingerprinting a row's concept against the prior text.
_GENERIC_PARAM_WORDS = frozenset(
    {
        "risk", "weight", "weights", "rate", "rates", "ratio", "ratios",
        "factor", "factors", "exposure", "exposures", "capital", "charge",
        "charges", "value", "values", "minimum", "maximum", "requirement",
        "requirements", "limit", "limits", "band", "bands", "cent", "percent",
        "amount", "level", "threshold", "thresholds", "applicable", "general",
    }
)


def _distinctive_tokens(*fields: str | None) -> set[str]:
    """Content words (len>3, non-generic, non-numeric) that name a concept."""
    toks: set[str] = set()
    for f in fields:
        for w in re.split(r"[^a-z0-9]+", (f or "").lower()):
            if len(w) > 3 and not w.isdigit() and w not in _GENERIC_PARAM_WORDS:
                toks.add(w)
    return toks


def _normalize_for_match(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").lower())


def _clean_param_changes(
    rows: list[ParameterChange], *, comparison_text: str | None = None
) -> list[ParameterChange]:
    """Drop non-changes/duplicates, then suppress restatements of prior text.

    Two passes:

    1. Deterministic hygiene — drop ``direction='unchanged'`` rows (e.g. CET1
       5.5%→5.5%), ``removed`` rows with no original value, mislabelled
       old==new rows, and cross-batch duplicates (observed: 470 raw rows, 241
       'unchanged').
    2. *Evidence-based restatement suppression* — a ``new`` row carries a null
       ``old_value`` by definition. It is only *genuinely* new if its concept is
       ABSENT from the prior framework. When the pre-diff aligns a restatement
       into an "added" block (common: a credit-risk SA Direction repeats Basel
       weights in different wording), the model emits a null-old ``new`` row for
       a parameter that already existed — so we drop a ``new`` row only when ALL
       its distinctive tokens (parameter + exposure_class, minus generic words)
       already appear in the prior text. Rows that cite a prior value, or are
       increase/decrease/restructured movements, are always kept. This replaces
       the earlier all-or-nothing global flip, which wrongly discarded genuinely
       new levers whenever any single movement existed. Empty-guard: if this
       would drop everything (a brand-new-table amendment, or no prior text),
       keep the cleaned set so the run is never blanked.
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
        # A "removed" row with no original value is unverifiable noise (the
        # model can't cite what was removed) — drop it.
        if direction == "removed" and not old_v:
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

    prior = _normalize_for_match(comparison_text)

    def _is_restatement(r: ParameterChange) -> bool:
        if (r.direction or "").strip().lower() != "new":
            return False
        if (r.old_value or "").strip():  # cites a prior value → keep
            return False
        if not prior:  # can't verify without prior text → keep
            return False
        toks = _distinctive_tokens(r.parameter, r.exposure_class)
        if not toks:
            return False
        # The concept already exists in the prior framework → not genuinely new.
        return all(t in prior for t in toks)

    kept = [r for r in cleaned if not _is_restatement(r)]
    return kept if kept else cleaned


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
        # Only feed SUBSTANTIVE changes (modified + added) to the model. A
        # "removed" block is prior-framework text not restated in the new doc —
        # when a 3-page amendment is diffed against a 400-page master, almost
        # the entire master reads as "removed", producing hundreds of
        # unverifiable null-old "removed parameters" (observed: 388/425). Genuine
        # value changes are "modified"; genuinely new levers are "added".
        # Withdrawals belong in the impact narrative, not as null-valued rows.
        changes = [c for c in result.ordered_changes() if c.kind != "removed"]
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
            cleaned = _clean_param_changes(all_changes, comparison_text=comparison_text)
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
        run_agent(agent, prompt, output_schema=list[ParameterChange]),
        comparison_text=comparison_text,
    )


def build_agent():  # type: ignore[no-untyped-def]
    from google.adk.agents import Agent
    from google.adk.models import Gemini

    from app.llm import curator_generation_config, curator_model_name

    return Agent(
        name="param_diff_agent",
        model=Gemini(model=curator_model_name()),
        generate_content_config=curator_generation_config(),
        instruction=PARAM_DIFF_INSTRUCTION,
        description=(
            "Diffs two regulatory frameworks and extracts the quantitative "
            "parameters (risk weights, LTV bands, capital charges, effective "
            "dates) that moved, old → new, with CRAR impact."
        ),
        output_schema=list[ParameterChange],
    )
