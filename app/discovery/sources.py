"""Multi-regulator source registry for the Discovery service.

Curator is plug-and-play across jurisdictions: drop in a new entry in
:data:`BUILTIN_SOURCES` (or override at deploy time via
``CURATOR_RSS_FEEDS``) and the Discovery service polls it on every
Cloud Scheduler tick. No code change required to add a new regulator
feed.

Configuration
-------------
At runtime the active list is resolved from, in priority order:

1. ``CURATOR_RSS_FEEDS`` env var — comma-separated, two accepted forms:

   * ``"rbi,sebi,irdai"`` — built-in source ids.
   * ``"my_reg=https://example.gov/feed.xml,sebi"`` — mix of inline
     ``id=url`` definitions and built-in ids.

2. ``CURATOR_RSS_FEED_URL`` env var (legacy) — single-feed
   backward-compatibility for the original Stage-2 deploy. Maps to a
   single source named ``custom_rss``.

3. The default: every entry in :data:`BUILTIN_SOURCES` that has
   ``default_enabled=True``. Today that's just SEBI (RBI's RSS endpoint
   returns broken HTML and IRDAI does not publish an RSS feed — both
   documented in the entries themselves).

The Discovery service iterates these in :func:`app.discovery.service.poll`
and tags each :class:`~app.discovery.rss_poller.DiscoveredItem` with its
originating ``source`` id, which is what the Inbox UI displays.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegulatorSource:
    """One configured regulator feed.

    Attributes:
      id: short stable identifier (used in ``agent_runs`` rows, Pub/Sub
        message bodies, Inbox table). Lowercase, no spaces.
      display_name: human-readable name for the UI / Devpost copy.
      jurisdiction: 2- or 3-letter region code (``IN``, ``EU``, ``US``).
      feed_url: HTTPS URL of the RSS feed.
      kind: ``"rss"`` today; reserved for ``"atom"`` / ``"html"`` later.
      default_enabled: whether the source ships ON in the default
        ``CURATOR_RSS_FEEDS`` unset case.
      notes: short engineering notes (broken endpoints, planned
        upgrades). Shown in startup logs.
    """

    id: str
    display_name: str
    jurisdiction: str
    feed_url: str
    kind: str = "rss"
    default_enabled: bool = True
    notes: str = ""


# ---------------------------------------------------------------------------
# Built-in registry
# ---------------------------------------------------------------------------
# Add new regulators here. Anything in this dict is selectable via
# ``CURATOR_RSS_FEEDS=...``; entries with ``default_enabled=True`` are
# polled out of the box.

BUILTIN_SOURCES: dict[str, RegulatorSource] = {
    "sebi": RegulatorSource(
        id="sebi",
        display_name="Securities & Exchange Board of India (SEBI)",
        jurisdiction="IN",
        feed_url="https://www.sebi.gov.in/sebirss.xml",
        default_enabled=True,
        notes="Verified 2026-06-02: returns ~30 entries of valid RSS.",
    ),
    "rbi": RegulatorSource(
        id="rbi",
        display_name="Reserve Bank of India (RBI)",
        jurisdiction="IN",
        # Endpoint kept for transparency; today it returns an ASP.NET
        # error page rather than RSS. Operators who need RBI can override
        # the URL once the official feed is back.
        feed_url="https://www.rbi.org.in/Scripts/RssNotification.aspx",
        default_enabled=False,
        notes=(
            "Endpoint returns ASP.NET error HTML at present. Default OFF. "
            "Phase-5 plan is to BeautifulSoup-parse the notifications HTML."
        ),
    ),
    "irdai": RegulatorSource(
        id="irdai",
        display_name="Insurance Regulatory and Development Authority of India (IRDAI)",
        jurisdiction="IN",
        # IRDAI does not publish an RSS feed; we wire the website URL so
        # the row is visible. Override the feed_url to a self-hosted
        # mirror or a third-party aggregator to enable real polling.
        feed_url="https://irdai.gov.in/rss",
        default_enabled=False,
        notes=(
            "IRDAI does not publish a public RSS feed. Default OFF; "
            "operators can point at an aggregator or a self-hosted mirror."
        ),
    ),
    "eu_eba": RegulatorSource(
        id="eu_eba",
        display_name="European Banking Authority (EBA)",
        jurisdiction="EU",
        feed_url="https://www.eba.europa.eu/rss.xml",
        default_enabled=False,
        notes="Demonstrates cross-jurisdiction plug-and-play. Enable via CURATOR_RSS_FEEDS=eu_eba.",
    ),
    "us_sec": RegulatorSource(
        id="us_sec",
        display_name="U.S. Securities and Exchange Commission (SEC)",
        jurisdiction="US",
        feed_url="https://www.sec.gov/news/pressreleases.rss",
        default_enabled=False,
        notes="Demonstrates US-jurisdiction plug-and-play.",
    ),
}


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _parse_feeds_env(raw: str) -> list[RegulatorSource]:
    """Parse ``CURATOR_RSS_FEEDS`` — comma-separated source-ids or id=url pairs."""
    out: list[RegulatorSource] = []
    for token in [t.strip() for t in raw.split(",") if t.strip()]:
        if "=" in token:
            sid, url = token.split("=", 1)
            sid = sid.strip().lower()
            url = url.strip()
            if not sid or not url:
                LOGGER.warning("CURATOR_RSS_FEEDS: skipping malformed entry %r", token)
                continue
            out.append(
                RegulatorSource(
                    id=sid,
                    display_name=sid.upper(),
                    jurisdiction="?",
                    feed_url=url,
                    notes="Inline definition via CURATOR_RSS_FEEDS.",
                )
            )
        else:
            sid = token.lower()
            src = BUILTIN_SOURCES.get(sid)
            if src is None:
                LOGGER.warning("CURATOR_RSS_FEEDS: unknown source id %r (skipping)", sid)
                continue
            out.append(src)
    return out


def active_sources() -> list[RegulatorSource]:
    """Resolve the active set of regulator sources for this process.

    Falls through env-var precedence — see module docstring. Always
    returns at least one entry (SEBI as fallback) so the Discovery
    service never silently no-ops.
    """
    feeds_env = os.environ.get("CURATOR_RSS_FEEDS", "").strip()
    if feeds_env:
        parsed = _parse_feeds_env(feeds_env)
        if parsed:
            return parsed
        LOGGER.warning("CURATOR_RSS_FEEDS set but no valid entries; falling back.")

    legacy = os.environ.get("CURATOR_RSS_FEED_URL", "").strip()
    if legacy:
        return [
            RegulatorSource(
                id="custom_rss",
                display_name="Custom RSS feed",
                jurisdiction="?",
                feed_url=legacy,
                notes="From legacy CURATOR_RSS_FEED_URL env var.",
            )
        ]

    defaults = [s for s in BUILTIN_SOURCES.values() if s.default_enabled]
    if not defaults:
        # Belt-and-braces: always return at least SEBI so the service
        # has something to poll even if the registry is misconfigured.
        return [BUILTIN_SOURCES["sebi"]]
    return defaults


__all__ = [
    "BUILTIN_SOURCES",
    "RegulatorSource",
    "active_sources",
]
