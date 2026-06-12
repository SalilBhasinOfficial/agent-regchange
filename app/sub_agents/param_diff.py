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
  * Prefer many precise rows over a few vague ones. A real credit-risk
    standardised-approach change has dozens of risk-weight movements.
  * Do not emit obligations or policy edits here — only parameter movements.
"""


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
    # aligned old→new deltas. Smaller input → no JSON truncation, lower cost,
    # and the model sees pairs rather than haystacks. Disable with
    # CURATOR_PREDIFF=0 to restore the full-document behavior.
    if os.environ.get("CURATOR_PREDIFF", "1") != "0":
        import logging

        from app.ingest.prediff import prediff, split_paragraphs

        result = prediff(
            split_paragraphs(comparison_text),
            split_paragraphs(new_full),
        )
        logging.getLogger(__name__).info("param_diff: %s", result.summary())
        changed_blob = result.changed_blob(max_chars)
        if changed_blob.strip():
            prompt = (
                f"NEW FRAMEWORK — {new_title}\n"
                f"PRIOR FRAMEWORK — {comparison_title or 'consolidated / earlier framework'}\n"
                f"=================================================\n"
                f"The paragraphs below are ONLY the regions that changed between the\n"
                f"prior and new framework, already aligned old→new (unchanged text has\n"
                f"been removed in a deterministic pre-pass). Extract every quantitative\n"
                f"parameter movement from these changes per your instructions.\n"
                f"=================================================\n"
                f"{changed_blob}\n\n"
                f"Now produce the exhaustive ParameterChange table."
            )
            agent = build_agent()
            return run_agent(agent, prompt, output_schema=list[ParameterChange])
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
    return run_agent(agent, prompt, output_schema=list[ParameterChange])


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
