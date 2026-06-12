#!/usr/bin/env bash
# Source this file from the repo root to enable GCP auth for Curator.
#   source scripts/env.sh
#
# Sets GOOGLE_APPLICATION_CREDENTIALS to the project's service-account key
# so any tool that calls google.auth.default() (ADK, agents-cli, the
# agent itself) picks up the right identity. Also sets the GCP project
# and Gemini location to match app/agent.py.

_REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

export GOOGLE_APPLICATION_CREDENTIALS="${_REPO_ROOT}/.secrets/SA_aidnicloudcurator.json"
export GOOGLE_CLOUD_PROJECT="curator-research"
export GOOGLE_CLOUD_LOCATION="global"
export GOOGLE_GENAI_USE_VERTEXAI="True"

unset _REPO_ROOT

echo "Curator env set:"
echo "  GOOGLE_APPLICATION_CREDENTIALS=${GOOGLE_APPLICATION_CREDENTIALS}"
echo "  GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT}"
echo "  GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION}"
echo "  GOOGLE_GENAI_USE_VERTEXAI=${GOOGLE_GENAI_USE_VERTEXAI}"
