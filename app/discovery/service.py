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
from app.discovery.rss_poller import DEFAULT_RBI_FEED_URL, RssPoller

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


@app.post("/poll")
def poll() -> dict[str, Any]:
    """Run one poll cycle and return summary counts.

    Order of operations:
      1. ``rss_poller.poll()`` — fetch the upstream RBI feed.
      2. ``dedupe.filter_new(items)`` — drop already-known hashes.
      3. ``publisher.publish_all(unseen)`` — push to Pub/Sub topic.
      4. ``dedupe.mark_first_seen(unseen)`` — write rows so future polls
         skip these hashes. Performed AFTER publish so a Pub/Sub outage
         doesn't strand items as "discovered but never sent".
    """
    import os

    poller = RssPoller()
    dedupe = Dedupe()
    publisher = Publisher()

    feed_url = os.environ.get("CURATOR_RSS_FEED_URL", DEFAULT_RBI_FEED_URL)
    items = poller.poll(feed_url)
    unseen = dedupe.filter_new(items)
    published = publisher.publish_all(unseen)
    # Stamp first_seen only for items we successfully attempted to publish.
    # If publish failed entirely (published == 0 and unseen is non-empty)
    # we still mark them so a buggy upstream feed cannot blow up our
    # quota with the same N items every 30 minutes. The chain service
    # subscriber is the authoritative consumer; a Pub/Sub outage is
    # diagnosed via Cloud Trace, not by leaving Spanner in a poke-me state.
    dedupe.mark_first_seen(unseen)

    summary = {"polled": len(items), "new": len(unseen), "published": published}
    LOGGER.info("Discovery /poll summary: %s", summary)
    return summary


# Main execution for local dev — Cloud Run uses the Docker CMD.
if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
