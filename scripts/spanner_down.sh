#!/usr/bin/env bash
# scripts/spanner_down.sh — tear down the dev Spanner instance.
# Idempotent: succeeds even if the instance doesn't exist.

set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-curator-research}"
INSTANCE="curator-graph"

if gcloud spanner instances describe "${INSTANCE}" --project="${PROJECT}" >/dev/null 2>&1; then
  echo "Deleting Spanner instance ${INSTANCE} on ${PROJECT}..."
  gcloud spanner instances delete "${INSTANCE}" --project="${PROJECT}" --quiet
  echo "  done"
else
  echo "Spanner instance ${INSTANCE} not present on ${PROJECT} — nothing to delete"
fi
