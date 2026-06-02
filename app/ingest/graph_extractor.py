"""Document AI ChunkedSection[] → Graph (clauses + entities + relations).

Stage of the pipeline:
    PDF → docai.parse_pdf → ChunkedSection[]  (upstream, D3)
                                  │
                                  ▼
                       graph_extractor.extract_graph   (this module, D4)
                                  │
                                  ▼
              SpannerGraphBackend.ingest_document     (D4, downstream)

What this module does
---------------------
For one document at a time we walk the Doc AI chunks in reading order and
collapse them into ``ExtractedClause`` records — one per heading-rooted
section. The clause's ``new_text`` is the concatenation of the
paragraph / list / table chunks that follow that heading until the next
heading. This mapping mirrors how RBI Master Directions and amendments
read in practice.

We then ask Gemini (via the existing ``run_agent`` helper) to extract a
small entity + relation graph for the whole document in a *single* call —
one prompt per document, batched up to ~30K characters. The agent
returns structured JSON conforming to a small pydantic schema; we
validate, hash-deterministic-id the entities, and return the
``GraphExtractionResult``.

The result is consumed by:
    * ``SpannerGraphBackend.ingest_document`` — writes documents + clauses
      (entities/relations write-out is Phase-5 polish — for D4 we capture
      them in the returned object so callers can persist later if they
      want, but the Spanner writes are clause-scoped).
    * ``pipeline.ingest_two_pdfs`` — orchestrates this for both PDFs.

Failure mode contract
---------------------
If ``chunks`` is empty (or DocAI returned nothing), raise
``GraphExtractionError``. Silent empties are *not* OK — they cascade
into a downstream chain that thinks the document is well-formed.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.ingest.docai import ChunkedSection

# Gemini structured-output context budget per document. Doc AI chunks for
# a 1 MB regulatory PDF land around 5-15 KB total text; 30K leaves room
# for the prompt scaffolding without hitting model token caps.
_MAX_PROMPT_CHARS = 30_000

# Layout types that *start* a new clause. Mirrors docai._HEADING_TYPES
# but kept here in case the upstream set drifts; we want the boundary
# logic owned by the consumer.
_HEADING_LAYOUT_TYPES: frozenset[str] = frozenset(
    {
        "subtitle",
        "title",
        "heading-1",
        "heading-2",
        "heading-3",
        "heading-4",
        "heading-5",
        "section_heading",
        "heading",
    }
)


class GraphExtractionError(RuntimeError):
    """Raised when graph extraction can't proceed (e.g. empty chunks)."""


EntityType = Literal["regulator", "department", "metric", "instrument", "entity"]


class ExtractedClause(BaseModel):
    """One clause derived from a heading-rooted chunk group."""

    clause_id: str
    heading: str | None = None
    new_text: str
    old_text: str | None = None
    change_type: str = "modify"
    ord: int


class Entity(BaseModel):
    """A named entity referenced by one or more clauses."""

    entity_id: str
    name: str
    entity_type: EntityType = "entity"
    mentions_clause_ids: list[str] = Field(default_factory=list)


class Relation(BaseModel):
    """A triple linking two entities, anchored to a source clause."""

    subject_entity_id: str
    predicate: str
    object_entity_id: str
    clause_id: str | None = None


class GraphExtractionResult(BaseModel):
    """Output of ``extract_graph``."""

    doc_id: str
    clauses: list[ExtractedClause] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Clause derivation — purely deterministic, no LLM.
# ---------------------------------------------------------------------------


_WS_RUN = re.compile(r"[ \t]+")
_BLANK_RUN = re.compile(r"\n{3,}")


def _normalise_text(text: str) -> str:
    """Strip surrounding whitespace and collapse runs of blank lines."""
    text = text.strip()
    text = _WS_RUN.sub(" ", text)
    text = _BLANK_RUN.sub("\n\n", text)
    return text


def _is_heading(chunk: ChunkedSection) -> bool:
    return chunk.layout_type in _HEADING_LAYOUT_TYPES


def _derive_clauses(
    chunks: list[ChunkedSection], doc_id: str
) -> list[ExtractedClause]:
    """Walk chunks in order; each heading seeds a new clause.

    Non-heading chunks following a heading are concatenated into the
    clause's ``new_text``. Leading content before the first heading is
    captured as a synthetic preamble clause so the document's opening
    paragraphs aren't lost.
    """
    clauses: list[ExtractedClause] = []
    current_heading: str | None = None
    buf: list[str] = []
    ord_idx = 0

    def _flush() -> None:
        nonlocal ord_idx
        if current_heading is None and not buf:
            return
        text = _normalise_text("\n".join(buf))
        # Drop empty clauses with no heading and no text.
        if not text and current_heading is None:
            return
        clauses.append(
            ExtractedClause(
                clause_id=f"{doc_id}#clause-{ord_idx:04d}",
                heading=current_heading,
                new_text=text,
                old_text=None,
                change_type="modify",
                ord=ord_idx,
            )
        )
        ord_idx += 1

    for chunk in chunks:
        if _is_heading(chunk):
            _flush()
            current_heading = chunk.text.strip()
            buf = []
        else:
            t = chunk.text.strip()
            if t:
                buf.append(t)

    # Tail flush — anything still buffered after the last heading.
    _flush()
    return clauses


# ---------------------------------------------------------------------------
# Entity / relation extraction — LLM-backed, single call per document.
# ---------------------------------------------------------------------------


_ENTITY_RELATION_INSTRUCTION = """You are a regulatory-domain knowledge-graph
extractor. Given the clauses of one regulatory document (an RBI Master
Direction or amendment), identify the high-value named entities and the
relationships between them.

Entities you care about:
  * regulator     — the RBI, central bank, supervisory body.
  * department    — internal bank functions (CFO, CRO, Board, Risk
                    Management Committee, Compliance, ICAAP committee).
  * metric        — quantitative regulatory metrics (CET1 ratio, RWAs,
                    Climate Risk Capital Buffer, leverage ratio).
  * instrument    — financial instruments / disclosure templates
                    (Pillar 3 disclosure, ICAAP document, CET1 capital).
  * entity        — anything else that is named and load-bearing but
                    doesn't fit the four buckets above.

For each entity emit a stable lowercase ``name`` and an ``entity_type``.
For each relation emit a clear predicate (e.g. ``requires``, ``reports_to``,
``measures``, ``regulates``, ``maintains``, ``discloses``). Anchor each
relation to the clause_id where it is grounded.

Be conservative: better to miss a marginal relation than to fabricate.
"""


class _LLMGraphPayload(BaseModel):
    """Shape returned by the LLM. Entities use ``name`` only; the
    deterministic ``entity_id`` is computed in Python so re-runs are
    stable across LLM stochasticity.
    """

    class _LLMEntity(BaseModel):
        name: str
        entity_type: EntityType = "entity"
        mentions_clause_ids: list[str] = Field(default_factory=list)

    class _LLMRelation(BaseModel):
        subject_name: str
        predicate: str
        object_name: str
        clause_id: str | None = None

    entities: list[_LLMEntity] = Field(default_factory=list)
    relations: list[_LLMRelation] = Field(default_factory=list)


def _entity_id_for(name: str) -> str:
    """Deterministic hash id for an entity name."""
    digest = hashlib.sha1(name.strip().lower().encode("utf-8")).hexdigest()
    return f"ent-{digest[:12]}"


def _format_clauses_for_prompt(clauses: list[ExtractedClause]) -> str:
    """Render the clauses as compact JSON-lines for the LLM prompt.

    We truncate at _MAX_PROMPT_CHARS — if a document overshoots, later
    clauses are dropped. This is acceptable for D4 (the RBI fixtures all
    fit comfortably under 30K).
    """
    lines: list[str] = []
    total = 0
    for c in clauses:
        line = (
            f'{{"clause_id": "{c.clause_id}", '
            f'"heading": {repr(c.heading or "")}, '
            f'"text": {repr(c.new_text)}}}'
        )
        if total + len(line) > _MAX_PROMPT_CHARS:
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


def _build_extractor_agent():  # type: ignore[no-untyped-def]
    """Construct the Gemini extractor agent (lazy ADK import)."""
    from google.adk.agents import Agent
    from google.adk.models import Gemini

    return Agent(
        name="graph_extractor",
        model=Gemini(model="gemini-flash-latest"),
        instruction=_ENTITY_RELATION_INSTRUCTION,
        description=(
            "Extracts entities + relations from a regulatory document's "
            "clauses. One call per document."
        ),
        output_schema=_LLMGraphPayload,
    )


def _llm_extract(clauses: list[ExtractedClause]) -> _LLMGraphPayload:
    """Run the extractor agent once for the whole document.

    On any failure we degrade to an empty payload — the deterministic
    clauses are still useful, and downstream graph queries don't depend
    on entities/relations being populated for D4 (lexical clause search
    is the primary retrieval path).
    """
    from app.runners import run_agent

    agent = _build_extractor_agent()
    prompt = _format_clauses_for_prompt(clauses)
    try:
        return run_agent(agent, prompt, output_schema=_LLMGraphPayload)
    except Exception:  # pragma: no cover - degraded path
        return _LLMGraphPayload()


def extract_graph(
    chunks: list[ChunkedSection],
    doc_id: str,
    namespace: str,
    *,
    skip_llm: bool | None = None,
) -> GraphExtractionResult:
    """Convert Doc AI chunks into a graph-shaped extraction.

    Args:
        chunks: ordered ChunkedSection list (the output of
            ``docai.parse_pdf``).
        doc_id: stable doc identifier used to seed clause ids.
        namespace: tenant/demo namespace — stored alongside the doc when
            persisted by ``SpannerGraphBackend.ingest_document``. We
            accept it here so the caller doesn't have to repeat itself,
            though ``extract_graph`` itself doesn't persist anything.
        skip_llm: when True, skip the Gemini entity/relation call and
            return only deterministic clauses. Default is to read the
            env var ``CURATOR_GRAPH_EXTRACT_LLM`` (default off).

    Raises:
        GraphExtractionError: when ``chunks`` is empty.
    """
    if not chunks:
        raise GraphExtractionError(
            f"extract_graph received zero chunks for doc_id={doc_id!r} "
            f"(namespace={namespace!r}). Doc AI either failed or returned "
            "an empty document; refusing to silently emit an empty graph."
        )

    clauses = _derive_clauses(chunks, doc_id)
    if not clauses:
        # The chunks were non-empty but contained no heading-anchored
        # content. Emit a single catch-all clause holding the full text
        # rather than failing entirely — better a degraded ingestion
        # than a hard stop on a malformed PDF.
        joined = _normalise_text("\n".join(c.text for c in chunks if c.text))
        if joined:
            clauses = [
                ExtractedClause(
                    clause_id=f"{doc_id}#clause-0000",
                    heading=None,
                    new_text=joined,
                    old_text=None,
                    change_type="modify",
                    ord=0,
                )
            ]
        else:
            raise GraphExtractionError(
                f"extract_graph: chunks for {doc_id!r} contained no text"
            )

    # Decide whether to actually fire the LLM extractor. The deterministic
    # clauses are the value-add for D4; entities/relations are bonus.
    if skip_llm is None:
        env_val = os.environ.get("CURATOR_GRAPH_EXTRACT_LLM", "0").strip().lower()
        skip_llm = env_val not in {"1", "true", "yes", "on"}

    entities: list[Entity] = []
    relations: list[Relation] = []
    if not skip_llm:
        payload = _llm_extract(clauses)
        # Build the deterministic-id entity list.
        name_to_id: dict[str, str] = {}
        for e in payload.entities:
            name = e.name.strip()
            if not name:
                continue
            eid = _entity_id_for(name)
            name_to_id[name.lower()] = eid
            entities.append(
                Entity(
                    entity_id=eid,
                    name=name,
                    entity_type=e.entity_type,
                    mentions_clause_ids=list(e.mentions_clause_ids or []),
                )
            )
        # Resolve relations by name → id. Drop relations whose endpoints
        # we don't recognise (LLM occasionally invents fillers).
        for r in payload.relations:
            sid = name_to_id.get(r.subject_name.strip().lower())
            oid = name_to_id.get(r.object_name.strip().lower())
            if not sid or not oid:
                continue
            relations.append(
                Relation(
                    subject_entity_id=sid,
                    predicate=r.predicate.strip(),
                    object_entity_id=oid,
                    clause_id=r.clause_id,
                )
            )

    return GraphExtractionResult(
        doc_id=doc_id,
        clauses=clauses,
        entities=entities,
        relations=relations,
    )


__all__ = [
    "GraphExtractionError",
    "GraphExtractionResult",
    "ExtractedClause",
    "Entity",
    "Relation",
    "extract_graph",
]
