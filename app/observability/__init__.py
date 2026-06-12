# Curator observability package.
#
# Best-effort run-level logging into Spanner ``agent_runs``. Activated only
# when ``CURATOR_AGENT_RUN_LOG=1``; otherwise every public call is a no-op
# so the offline chain regression stays free of GCP dependencies.
