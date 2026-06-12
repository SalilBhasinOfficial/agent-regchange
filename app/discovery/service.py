"""FastAPI app for the standalone Curator Discovery Cloud Run service.

Two routes:
  * ``GET /health`` — liveness probe.
  * ``POST /poll`` — one poll cycle: fetch the RBI feed, dedupe against
    Spanner, publish new items to Pub/Sub, then stamp ``first_seen``.

The service is intentionally separate from the chain service: it never
imports any sub-agent code, has its own Cloud Run resource profile, and
keeps polling even when the chain service is degraded. Resilience > DRY.

Auth model
----------
In production Cloud Run rejects unauthenticated traffic and Cloud
Scheduler attaches an OIDC token signed by the Curator service account;
the service itself therefore does not need application-layer auth
checks. For local development the endpoint is unauthenticated.

Lazy GCP clients
----------------
``RssPoller``, ``Dedupe``, and ``Publisher`` are constructed inside the
``/poll`` handler so importing this module does not require Spanner or
Pub/Sub credentials. The FastAPI app object itself is import-time
safe — ``adk deploy cloud_run`` introspects it without contacting GCP.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from app.discovery.dedupe import Dedupe
from app.discovery.publisher import Publisher
from app.discovery.rss_poller import RssPoller
from app.discovery.sources import active_sources

LOGGER = logging.getLogger(__name__)

app: FastAPI = FastAPI(
    title="curator-discovery",
    description=(
        "Polls RBI RSS notifications, dedupes against Spanner, publishes "
        "new items to Pub/Sub for the Curator chain service."
    ),
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe — never touches Spanner / Pub/Sub."""
    return {"status": "ok", "service": "curator-discovery"}


@app.get("/sources")
def sources() -> dict[str, Any]:
    """Enumerate the regulator sources this process will poll.

    Useful for debugging plug-and-play configuration: hit the deployed
    URL with ``curl /sources`` to confirm a newly added entry was
    picked up.
    """
    return {
        "sources": [
            {
                "id": s.id,
                "display_name": s.display_name,
                "jurisdiction": s.jurisdiction,
                "feed_url": s.feed_url,
                "kind": s.kind,
                "notes": s.notes,
            }
            for s in active_sources()
        ]
    }


@app.post("/poll")
def poll() -> dict[str, Any]:
    """Run one poll cycle across every active regulator source.

    Per-source loop:
      1. ``rss_poller.poll(feed_url)`` — fetch the upstream feed.
      2. ``dedupe.filter_new(items)`` — drop already-known hashes.
      3. ``publisher.publish_all(unseen)`` — push to Pub/Sub topic.
      4. ``dedupe.mark_first_seen(unseen)`` — write rows so future polls
         skip these hashes. Performed AFTER publish so a Pub/Sub outage
         doesn't strand items as "discovered but never sent".

    Per-source failure is isolated — a broken feed doesn't stop the
    others from being polled (audit U4/plug-and-play, 2026-06-05).
    """
    dedupe = Dedupe()
    publisher = Publisher()

    per_source_summaries: list[dict[str, Any]] = []
    total_polled = total_new = total_published = 0

    for src in active_sources():
        poller = RssPoller(source=src.id)
        try:
            items = poller.poll(src.feed_url)
            unseen = dedupe.filter_new(items)
            published = publisher.publish_all(unseen)
            dedupe.mark_first_seen(unseen)
        except Exception as e:  # noqa: BLE001 — per-source airlock
            LOGGER.warning("Discovery source %s failed: %s", src.id, e)
            per_source_summaries.append({"source": src.id, "error": str(e)[:200]})
            continue

        per_source_summaries.append(
            {
                "source": src.id,
                "polled": len(items),
                "new": len(unseen),
                "published": published,
            }
        )
        total_polled += len(items)
        total_new += len(unseen)
        total_published += published

    summary = {
        "polled": total_polled,
        "new": total_new,
        "published": total_published,
        "per_source": per_source_summaries,
    }
    LOGGER.info("Discovery /poll summary: %s", summary)
    return summary


# Main execution for local dev — Cloud Run uses the Docker CMD.
if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
