"""One-shot validation of the parameter-diff stage on the real
credit-risk SA (Doc A, new) vs consolidated Capital Adequacy MD (Doc B,
prior) sidecar pair. Single large-context Gemini call.

    source scripts/env.sh
    CURATOR_REAL_LLM=1 .venv/bin/python scripts/try_param_diff.py
"""
from __future__ import annotations

from pathlib import Path

from app.ingest.pipeline import ingest_two_pdfs
from app.sub_agents.param_diff import real_param_diff

PDFS = Path("data/fixtures/source_pdfs")
NEW = PDFS / "05_credit_risk_standardised_2026-04-27_RBI-087798ec1547.pdf"
PRIOR = PDFS / "06_basel_iii_master_circular_2025-04-01_RBI-28cfc2fb93e7.pdf"


def main() -> None:
    state = ingest_two_pdfs(NEW, PRIOR, namespace="capital-adequacy", dry_run=True)
    print(f"new title : {state.amendment.title[:90]}")
    print(f"prior     : {(state.comparison_title or '')[:90]}")
    print(f"new chars : {len(state.amendment.raw_text):,}  prior chars: {len(state.comparison_text or ''):,}")
    print(f"clauses   : {len(state.amended_clauses)}")
    print("--- running param_diff (one large-context call) ---")
    changes = real_param_diff(
        state.amended_clauses,
        new_title=state.amendment.title,
        new_text=state.amendment.raw_text,
        comparison_title=state.comparison_title,
        comparison_text=state.comparison_text,
    )
    print(f"\n=== {len(changes)} parameter changes ===\n")
    for c in changes:
        print(
            f"• {c.parameter}"
            + (f" [{c.exposure_class}]" if c.exposure_class else "")
            + f"\n    {c.old_value or 'n/a'} -> {c.new_value} ({c.direction}; {c.unit or ''})"
            + (f"\n    effective: {c.effective_date}" if c.effective_date else "")
            + (f"\n    CRAR: {c.crar_impact}" if c.crar_impact else "")
        )


if __name__ == "__main__":
    main()
