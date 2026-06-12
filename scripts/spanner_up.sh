#!/usr/bin/env bash
# scripts/spanner_up.sh — provision a fresh Spanner Graph dev instance in asia-south1.
#
# Idempotent: skips create steps that already exist. Schema bootstrap waits
# for Phase 2 (when app/ingest/spanner_schema.sql lands). Until then, this
# just provisions the instance + empty database.
#
# Run cost: instance creation ~30s; schema apply ~10s (Phase 2). Total ~1 min cold.

set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-curator-research}"
INSTANCE="curator-graph"
DATABASE="curator"
CONFIG="regional-asia-south1"
PROCESSING_UNITS="${SPANNER_PROCESSING_UNITS:-100}"

echo "Provisioning Spanner instance ${INSTANCE} in ${CONFIG} on ${PROJECT}..."

if gcloud spanner instances describe "${INSTANCE}" --project="${PROJECT}" >/dev/null 2>&1; then
  echo "  instance ${INSTANCE}: already exists, skipping create"
else
  gcloud spanner instances create "${INSTANCE}" \
    --project="${PROJECT}" \
    --config="${CONFIG}" \
    --description="Curator runtime GraphRAG (dev)" \
    --processing-units="${PROCESSING_UNITS}"
  echo "  instance ${INSTANCE}: created"
fi

if gcloud spanner databases describe "${DATABASE}" --instance="${INSTANCE}" --project="${PROJECT}" >/dev/null 2>&1; then
  echo "  database ${DATABASE}: already exists, skipping create"
else
  gcloud spanner databases create "${DATABASE}" \
    --instance="${INSTANCE}" \
    --project="${PROJECT}"
  echo "  database ${DATABASE}: created"
fi

SCHEMA_PATH="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")/.." && pwd)/app/ingest/spanner_schema.sql"
if [[ -f "${SCHEMA_PATH}" ]]; then
  echo "  applying schema from ${SCHEMA_PATH}..."
  gcloud spanner databases ddl update "${DATABASE}" \
    --instance="${INSTANCE}" \
    --project="${PROJECT}" \
    --ddl-file="${SCHEMA_PATH}"
  echo "  schema applied"
else
  echo "  schema file not present yet (${SCHEMA_PATH}) — skipping. Apply in Phase 2.2."
fi

echo
echo "Spanner ready:"
echo "  project=${PROJECT}"
echo "  instance=${INSTANCE}"
echo "  database=${DATABASE}"
echo "  config=${CONFIG}"
echo
echo "Tear down when done with: scripts/spanner_down.sh"
