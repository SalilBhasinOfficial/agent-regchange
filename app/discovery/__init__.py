"""Curator D5 — Discovery service package.

Standalone Cloud Run service that polls the RBI RSS feed, dedupes
against the Spanner ``discovered_items`` table, and publishes new
items to Pub/Sub for the chain service to consume.

This package does NOT import from the chain service: discovery must
keep running even if the chain is wedged. Resilience > DRY.

Modules:
  * :mod:`app.discovery.rss_poller` — feedparser-backed RSS fetcher.
  * :mod:`app.discovery.dedupe` — Spanner-backed first-seen filter.
  * :mod:`app.discovery.publisher` — Pub/Sub fan-out to chain service.
  * :mod:`app.discovery.service` — FastAPI app exposing ``/health`` + ``/poll``.
  * :mod:`app.discovery.subscriber` — Pub/Sub pull subscriber that lives
    inside the chain service (logging-only for D5; D6 wires the chain
    trigger).
"""
