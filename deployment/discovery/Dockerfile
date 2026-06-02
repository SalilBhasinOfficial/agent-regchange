# Curator Discovery service — Dockerfile.
#
# This file intentionally REUSES the top-level repo Dockerfile to avoid
# duplicating the Python 3.12 + uv setup. The only difference between
# the chain service and the discovery service is the entrypoint, which
# we override at deploy time via `--command` / `--args` on `gcloud run
# deploy`. This file is therefore documentation rather than a true
# image — keep the top-level Dockerfile as the single source of truth.
#
# Deploy command (D6):
#
#   gcloud run deploy curator-discovery \
#     --source=. \
#     --region=asia-south1 \
#     --project=curator-research \
#     --service-account=curator-ai-engine@curator-research.iam.gserviceaccount.com \
#     --no-allow-unauthenticated \
#     --memory=512Mi \
#     --command="uv" \
#     --args="run,uvicorn,app.discovery.service:app,--host,0.0.0.0,--port,8080" \
#     --set-env-vars=GOOGLE_CLOUD_PROJECT=curator-research,SPANNER_INSTANCE=curator-graph,SPANNER_DATABASE=curator,CURATOR_DISCOVERY_TOPIC=curator-discoveries
#
# Alternative — if `gcloud run deploy` cannot override CMD cleanly,
# uncomment the `FROM` + `CMD` lines below and build with
# `gcloud builds submit -f deployment/discovery/Dockerfile .` instead.

# FROM python:3.12-slim
# RUN pip install --no-cache-dir uv==0.8.13
# WORKDIR /code
# COPY ./pyproject.toml ./README.md ./uv.lock* ./
# COPY ./app ./app
# RUN uv sync --frozen
# ARG COMMIT_SHA=""
# ENV COMMIT_SHA=${COMMIT_SHA}
# EXPOSE 8080
# CMD ["uv", "run", "uvicorn", "app.discovery.service:app", "--host", "0.0.0.0", "--port", "8080"]
