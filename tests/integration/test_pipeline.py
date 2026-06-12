"""D4 ingestion pipeline + SpannerGraphBackend integration tests.

Both tests below require live GCP credentials. The whole module is
hard-skipped at collection time when ``CURATOR_LIVE_GCP != "1"`` so the
default ``pytest tests/integration -q`` run never hits a billable API.

Run live with:

    source scripts/env.sh
    CURATOR_LIVE_GCP=1 \\
    CURATOR_DOCAI_PROCESSOR_ID=projects/<num>/locations/us/processors/<id> \\
    uv run pytest tests/integration/test_pipeline.py -q
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

if os.environ.get("CURATOR_LIVE_GCP", "0") != "1":
    pytest.skip(
        "Set CURATOR_LIVE_GCP=1 to run live ingestion / Spanner integration tests",
        allow_module_level=True,
    )

# Imports below are deferred until after the skip-gate so a CI box
# without google-cloud-spanner / documentai still collects cleanly.
from app.grounding import SpannerGraphBackend  # noqa: E402
from app.ingest.graph_extractor import ExtractedClause  # noqa: E402
from app.ingest.pipeline import ingest_two_pdfs  # noqa: E402
from app.models import AgentState  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PDF_A = (
    _REPO_ROOT
    / "data"
    / "fixtures"
    / "source_pdfs"
    / "02_second_amendment_2026-02-13_RBI-dbecd9fe73f6.pdf"
)
_PDF_B = (
    _REPO_ROOT
    / "data"
    / "fixtures"
    / "source_pdfs"
    / "03_third_amendment_2026-03-10_RBI-aaafe4b91697.pdf"
)


def test_ingest_two_pdfs_dry_run() -> None:
    """Dry-run orchestrator: Doc AI live, Spanner skipped.

    Asserts that:
      * the returned state is an ``AgentState``,
      * ``amendment`` is populated,
      * ``amended_clauses`` has at least 3 entries (regulatory PDFs
        comfortably produce >3 clauses),
      * ``policies`` has at least 3 entries (the four mock policies
        loaded from the fixture manifest).
    """
    assert _PDF_A.exists(), f"missing fixture: {_PDF_A}"
    assert _PDF_B.exists(), f"missing fixture: {_PDF_B}"

    state = ingest_two_pdfs(
        pdf_a=_PDF_A,
        pdf_b=_PDF_B,
        namespace=f"test-dry-{uuid.uuid4().hex[:8]}",
        dry_run=True,
    )

    assert isinstance(state, AgentState)
    assert state.amendment is not None, "amendment was not populated"
    assert state.amendment.amendment_id, "amendment_id is empty"
    assert state.amendment.raw_text, "amendment raw_text is empty"
    assert len(state.amended_clauses) >= 3, (
        f"expected >=3 amended_clauses, got {len(state.amended_clauses)}"
    )
    assert len(state.policies) >= 3, (
        f"expected >=3 mock bank policies, got {len(state.policies)}"
    )


def test_spanner_graph_backend_round_trip() -> None:
    """Ingest 3 synthetic clauses, read them back via the backend, clean up.

    Exercises ``ingest_document``, ``get_master_direction_text``,
    ``search_master_direction``, and the SQL ``DELETE`` path used for
    test cleanup.
    """
    backend = SpannerGraphBackend()
    doc_id = f"test-roundtrip-{uuid.uuid4().hex[:8]}"
    namespace = "test-pipeline"
    clauses = [
        ExtractedClause(
            clause_id=f"{doc_id}#clause-0000",
            heading="Climate Risk Capital Buffer",
            new_text=(
                "Every bank shall maintain an additional Climate Risk Capital "
                "Buffer of 0.25 per cent of RWAs in the form of CET1 capital."
            ),
            old_text=None,
            change_type="insert",
            ord=0,
        ),
        ExtractedClause(
            clause_id=f"{doc_id}#clause-0001",
            heading="Quarterly ICAAP Refresh",
            new_text=(
                "A bank's Board of Directors shall assess and document, at "
                "least once every calendar quarter, whether the policies, "
                "procedures and limits remain appropriate."
            ),
            old_text="(prior text)",
            change_type="modify",
            ord=1,
        ),
        ExtractedClause(
            clause_id=f"{doc_id}#clause-0002",
            heading="Pillar 3 Disclosure",
            new_text=(
                "A bank shall disclose the Climate Risk Capital Buffer with "
                "quantitative breakdown by exposure class, effective FY 2027-28."
            ),
            old_text=None,
            change_type="modify",
            ord=2,
        ),
    ]

    backend.ingest_document(
        doc_id=doc_id,
        namespace=namespace,
        source_pdf_path=None,
        title="Synthetic Test Document",
        doc_kind="master_direction",
        raw_text="Synthetic raw text for round-trip test.",
        clauses=clauses,
    )

    try:
        text = backend.get_master_direction_text(doc_id)
        assert "Climate Risk Capital Buffer" in text, (
            f"round-tripped text missing CRCB heading: {text[:300]}"
        )
        assert "ICAAP" in text, "round-tripped text missing ICAAP clause"

        hits = backend.search_master_direction(doc_id, "Climate", k=5)
        assert hits, "lexical search returned no hits for 'Climate'"
        assert any(
            "Climate" in (h.get("text") or "") for h in hits
        ), "no hit contained 'Climate' in its text"

        # query_graph_neighborhood: anchor on the second clause, plus a
        # lexical re-query for 'ICAAP'.
        nbr = backend.query_graph_neighborhood(
            node_id=f"{doc_id}#clause-0001",
            depth=2,
            requeries=["ICAAP"],
        )
        assert nbr, "graph neighbourhood returned empty for known clause"
        assert any(
            n["clause_id"] == f"{doc_id}#clause-0001" for n in nbr
        ), "anchor clause not in neighbourhood result"

    finally:
        # Cleanup — delete via DML so we don't leave test rows behind.
        database = backend._ensure_database()

        def _delete(txn) -> None:
            txn.execute_update(
                "DELETE FROM clauses WHERE doc_id = @doc_id",
                params={"doc_id": doc_id},
            )
            txn.execute_update(
                "DELETE FROM documents WHERE doc_id = @doc_id",
                params={"doc_id": doc_id},
            )

        database.run_in_transaction(_delete)
