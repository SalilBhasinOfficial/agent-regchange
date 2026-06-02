"""Pub/Sub pull subscriber that bridges discovery → chain service.

This module is the **bridge** between the standalone discovery Cloud
Run service and the chain service. It is **NOT** imported by the
discovery service itself (which only publishes) — it lives in the
chain service's process and gets wired into ``app/fast_api_app.py``
by Track B of D5. Track A (this brief) writes the function but does
not wire it.

D5 behaviour: logging-only
--------------------------
For the D5 MVP the subscriber simply parses each message, opens a fresh
``pipeline_run_id`` via :func:`app.observability.run_log.begin_pipeline_run`,
and logs receipt. It does NOT yet trigger
:func:`app.ingest.pipeline.ingest_two_pdfs` — fetching a PDF from the
RBI URL is a D6 polish item (URL → PDF fetcher) gated on time. The
``pipeline_run_id`` is still emitted so the inbox UI (Track B) can
display it next to the discovered-item row.

TODO (D6+): wire the live chain trigger here once the PDF fetcher
lands. Update ``discovered_items.pipeline_run_id`` + ``status='processing'``
inside the message handler, kick off the chain in a thread, then
``status='done'`` (or ``'error'`` with the message in ``error``).

Ack policy
----------
We use the standard streaming-pull callback contract: call
``message.ack()`` after successful processing (logging the receipt is
"success" for D5), and ``message.nack()`` on parse failures. Pub/Sub's
default ack deadline (10s) is plenty for this logging-only path; once
the chain trigger lands we'll bump it via
``SubscriberClient.modify_ack_deadline``.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

LOGGER = logging.getLogger(__name__)

ENV_PROJECT = "GOOGLE_CLOUD_PROJECT"
ENV_SUBSCRIPTION = "CURATOR_DISCOVERY_SUBSCRIPTION"

DEFAULT_PROJECT = "curator-research"
DEFAULT_SUBSCRIPTION = "curator-chain-pull"


def _subscription_path(project: str, subscription: str) -> str:
    return f"projects/{project}/subscriptions/{subscription}"


def _handle_message(message: Any) -> None:
    """Per-message callback — D5 MVP is logging-only.

    Parses the JSON body, opens a pipeline_run_id, logs the receipt,
    and acks. Any parse failure naks so Pub/Sub re-delivers (or
    eventually dead-letters per topic config).
    """
    # Imported lazily so this module stays importable without
    # google.cloud.spanner in test environments.
    from app.observability.run_log import begin_pipeline_run

    try:
        raw = message.data.decode("utf-8")
        body = json.loads(raw)
    except Exception as e:  # noqa: BLE001 — best-effort
        LOGGER.warning("Subscriber: failed to parse message (%s); naking", e)
        try:
            message.nack()
        except Exception:  # noqa: BLE001
            pass
        return

    pipeline_run_id = begin_pipeline_run()
    LOGGER.info(
        "Subscriber: received item_hash=%s source=%s url=%s pipeline_run_id=%s",
        body.get("item_hash"),
        body.get("source"),
        body.get("url"),
        pipeline_run_id,
    )
    # TODO(D6): fetch PDF from body["url"] and invoke
    # app.ingest.pipeline.ingest_two_pdfs(...). For D5 we only log +
    # ack; the inbox UI surfaces the receipt via Spanner.

    try:
        message.ack()
    except Exception as e:  # noqa: BLE001
        LOGGER.warning("Subscriber: ack failed (%s)", e)


def subscribe(timeout_seconds: int | None = None) -> None:
    """Block on the configured Pub/Sub pull subscription.

    Args:
      timeout_seconds: optional cap so test harnesses can run the
        subscriber for a bounded duration. ``None`` means block
        indefinitely (the Cloud Run sidecar's lifetime).
    """
    try:
        from google.cloud import pubsub_v1  # type: ignore[import-not-found]
    except Exception as e:  # noqa: BLE001
        LOGGER.warning("Subscriber: pubsub_v1 import failed (%s)", e)
        return

    project = os.environ.get(ENV_PROJECT, DEFAULT_PROJECT)
    subscription = os.environ.get(ENV_SUBSCRIPTION, DEFAULT_SUBSCRIPTION)
    path = _subscription_path(project, subscription)

    subscriber = pubsub_v1.SubscriberClient()
    streaming_pull_future = subscriber.subscribe(path, callback=_handle_message)
    LOGGER.info("Subscriber: listening on %s", path)

    try:
        # ``result(timeout)`` blocks until the future completes or
        # raises; KeyboardInterrupt + cancel() is the standard
        # shutdown path for streaming pull.
        streaming_pull_future.result(timeout=timeout_seconds)
    except TimeoutError:
        LOGGER.info("Subscriber: timeout reached; shutting down cleanly")
    except KeyboardInterrupt:
        LOGGER.info("Subscriber: interrupted; shutting down cleanly")
    except Exception as e:  # noqa: BLE001
        LOGGER.warning("Subscriber: streaming pull failed (%s)", e)
    finally:
        try:
            streaming_pull_future.cancel()
            streaming_pull_future.result(timeout=10)
        except Exception:  # noqa: BLE001
            pass
        try:
            subscriber.close()
        except Exception:  # noqa: BLE001
            pass


__all__ = ["subscribe"]
