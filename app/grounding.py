"""Grounding backends for Curator.

Two implementations:
  - MockGroundingBackend: in-memory, reads from ``data/fixtures/``. Works
    today, deterministic, fast — used by every Stage-1 test and the
    offline smoke run.
  - VertexRagBackend: stub. Will wrap Vertex AI RAG Engine in Stage 2.

Residency note for Stage 2: the Vertex AI RAG Engine managed database
runs on Spanner; the current region allow-list is us-central1, us-east1,
us-east4. Indian-resident regulatory data may need a residency review
before Stage-2 ingestion.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

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


class VertexRagBackend(GroundingBackend):
    """TODO(stage-2): wrap Vertex AI RAG Engine.

    Plan:
      - Build a RAG corpus from data/fixtures/ + tenant policy uploads.
      - Region: us-central1 (RAG Engine managed-DB allow-list).
      - Wire ADK VertexAiSearchTool or the RAG Engine retrieval API.
      - Surface citation metadata into RetrievalHit['source'].
    """

    def __init__(self, project: str, location: str = "us-central1") -> None:
        self.project = project
        self.location = location

    def search_master_direction(self, md_id: str, query: str, k: int = 5) -> list[RetrievalHit]:
        raise NotImplementedError("Stage 2: wire Vertex AI RAG Engine")

    def get_master_direction_text(self, md_id: str) -> str:
        raise NotImplementedError("Stage 2")

    def get_amendment_text(self, amendment_id: str) -> str:
        raise NotImplementedError("Stage 2")

    def load_bank_policies(self, bank_id: str = "demo") -> list[PolicyDocument]:
        raise NotImplementedError("Stage 2")


def get_backend() -> GroundingBackend:
    """Factory — stage-1 always returns the mock backend."""
    return MockGroundingBackend()
