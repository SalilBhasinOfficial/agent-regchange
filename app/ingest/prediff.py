"""Programmatic pre-diff — classify paragraphs BEFORE spending any LLM call.

When two regulatory documents are compared, most paragraphs are either
byte-identical (a re-issued master direction carries 80-95% unchanged
text) or trivially reworded. Sending every paragraph to the four-lens
debate panel (which costs 4 LLM calls *per clause*) or dumping both full
documents into the parameter-diff call (which then truncates its own JSON
output) is wasteful and lossy.

This module does the cheap, deterministic work in plain Python first:

  1. **Normalize** each paragraph for *matching only* — NFKC, lowercase,
     collapse whitespace, straighten quotes. Digits, ``%``, decimals and
     dates are PRESERVED, so a ``125% -> 250%`` change always makes the
     normalized strings differ and is never mistaken for "unchanged".
  2. **Align** old vs new with ``difflib.SequenceMatcher`` and classify
     each new paragraph as unchanged / modified / added (and each dropped
     old paragraph as removed).
  3. Hand the caller only the genuine deltas.

Two consumers:

  * :func:`filter_unchanged_clauses` — drops clauses whose text is
    byte-identical (after normalization) to a paragraph in the prior
    document, so the decompose panel only debates clauses that actually
    changed. **Exact-match only** — never similarity — because a clause
    that changed only a number is ~0.97 similar to its old self and must
    NOT be dropped.
  * :func:`prediff` + :meth:`PrediffResult.changed_blob` — builds a
    compact "changed regions" blob of aligned old->new pairs for the
    parameter-diff call, replacing the two full-document blobs. Optional
    similarity mode pairs reworded paragraphs so the model sees an aligned
    old/new pair instead of hunting two haystacks. Similarity only affects
    *pairing for display*; it never drops a paragraph.

Everything here is deterministic and offline — zero LLM, zero GCP.
"""

from __future__ import annotations

import difflib
import os
import re
import unicodedata
from dataclasses import dataclass, field

__all__ = [
    "normalize_text",
    "split_paragraphs",
    "ParaChange",
    "PrediffResult",
    "prediff",
    "filter_unchanged_clauses",
]


# --------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")
# Smart punctuation → ASCII so cosmetic encoding differences don't read as
# changes. Note: NO digit / percent / decimal stripping — those carry the
# regulatory values we must keep sensitive to.
_PUNCT_MAP = {
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    "•": "",
    " ": " ",
    "​": "",
}
_PUNCT_RE = re.compile("|".join(re.escape(k) for k in _PUNCT_MAP))


def normalize_text(s: str) -> str:
    """Normalize a paragraph for *matching only*.

    Lowercases, straightens smart punctuation, and collapses whitespace.
    Digits, ``%``, decimal points and dates are preserved verbatim, so any
    numeric movement defeats an "unchanged" match.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = _PUNCT_RE.sub(lambda m: _PUNCT_MAP[m.group(0)], s)
    s = s.lower()
    s = _WS_RE.sub(" ", s).strip()
    return s


_PARA_SPLIT_RE = re.compile(r"\n\s*\n+")


def split_paragraphs(text: str | None, *, min_chars: int = 1) -> list[str]:
    """Split a raw text blob into paragraph units.

    Splits on blank lines first; if that yields a single huge block (text
    joined with single newlines) it falls back to single-newline splitting.
    Empty / whitespace-only fragments are dropped.
    """
    if not text or not text.strip():
        return []
    parts = [p.strip() for p in _PARA_SPLIT_RE.split(text) if p.strip()]
    if len(parts) <= 1:
        parts = [p.strip() for p in text.splitlines() if p.strip()]
    if min_chars > 1:
        parts = [p for p in parts if len(p) >= min_chars]
    return parts


# --------------------------------------------------------------------------
# Diff classification
# --------------------------------------------------------------------------


@dataclass
class ParaChange:
    """One classified delta between the prior and new document."""

    kind: str  # "modified" | "added" | "removed"
    old_text: str | None
    new_text: str | None


@dataclass
class PrediffResult:
    total_new: int
    unchanged: int
    changes: list[ParaChange] = field(default_factory=list)

    @property
    def modified(self) -> int:
        return sum(1 for c in self.changes if c.kind == "modified")

    @property
    def added(self) -> int:
        return sum(1 for c in self.changes if c.kind == "added")

    @property
    def removed(self) -> int:
        return sum(1 for c in self.changes if c.kind == "removed")

    @property
    def changed_new(self) -> int:
        """New-document units that still need the LLM (modified + added)."""
        return self.modified + self.added

    def summary(self) -> str:
        pct = (self.unchanged * 100) // max(self.total_new, 1)
        return (
            f"prediff: {self.total_new} new units — {self.unchanged} unchanged "
            f"({pct}%, skipped), {self.modified} modified, {self.added} added, "
            f"{self.removed} removed → {self.changed_new} reach the LLM"
        )

    def ordered_changes(self) -> list[ParaChange]:
        """Changes ordered modified → added → removed.

        ``modified`` / ``added`` carry the new_value the parameter-diff
        extracts, so they come first; ``removed`` (prior-only text — noise for
        a cross-framework pair, a withdrawal flag for a version diff) comes
        last, so any truncation/batching drops removed before aligned pairs.
        """
        return (
            [c for c in self.changes if c.kind == "modified"]
            + [c for c in self.changes if c.kind == "added"]
            + [c for c in self.changes if c.kind == "removed"]
        )

    def changed_blob(self, max_chars: int) -> str:
        """Render all deltas as aligned old→new pairs for a diff LLM call."""
        blob = render_change_blocks(self.ordered_changes())
        if len(blob) > max_chars:
            blob = blob[:max_chars] + "\n\n[...further changes truncated...]"
        return blob


def render_change_blocks(changes: list[ParaChange]) -> str:
    """Render a list of ParaChange as numbered old→new blocks for an LLM."""
    out: list[str] = []
    for n, c in enumerate(changes):
        if c.kind == "removed":
            block = f"[CHANGE {n + 1}] REMOVED\nPRIOR: {c.old_text}"
        elif c.kind == "added":
            block = f"[CHANGE {n + 1}] ADDED (new in this framework)\nNEW: {c.new_text}"
        else:  # modified
            block = (
                f"[CHANGE {n + 1}] MODIFIED\n"
                f"PRIOR: {c.old_text}\n"
                f"NEW:   {c.new_text}"
            )
        out.append(block)
    return "\n\n".join(out)


def _mode() -> str:
    m = os.environ.get("CURATOR_PREDIFF_MODE", "exact").strip().lower()
    return m if m in {"exact", "similarity"} else "exact"


def _threshold() -> float:
    try:
        return float(os.environ.get("CURATOR_PREDIFF_THRESHOLD", "0.6"))
    except ValueError:
        return 0.6


def prediff(
    old_units: list[str],
    new_units: list[str],
    *,
    mode: str | None = None,
    threshold: float | None = None,
) -> PrediffResult:
    """Classify every new paragraph against the prior document.

    ``mode``:
      * ``"exact"`` (default) — only byte-identical (normalized) paragraphs
        are unchanged; everything else is modified/added/removed.
      * ``"similarity"`` — additionally pairs reworded paragraphs (old vs
        new) whose similarity ratio >= ``threshold`` into a single
        "modified" delta, so the diff LLM sees an aligned pair rather than
        a separate add + remove. Never marks anything unchanged that the
        exact pass didn't — a reworded paragraph still reaches the LLM.
    """
    mode = mode or _mode()
    threshold = threshold if threshold is not None else _threshold()

    norm_old = [normalize_text(u) for u in old_units]
    norm_new = [normalize_text(u) for u in new_units]

    sm = difflib.SequenceMatcher(None, norm_old, norm_new, autojunk=False)
    unchanged = 0
    changes: list[ParaChange] = []
    pending_removed: list[int] = []  # old indices, for similarity re-pairing

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            unchanged += j2 - j1
        elif tag == "replace":
            # Pair positionally; leftovers become add / remove.
            old_idx = list(range(i1, i2))
            new_idx = list(range(j1, j2))
            for k in range(max(len(old_idx), len(new_idx))):
                oi = old_idx[k] if k < len(old_idx) else None
                nj = new_idx[k] if k < len(new_idx) else None
                if oi is not None and nj is not None:
                    changes.append(
                        ParaChange("modified", old_units[oi], new_units[nj])
                    )
                elif nj is not None:
                    changes.append(ParaChange("added", None, new_units[nj]))
                else:
                    pending_removed.append(oi)
        elif tag == "insert":
            for nj in range(j1, j2):
                changes.append(ParaChange("added", None, new_units[nj]))
        elif tag == "delete":
            for oi in range(i1, i2):
                pending_removed.append(oi)

    if mode == "similarity" and pending_removed:
        # Try to re-pair removed-old against added-new by similarity so a
        # reworded+moved paragraph reads as one "modified" delta instead of
        # an orphan add + orphan remove. Display only — never drops content.
        added_changes = [c for c in changes if c.kind == "added"]
        matcher = difflib.SequenceMatcher(autojunk=False)
        still_removed: list[int] = []
        for oi in pending_removed:
            matcher.set_seq2(norm_old[oi])
            best, best_r = None, threshold
            for c in added_changes:
                matcher.set_seq1(normalize_text(c.new_text or ""))
                r = matcher.ratio()
                if r >= best_r:
                    best, best_r = c, r
            if best is not None:
                best.kind = "modified"
                best.old_text = old_units[oi]
                added_changes.remove(best)
            else:
                still_removed.append(oi)
        pending_removed = still_removed

    for oi in pending_removed:
        changes.append(ParaChange("removed", old_units[oi], None))

    return PrediffResult(total_new=len(new_units), unchanged=unchanged, changes=changes)


# --------------------------------------------------------------------------
# Clause filter (decompose-side call reduction)
# --------------------------------------------------------------------------


def filter_unchanged_clauses(
    clauses: list,
    comparison_text: str | None,
) -> tuple[list, int]:
    """Drop clauses byte-identical (normalized) to a prior-document paragraph.

    This is the decompose-side win: the four-lens panel costs ~4 LLM calls
    per clause, so skipping a clause that did not change between versions
    saves 4 calls. **Exact-match only** — a clause that changed any number,
    date or word survives, because its normalized text no longer matches.

    Returns ``(kept_clauses, dropped_count)``. With no comparison text, or
    when disabled, returns the clauses untouched.
    """
    if not clauses or not (comparison_text and comparison_text.strip()):
        return clauses, 0

    prior = {normalize_text(p) for p in split_paragraphs(comparison_text)}
    if not prior:
        return clauses, 0

    kept = []
    dropped = 0
    for c in clauses:
        txt = getattr(c, "new_text", None) or ""
        norm = normalize_text(txt)
        # Only drop a clause whose ENTIRE normalized text is present verbatim
        # in the prior document — a true no-op re-statement.
        if norm and norm in prior:
            dropped += 1
            continue
        kept.append(c)
    return kept, dropped
