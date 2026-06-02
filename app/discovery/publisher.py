"""Pub/Sub publisher that fans newly-discovered items out to the chain service.

The discovery service publishes one message per ``DiscoveredItem`` to a
Pub/Sub topic (default ``curator-discoveries``). The chain service runs
:func:`app.discovery.subscriber.subscribe` against a corresponding pull
subscription (default ``curator-chain-pull``) — that boundary keeps the
two services decoupled at runtime.

Topic / project resolution
--------------------------
Project: ``GOOGLE_CLOUD_PROJECT`` (default ``curator-research``).
Topic name: ``CURATOR_DISCOVERY_TOPIC`` (default ``curator-discoveries``).
The full path ``projects/{project}/topics/{topic}`` is built lazily so
import time stays GCP-free.

Best-effort policy
------------------
Errors on individual ``publish`` futures are caught and logged; the
batch carries on. Publisher client construction failure aborts the
batch with an empty success count (still logged, never raised).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from app.discovery.rss_poller import DiscoveredItem

LOGGER = logging.getLogger(__name__)

ENV_PROJECT = "GOOGLE_CLOUD_PROJECT"
ENV_TOPIC = "CURATOR_DISCOVERY_TOPIC"

DEFAULT_PROJECT = "curator-research"
DEFAULT_TOPIC = "curator-discoveries"


def _now_utc_iso() -> str:
    """Discovered-at timestamp stamped at publish time."""
    return datetime.now(tz=timezone.utc).isoformat()


def _item_to_message(item: DiscoveredItem) -> bytes:
    """Serialize a DiscoveredItem to the wire format the subscriber expects.

    Keep this in lock-step with :func:`app.discovery.subscriber.subscribe`.
    """
    body = {
        "item_hash": item.item_hash,
        "source": item.source,
        "url": item.url,
        "title": item.title,
        "published_at": item.published_at,
        "discovered_at": _now_utc_iso(),
    }
    return json.dumps(body).encode("utf-8")


class Publisher:
    """Thin wrapper around :class:`google.cloud.pubsub_v1.PublisherClient`.

    The class accepts an injected ``client`` (for tests). When not
    provided the client is built lazily on the first ``publish_all``
    call, again preserving import-time GCP independence.
    """

    def __init__(
        self,
        *,
        project: str | None = None,
        topic: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._project = project or os.environ.get(ENV_PROJECT, DEFAULT_PROJECT)
        self._topic = topic or os.environ.get(ENV_TOPIC, DEFAULT_TOPIC)
        self._client = client
        self._init_failed = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def topic_path(self) -> str:
        return f"projects/{self._project}/topics/{self._topic}"

    def _ensure_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        if self._init_failed:
            return None
        try:
            from google.cloud import pubsub_v1  # type: ignore[import-not-found]

            self._client = pubsub_v1.PublisherClient()
            return self._client
        except Exception as e:  # noqa: BLE001 — best-effort
            LOGGER.warning("Publisher client init failed: %s", e)
            self._init_failed = True
            return None

    def publish_all(self, items: list[DiscoveredItem]) -> int:
        """Publish each item; return the count of successful publishes.

        Errors on individual futures are caught and logged but do NOT
        abort the batch.
        """
        if not items:
            return 0

        client = self._ensure_client()
        if client is None:
            LOGGER.warning(
                "Publisher: Pub/Sub unavailable; skipping %d items", len(items)
            )
            return 0

        topic_path = self.topic_path
        successes = 0
        for item in items:
            try:
                payload = _item_to_message(item)
                future = client.publish(topic_path, payload)
                # .result() blocks until ack-from-server; cheap (~10ms typical).
                future.result(timeout=30)
                successes += 1
            except Exception as e:  # noqa: BLE001 — best-effort per item
                LOGGER.warning(
                    "Publisher: publish failed for item_hash=%s (%s)",
                    getattr(item, "item_hash", "?"),
                    e,
                )
                continue
        LOGGER.info(
            "Publisher: %d / %d items published to %s",
            successes,
            len(items),
            topic_path,
        )
        return successes


__all__ = ["Publisher", "DEFAULT_TOPIC"]
