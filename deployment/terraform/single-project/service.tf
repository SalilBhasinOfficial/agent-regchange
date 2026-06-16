# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


resource "google_cloud_run_v2_service" "app" {
  name                = var.project_name
  location            = var.region
  project             = var.project_id
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"
  labels = {
    "created-by"                  = "adk"
  }

  template {
    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello"
      resources {
        limits = {
          cpu    = "4"
          memory = "8Gi"
        }
      }

      env {
        name  = "DATA_STORE_ID"
        value = data.external.data_store_id.result.data_store_id
      }

      env {
        name  = "DATA_STORE_REGION"
        value = var.data_store_region
      }

      env {
        name  = "LOGS_BUCKET_NAME"
        value = google_storage_bucket.logs_data_bucket.name
      }

      env {
        name  = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
        value = "NO_CONTENT"
      }

      # ---- Curator runtime flags ----
      # Without these a `terraform apply` reverts the service to STUB mode:
      # canned placeholder obligations, no cost logging, mock grounding. They
      # must be codified here so the deployed service is "real" after any apply.
      env {
        name  = "CURATOR_REAL_LLM"
        value = "1"
      }
      env {
        name  = "CURATOR_GROUNDING"
        value = "spanner"
      }
      env {
        name  = "CURATOR_AGENT_RUN_LOG"
        value = "1"
      }
      env {
        name  = "CURATOR_GEMINI_MODEL"
        value = "gemini-2.5-flash-lite"
      }
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "True"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        # Gemini flash-lite is served via the global endpoint (see DECISIONS-9);
        # data residency is governed by Spanner's asia-south1 region, not this.
        name  = "GOOGLE_CLOUD_LOCATION"
        value = "global"
      }
      env {
        name  = "SPANNER_INSTANCE"
        value = "curator-graph"
      }
      env {
        name  = "SPANNER_DATABASE"
        value = "curator"
      }
      # Silence the Spanner client's built-in Cloud Monitoring metrics
      # exporter — it deadline-exceeds on Cloud Run, spamming logs and
      # adding latency to the persistence path.
      env {
        name  = "SPANNER_DISABLE_BUILTIN_METRICS"
        value = "true"
      }
      # OTEL→Cloud Trace export is opt-in; the exporter SSL-EOFs on Cloud
      # Run and starves request threads on long large-doc runs.
      env {
        name  = "CURATOR_OTEL_TO_CLOUD"
        value = "0"
      }
    }

    service_account = google_service_account.app_sa.email
    max_instance_request_concurrency = 40

    scaling {
      min_instance_count = 1
      max_instance_count = 10
    }

    session_affinity = true
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  # This lifecycle block prevents Terraform from overwriting the container image when it's
  # updated by Cloud Run deployments outside of Terraform (e.g., via CI/CD pipelines)
  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }

  # Make dependencies conditional to avoid errors.
  depends_on = [
    resource.google_project_service.services,
  ]
}
