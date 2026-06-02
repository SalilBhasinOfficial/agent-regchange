"""Spanner-backed dedupe layer for the discovery service.

For each poll cycle the service hands us a list of ``DiscoveredItem``
records from the RSS feed; we ask Spanner which hashes it already knows
about, return only the unseen ones to the caller (so they can be
published to Pub/Sub), and then write a ``status='new'`` row for each
freshly-published item so a follow-up poll skips them.

Best-effort policy
------------------
If Spanner is unreachable we log and return ALL incoming items rather
than aborting. Rationale: a duplicate downstream chain trigger is
recoverable (the chain idempotently re-uses the same pipeline_run_id
linkage); a silent discovery outage is not. The choice is documented
explicitly so future maintainers don't tighten this to fail-closed.

Connection
----------
Same env-var contract as :mod:`app.observability.run_log`:
``GOOGLE_CLOUD_PROJECT`` (default ``curator-research``),
``SPANNER_INSTANCE`` (default ``curator-graph``),
``SPANNER_DATABASE`` (default ``curator``). Client is constructed
lazily on the first call so module import has zero GCP cost.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.discovery.rss_poller import DiscoveredItem

LOGGER = logging.getLogger(__name__)

ENV_PROJECT = "GOOGLE_CLOUD_PROJECT"
ENV_INSTANCE = "SPANNER_INSTANCE"
ENV_DATABASE = "SPANNER_DATABASE"

DEFAULT_PROJECT = "curator-research"
DEFAULT_INSTANCE = "curator-graph"
DEFAULT_DATABASE = "curator"


class Dedupe:
    """Spanner-backed first-seen filter.

    The class accepts an injected ``database`` (mainly for tests). When
    not provided, it lazily constructs a Spanner ``Database`` handle on
    the first method call using the env-var contract above.
    """

    def __init__(self, database: Any | None = None) -> None:
        self._database = database
        self._init_failed = False

    # ------------------------------------------------------------------
    # Lazy client (mirrors app.observability.run_log:127-130)
    # ------------------------------------------------------------------
    def _ensure_database(self) -> Any | None:
        if self._database is not None:
            return self._database
        if self._init_failed:
            return None
        try:
            from google.cloud import spanner  # type: ignore[import-not-found]

            project = os.environ.get(ENV_PROJECT, DEFAULT_PROJECT)
            instance_id = os.environ.get(ENV_INSTANCE, DEFAULT_INSTANCE)
            database_id = os.environ.get(ENV_DATABASE, DEFAULT_DATABASE)
            client = spanner.Client(project=project)
            instance = client.instance(instance_id)
            self._database = instance.database(database_id)
            return self._database
        except Exception as e:  # noqa: BLE001 — best-effort
            LOGGER.warning("Dedupe Spanner client init failed: %s", e)
            self._init_failed = True
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def filter_new(self, items: list[DiscoveredItem]) -> list[DiscoveredItem]:
        """Return the subset of ``items`` whose ``item_hash`` is unknown to Spanner.

        On Spanner unavailability returns ``items`` unchanged (best-effort
        — see module docstring).
        """
        if not items:
            return []

        database = self._ensure_database()
        if database is None:
            LOGGER.warning(
                "Dedupe: Spanner unavailable; returning all %d items unfiltered",
                len(items),
            )
            return list(items)

        hashes = [it.item_hash for it in items]
        known: set[str] = set()
        try:
            with database.snapshot() as snapshot:
                results = snapshot.execute_sql(
                    "SELECT item_hash FROM discovered_items "
                    "WHERE item_hash IN UNNEST(@hashes)",
                    params={"hashes": hashes},
                    param_types=_string_array_param_types("hashes"),
                )
                for row in results:
                    known.add(row[0])
        except Exception as e:  # noqa: BLE001 — best-effort
            LOGGER.warning(
                "Dedupe: Spanner query failed (%s); returning all %d items",
                e,
                len(items),
            )
            return list(items)

        unseen = [it for it in items if it.item_hash not in known]
        LOGGER.info(
            "Dedupe: %d incoming, %d already-seen, %d new",
            len(items),
            len(items) - len(unseen),
            len(unseen),
        )
        return unseen

    def mark_first_seen(self, items: list[DiscoveredItem]) -> None:
        """Insert a ``discovered_items`` row per new item with ``status='new'``.

        Uses ``PENDING_COMMIT_TIMESTAMP`` for ``first_seen`` so Spanner
        stamps the row at commit time. Failures are logged, not raised.
        """
        if not items:
            return

        database = self._ensure_database()
        if database is None:
            LOGGER.warning(
                "Dedupe: Spanner unavailable; skipping mark_first_seen for %d items",
                len(items),
            )
            return

        try:
            from google.cloud import spanner  # type: ignore[import-not-found]

            def _txn(transaction) -> None:
                transaction.insert(
                    table="discovered_items",
                    columns=(
                        "item_hash",
                        "source",
                        "url",
                        "title",
                        "published_at",
                        "first_seen",
                        "status",
                    ),
                    values=[
                        (
                            it.item_hash,
                            it.source,
                            it.url,
                            it.title,
                            None,  # published_at: keep nullable; ISO string would need a TIMESTAMP cast
                            spanner.COMMIT_TIMESTAMP,
                            "new",
                        )
                        for it in items
                    ],
                )

            database.run_in_transaction(_txn)
            LOGGER.info("Dedupe: marked %d items as first-seen", len(items))
        except Exception as e:  # noqa: BLE001 — best-effort
            LOGGER.warning("Dedupe: mark_first_seen failed (%s)", e)


def _string_array_param_types(name: str) -> dict[str, Any]:
    """Lazy import of Spanner param_types to keep import-time GCP-free."""
    from google.cloud import spanner  # type: ignore[import-not-found]

    return {name: spanner.param_types.Array(spanner.param_types.STRING)}


__all__ = ["Dedupe"]
