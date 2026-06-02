"""RSS poller for the RBI notification feed (and similar regulator feeds).

Thin wrapper around :mod:`feedparser`. The public surface is a single
class, :class:`RssPoller`, with one method, :meth:`RssPoller.poll`, that
returns a list of :class:`DiscoveredItem` pydantic records.

Design rules
------------
1.  **Never raise on transient feed errors.** Discovery is best-effort:
    a malformed feed, a network blip, or a missing field MUST return an
    empty (or partial) list rather than propagate. Discovery service
    callers (``/poll`` endpoint, Cloud Scheduler) treat raises as
    outages; the airlock is therefore inside this module.
2.  **Deterministic hash.** ``item_hash = sha256(url + title)[:64]`` so
    two pollers running concurrently arrive at the same key for the same
    item. The Spanner dedup join compares on this hash exactly.
3.  **No GCP imports.** Polling has no Spanner / Pub/Sub coupling — that
    lives in :mod:`app.discovery.dedupe` and :mod:`app.discovery.publisher`.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import feedparser
from pydantic import BaseModel, Field

LOGGER = logging.getLogger(__name__)

# Default feed: SEBI's official RSS (validated 2026-06-02 — 30 entries,
# valid RSS XML). RBI's older ``/Scripts/RssNotification.aspx`` endpoint
# now returns an ASP.NET error HTML page, not RSS — we swapped to SEBI
# because (a) it's in the same BFSI vertical, (b) RBI's portal has no
# usable RSS today (parsing the notifications HTML page is a future
# enhancement). The poller accepts any feed URL — judges or operators
# can point it at a different regulator by setting ``CURATOR_RSS_FEED_URL``.
DEFAULT_RBI_FEED_URL = "https://www.sebi.gov.in/sebirss.xml"
DEFAULT_SOURCE = "sebi_rss"


class DiscoveredItem(BaseModel):
    """One regulatory notification surfaced from a regulator RSS feed.

    The pydantic model intentionally lives next to the poller (instead of
    being added to the frozen ``app/models.py``) — the discovery service is
    a standalone process and its message shape should not bleed into the
    chain service's domain models.
    """

    item_hash: str = Field(
        ..., description="sha256(url + title)[:64], the dedup primary key."
    )
    source: str = Field(default=DEFAULT_SOURCE, description="Origin feed identifier.")
    url: str = Field(..., description="Canonical URL of the regulator notification.")
    title: str = Field(..., description="Headline as published in the feed.")
    published_at: str | None = Field(
        default=None,
        description="ISO-8601 UTC string parsed from ``entry.published``; None if missing.",
    )
    raw_summary: str = Field(
        default="", description="Short summary as published in the feed (may be empty)."
    )


def _compute_item_hash(url: str, title: str) -> str:
    """Stable per-item key. Two callers produce the same hash for the same item."""
    payload = (url or "") + "|" + (title or "")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:64]


def _entry_published_iso(entry: Any) -> str | None:
    """Best-effort ``published_at`` extraction.

    ``feedparser`` exposes ``published_parsed`` as a ``time.struct_time``
    when it can parse the date; we convert to ISO-8601 UTC. When the
    field is missing or malformed we return ``None`` — the column is
    nullable in the Spanner schema.
    """
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


class RssPoller:
    """Wrapper around :func:`feedparser.parse` that returns DiscoveredItems.

    The class is intentionally near-stateless: it exists so test code can
    monkey-patch ``self._parse`` to feed in synthetic XML strings without
    having to monkey-patch a module-level function.
    """

    def __init__(self, *, source: str = DEFAULT_SOURCE) -> None:
        self.source = source

    def _parse(self, feed_url_or_text: str) -> Any:
        """Indirection seam so tests can supply embedded XML strings.

        ``feedparser.parse`` accepts both a URL and a raw XML string,
        so this is just a hook for substitution.
        """
        return feedparser.parse(feed_url_or_text)

    def poll(
        self, feed_url: str = DEFAULT_RBI_FEED_URL
    ) -> list[DiscoveredItem]:
        """Fetch the feed and return any items it contained.

        Never raises. Errors degrade to an empty list (or a partial list
        if individual entries are malformed but others parse cleanly).
        """
        try:
            parsed = self._parse(feed_url)
        except Exception as e:  # noqa: BLE001 — best-effort
            LOGGER.warning("RSS feed fetch failed (%s): %s", feed_url, e)
            return []

        # ``feedparser`` swallows malformed XML and sets ``bozo=1`` plus
        # a ``bozo_exception``. We log loudly but still walk through any
        # entries it managed to extract — feedparser is famously
        # forgiving and often surfaces useful items even from broken
        # feeds.
        if getattr(parsed, "bozo", 0):
            exc = getattr(parsed, "bozo_exception", None)
            LOGGER.warning("RSS feed marked bozo (%s): %s", feed_url, exc)

        entries = getattr(parsed, "entries", None) or []
        items: list[DiscoveredItem] = []
        for entry in entries:
            try:
                url = (entry.get("link") or "").strip()
                title = (entry.get("title") or "").strip()
                if not url and not title:
                    # Nothing identifying — drop it; no stable hash possible.
                    continue
                summary = (
                    entry.get("summary")
                    or entry.get("description")
                    or ""
                ).strip()
                item = DiscoveredItem(
                    item_hash=_compute_item_hash(url, title),
                    source=self.source,
                    url=url,
                    title=title,
                    published_at=_entry_published_iso(entry),
                    raw_summary=summary,
                )
                items.append(item)
            except Exception as e:  # noqa: BLE001 — best-effort per entry
                LOGGER.warning("RSS entry parse failed (skipping): %s", e)
                continue

        if not items:
            LOGGER.info("RSS feed produced 0 items (%s)", feed_url)
        return items


__all__ = [
    "DEFAULT_RBI_FEED_URL",
    "DEFAULT_SOURCE",
    "DiscoveredItem",
    "RssPoller",
]
