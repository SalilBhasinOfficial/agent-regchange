"""Grounding backends for Curator.

Two implementations:
  - MockGroundingBackend: in-memory, reads from ``data/fixtures/``. Works
    today, deterministic, fast — used by every Stage-1 test, the offline
    smoke run, and the eval harness. **The MockGroundingBackend is the
    airlock; it must keep working.**
  - SpannerGraphBackend (D4+): wraps Spanner Graph for the live demo.
    Lazy Spanner client import keeps this file importable without GCP
    creds.

Residency note: Spanner instance lives in ``asia-south1`` per
DECISIONS-6. Vertex (Gemini reasoning) sits in ``global`` / us-central1
per DECISIONS-9. The cross-region hop is acceptable for the demo
cadence.

Factory contract:
    ``get_grounding_backend()`` reads ``CURATOR_GROUNDING`` (default
    ``"mock"``). The env var is the contract — we never silently fall
    back from spanner to mock; on connection failure we raise.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.models import PolicyDocument, PolicySection

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "data" / "fixtures"


class RetrievalHit(dict):
    """Lightweight retrieval hit — dict-shaped to keep ADK tool returns simple."""


class GroundingBackend(ABC):
    @abstractmethod
    def search_master_direction(self, md_id: str, query: str, k: int = 5) -> list[RetrievalHit]:
        ...

    @abstractmethod
    def get_master_direction_text(self, md_id: str) -> str:
        ...

    @abstractmethod
    def get_amendment_text(self, amendment_id: str) -> str:
        ...

    @abstractmethod
    def load_bank_policies(self, bank_id: str = "demo") -> list[PolicyDocument]:
        ...


class MockGroundingBackend(GroundingBackend):
    """File-system backed mock. Reads markdown + json from data/fixtures/."""

    def __init__(self, fixtures_dir: Path = FIXTURES) -> None:
        self.dir = fixtures_dir

    def _read(self, path: Path) -> str:
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def get_master_direction_text(self, md_id: str) -> str:
        return self._read(self.dir / "master_directions" / f"{md_id}.md")

    def get_amendment_text(self, amendment_id: str) -> str:
        return self._read(self.dir / "amendments" / f"{amendment_id}.md")

    def search_master_direction(self, md_id: str, query: str, k: int = 5) -> list[RetrievalHit]:
        # Deterministic word-overlap scoring — adequate for stage-1 fixtures.
        text = self.get_master_direction_text(md_id)
        if not text:
            return []
        q_terms = {w.lower() for w in query.split() if len(w) > 3}
        # Split on H2 to get clause-like chunks.
        chunks = [c for c in text.split("\n## ") if c.strip()]
        scored: list[tuple[int, str]] = []
        for c in chunks:
            score = sum(1 for t in q_terms if t in c.lower())
            if score:
                scored.append((score, c))
        scored.sort(key=lambda x: -x[0])
        return [RetrievalHit(md_id=md_id, score=s, text=t[:1500]) for s, t in scored[:k]]

    def load_bank_policies(self, bank_id: str = "demo") -> list[PolicyDocument]:
        policy_dir = self.dir / "sample_bank_policy"
        manifest = policy_dir / "manifest.json"
        if not manifest.exists():
            return []
        meta = json.loads(manifest.read_text())
        out: list[PolicyDocument] = []
        for p in meta["policies"]:
            md_text = self._read(policy_dir / p["file"])
            sections: list[PolicySection] = []
            current_heading: str | None = None
            buf: list[str] = []
            sec_idx = 0
            for line in md_text.splitlines():
                if line.startswith("## "):
                    if current_heading is not None:
                        sections.append(
                            PolicySection(
                                policy_section_id=f"{p['policy_id']}#s{sec_idx}",
                                heading=current_heading,
                                text="\n".join(buf).strip(),
                            )
                        )
                        sec_idx += 1
                        buf = []
                    current_heading = line[3:].strip()
                else:
                    buf.append(line)
            if current_heading is not None:
                sections.append(
                    PolicySection(
                        policy_section_id=f"{p['policy_id']}#s{sec_idx}",
                        heading=current_heading,
                        text="\n".join(buf).strip(),
                    )
                )
            out.append(
                PolicyDocument(
                    policy_id=p["policy_id"],
                    title=p["title"],
                    owner_department=p.get("owner_department"),
                    sections=sections,
                )
            )
        return out


# ---------------------------------------------------------------------------
# Spanner Graph backend (D4)
# ---------------------------------------------------------------------------


_DEFAULT_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "curator-research")
_DEFAULT_INSTANCE = os.environ.get("SPANNER_INSTANCE", "curator-graph")
_DEFAULT_DATABASE = os.environ.get("SPANNER_DATABASE", "curator")


class SpannerGraphBackend(GroundingBackend):
    """Spanner-backed grounding for the live demo path.

    The backend persists ingested PDFs into the ``documents`` + ``clauses``
    tables defined in ``app/ingest/spanner_schema.sql`` and serves them
    back to the chain via lexical retrieval (LIKE) for D4. Vector-index
    retrieval is Phase-5 polish.

    Bank-policy data is *not* PDF-ingested for D4 — the demo bank's
    internal policies live in ``data/fixtures/sample_bank_policy/``. We
    delegate ``load_bank_policies`` to ``MockGroundingBackend`` until a
    real bank corpus arrives (D5+).
    """

    def __init__(
        self,
        project: str | None = None,
        instance_id: str | None = None,
        database_id: str | None = None,
    ) -> None:
        self.project = project or _DEFAULT_PROJECT
        self.instance_id = instance_id or _DEFAULT_INSTANCE
        self.database_id = database_id or _DEFAULT_DATABASE
        self._client = None
        self._database = None
        # Mock delegate for the bank-policy path (D4 — see class docstring).
        self._mock_for_policies = MockGroundingBackend()

    # ----- Spanner connection helpers ---------------------------------------

    def _ensure_database(self):  # type: ignore[no-untyped-def]
        """Lazy Spanner client + database handle.

        Raises a clear error on connection failure — we deliberately do
        NOT silently fall back to MockGroundingBackend. The env var is
        the contract.
        """
        if self._database is not None:
            return self._database
        try:
            from google.cloud import spanner  # local import — no GCP at module load
        except Exception as e:  # pragma: no cover - dep missing
            raise RuntimeError(
                "google-cloud-spanner is not installed but "
                "SpannerGraphBackend was requested. Add it via "
                "`uv add google-cloud-spanner`."
            ) from e

        try:
            client = spanner.Client(project=self.project)
            instance = client.instance(self.instance_id)
            database = instance.database(self.database_id)
            # Lightweight existence check — fetching the database session
            # surface raises a clean error on misconfiguration.
            database.reload()
        except Exception as e:
            raise RuntimeError(
                "SpannerGraphBackend failed to connect to "
                f"spanner://{self.project}/{self.instance_id}/{self.database_id}: "
                f"{e}"
            ) from e

        self._client = client
        self._database = database
        return database

    # ----- ingestion --------------------------------------------------------

    def ingest_document(
        self,
        doc_id: str,
        namespace: str,
        source_pdf_path: str | None,
        title: str | None,
        doc_kind: str,
        raw_text: str | None,
        clauses,
    ) -> None:
        """Write a document + its clauses into Spanner.

        ``clauses`` accepts either ``ExtractedClause`` objects or plain
        dicts with the same field names — we duck-type via getattr.
        Each row is upserted with ``insert_or_update`` so re-ingestion
        of the same doc_id is idempotent.
        """
        database = self._ensure_database()
        from google.cloud import spanner  # local for spanner.COMMIT_TIMESTAMP

        def _txn(txn) -> None:
            txn.insert_or_update(
                table="documents",
                columns=(
                    "doc_id",
                    "namespace",
                    "source_url",
                    "source_pdf_path",
                    "title",
                    "doc_kind",
                    "ingested_at",
                    "raw_text",
                ),
                values=[
                    (
                        doc_id,
                        namespace,
                        None,
                        source_pdf_path,
                        title,
                        doc_kind,
                        spanner.COMMIT_TIMESTAMP,
                        raw_text,
                    )
                ],
            )

            rows = []
            for c in clauses:
                clause_id = getattr(c, "clause_id", None) or c["clause_id"]
                heading = getattr(c, "heading", None) if not isinstance(c, dict) else c.get("heading")
                new_text = getattr(c, "new_text", None) if not isinstance(c, dict) else c.get("new_text")
                old_text = getattr(c, "old_text", None) if not isinstance(c, dict) else c.get("old_text")
                change_type = (
                    getattr(c, "change_type", "modify")
                    if not isinstance(c, dict)
                    else c.get("change_type", "modify")
                )
                ord_ = getattr(c, "ord", None) if not isinstance(c, dict) else c.get("ord")
                rows.append(
                    (
                        doc_id,
                        clause_id,
                        heading,
                        old_text,
                        new_text,
                        change_type,
                        ord_,
                    )
                )
            if rows:
                txn.insert_or_update(
                    table="clauses",
                    columns=(
                        "doc_id",
                        "clause_id",
                        "heading",
                        "old_text",
                        "new_text",
                        "change_type",
                        "ord",
                    ),
                    values=rows,
                )

        database.run_in_transaction(_txn)

    # ----- retrieval --------------------------------------------------------

    def search_master_direction(
        self, md_id: str, query: str, k: int = 5
    ) -> list[RetrievalHit]:
        """Lexical LIKE search against the document's clauses.

        D4 implementation note: this is lexical-only (``LOWER(new_text)
        LIKE %query%``). Vector-embedding retrieval lives in
        Phase-5 polish — once Spanner vector indexes are populated we'll
        switch this to KNN. The signature is stable so callers don't
        have to change.
        """
        database = self._ensure_database()
        if not query.strip():
            return []
        like = f"%{query.strip().lower()}%"
        sql = (
            "SELECT clause_id, heading, new_text "
            "FROM clauses "
            "WHERE doc_id = @doc_id "
            "AND LOWER(new_text) LIKE @q "
            "ORDER BY ord "
            "LIMIT @k"
        )
        params = {"doc_id": md_id, "q": like, "k": int(k)}
        param_types = None
        with database.snapshot() as snap:
            rows = list(
                snap.execute_sql(sql, params=params, param_types=param_types)
            )
        return [
            RetrievalHit(
                md_id=md_id,
                clause_id=r[0],
                heading=r[1],
                text=(r[2] or "")[:1500],
                score=1.0,  # lexical hit; phase-5 will replace with cosine sim.
            )
            for r in rows
        ]

    def _concat_clauses(self, doc_id: str) -> str:
        database = self._ensure_database()
        sql = (
            "SELECT heading, new_text "
            "FROM clauses WHERE doc_id = @doc_id ORDER BY ord"
        )
        with database.snapshot() as snap:
            rows = list(snap.execute_sql(sql, params={"doc_id": doc_id}))
        parts: list[str] = []
        for heading, new_text in rows:
            if heading:
                parts.append(f"## {heading}")
            if new_text:
                parts.append(new_text)
        return "\n\n".join(p for p in parts if p)

    def get_master_direction_text(self, md_id: str) -> str:
        return self._concat_clauses(md_id)

    def get_amendment_text(self, amendment_id: str) -> str:
        return self._concat_clauses(amendment_id)

    def load_bank_policies(self, bank_id: str = "demo") -> list[PolicyDocument]:
        """Delegate to MockGroundingBackend for D4.

        The demo bank's internal policies are not part of the two-PDF
        ingestion input; they live in ``data/fixtures/sample_bank_policy/``.
        TODO(D5+): when bank policies migrate to a real corpus (Spanner
        ``policy_sections`` table is already provisioned), replace this
        delegate with a Spanner query keyed on ``bank_id``.
        """
        return self._mock_for_policies.load_bank_policies(bank_id)

    # ----- metadata helpers (consumed by ingest/pipeline.py) ----------------

    def get_amendment_metadata(self, amendment_id: str) -> dict[str, Any]:
        """Return ``{title, effective_date, master_direction_id, notification_url}``.

        ``master_direction_id`` and ``notification_url`` are best-effort:
        the ingestion pipeline can supplement these via a sidecar JSON
        manifest if available. For the two-PDF demo we map the master
        direction from the document namespace convention (see
        ``pipeline.ingest_two_pdfs``).
        """
        database = self._ensure_database()
        sql = (
            "SELECT title, source_url, source_pdf_path "
            "FROM documents WHERE doc_id = @doc_id"
        )
        with database.snapshot() as snap:
            rows = list(snap.execute_sql(sql, params={"doc_id": amendment_id}))
        if not rows:
            return {
                "title": amendment_id,
                "effective_date": None,
                "master_direction_id": None,
                "notification_url": None,
            }
        title, source_url, _pdf_path = rows[0]
        return {
            "title": title or amendment_id,
            "effective_date": None,
            "master_direction_id": None,
            "notification_url": source_url,
        }

    # ----- graph neighbourhood (Reflector hook, D4) ------------------------

    def query_graph_neighborhood(
        self,
        node_id: str,
        depth: int = 2,
        requeries: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return clauses around ``node_id`` plus any matching the requeries.

        D4 implementation: lexical only.
            * Pull the clause(s) whose ``clause_id == node_id``.
            * Additionally pull any clauses whose ``new_text`` matches
              any of the ``requeries`` strings (LIKE).
        Returns a list of dicts ``{clause_id, heading, text_snippet}``
        — kept dict-shaped so the Reflector can feed them back into the
        panel without coupling to internal pydantic types.

        ``depth`` is accepted for forward-compatibility with property-
        graph traversal (Phase-5) but is otherwise ignored in D4.
        """
        del depth  # placeholder; phase-5 will use this for graph traversal.
        database = self._ensure_database()
        hits: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        def _add_rows(rows) -> None:
            for clause_id, heading, new_text in rows:
                if clause_id in seen_ids:
                    continue
                seen_ids.add(clause_id)
                hits.append(
                    {
                        "clause_id": clause_id,
                        "heading": heading,
                        "text_snippet": (new_text or "")[:800],
                    }
                )

        # 1) the anchor clause itself (across all docs).
        with database.snapshot() as snap:
            anchor_rows = list(
                snap.execute_sql(
                    "SELECT clause_id, heading, new_text "
                    "FROM clauses WHERE clause_id = @cid LIMIT 5",
                    params={"cid": node_id},
                )
            )
        _add_rows(anchor_rows)

        # 2) requery hits.
        for q in requeries or []:
            q = q.strip()
            if not q:
                continue
            like = f"%{q.lower()}%"
            with database.snapshot() as snap:
                rs = list(
                    snap.execute_sql(
                        "SELECT clause_id, heading, new_text "
                        "FROM clauses WHERE LOWER(new_text) LIKE @q LIMIT 5",
                        params={"q": like},
                    )
                )
            _add_rows(rs)

        return hits


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


_GROUNDING_ENV = "CURATOR_GROUNDING"


def get_grounding_backend() -> GroundingBackend:
    """Return a backend based on ``CURATOR_GROUNDING`` env var.

    Values:
        ``mock``      — MockGroundingBackend (default; offline; airlock).
        ``spanner``   — SpannerGraphBackend (live; requires GCP creds).

    Unknown values fall back to the mock with a printed warning so a
    typo doesn't accidentally hit Spanner in a CI environment.
    """
    val = os.environ.get(_GROUNDING_ENV, "mock").strip().lower()
    if val == "spanner":
        return SpannerGraphBackend()
    if val and val != "mock":  # pragma: no cover - operator warning
        print(
            f"[grounding] Unknown CURATOR_GROUNDING={val!r}; "
            "falling back to MockGroundingBackend."
        )
    return MockGroundingBackend()


# Backwards-compat alias used by older callers (e.g. retrievers.py).
def get_backend() -> GroundingBackend:
    """Legacy factory — defers to ``get_grounding_backend``."""
    return get_grounding_backend()


__all__ = [
    "GroundingBackend",
    "MockGroundingBackend",
    "SpannerGraphBackend",
    "RetrievalHit",
    "get_grounding_backend",
    "get_backend",
]
