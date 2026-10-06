# Images are deployed by CI (`gcloud run deploy --image`); Terraform owns everything else.
# The placeholder image lets the first `apply` succeed before any image is pushed.

locals {
  backend_env = {
    ENVIRONMENT        = var.environment
    GCP_PROJECT_ID     = var.project_id
    LOG_LEVEL          = "INFO"
    ENABLE_SYSTEM_PING = tostring(var.enable_system_ping)
    PUBLIC_WEB_URL     = local.run_url.web
    COOKIE_SECURE      = "true"
    GOOGLE_CLIENT_ID   = var.google_client_id
    EMAIL_BACKEND      = "console" # until an email provider is wired (M7)
    STORAGE_BACKEND    = "gcs"
    GCS_BUCKET         = google_storage_bucket.media.name
  }
}

resource "google_cloud_run_v2_service" "api" {
  name                = "${local.name_prefix}-api"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.api.email
    scaling {
      min_instance_count = 0
      max_instance_count = 10
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }

    containers {
      image = local.placeholder_image

      dynamic "env" {
        for_each = merge(local.backend_env, {
          CORS_ORIGINS = jsonencode([local.run_url.web])
        })
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.backend_secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      startup_probe {
        http_get {
          path = "/healthz"
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }

  depends_on = [google_secret_manager_secret_iam_member.backend_access]
}

resource "google_cloud_run_v2_service" "worker" {
  name                = "${local.name_prefix}-worker"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL" # IAM-protected: only the invoker SA may call it
  deletion_protection = false

  template {
    service_account = google_service_account.worker.email
    scaling {
      min_instance_count = 0
      max_instance_count = 10
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }

    containers {
      image   = local.placeholder_image
      command = ["sh", "-c", "exec uvicorn app.worker:app --host 0.0.0.0 --port $PORT"]

      dynamic "env" {
        for_each = merge(local.backend_env, {
          PUSH_AUTH_ENABLED        = "true"
          PUSH_AUTH_AUDIENCE       = local.run_url.worker
          PUSH_AUTH_ALLOWED_EMAILS = jsonencode([google_service_account.invoker.email])
        })
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.backend_secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }

  depends_on = [google_secret_manager_secret_iam_member.backend_access]
}

resource "google_cloud_run_v2_service" "web" {
  name                = "${local.name_prefix}-web"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.web.email
    scaling {
      min_instance_count = 0
      max_instance_count = 10
    }

    containers {
      image = local.placeholder_image
      env {
        name  = "API_INTERNAL_URL"
        value = local.run_url.api
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }
}

# Migrations run as a one-off job before each deploy (CI: `gcloud run jobs execute --wait`).
resource "google_cloud_run_v2_job" "migrate" {
  name                = "${local.name_prefix}-migrate"
  location            = var.region
  deletion_protection = false

  template {
    template {
      service_account = google_service_account.api.email
      max_retries     = 0

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.main.connection_name]
        }
      }

      containers {
        image   = local.placeholder_image
        command = ["alembic", "upgrade", "head"]

        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.database_url.secret_id
              version = "latest"
            }
          }
        }

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, client, client_version]
  }

  depends_on = [google_secret_manager_secret_iam_member.backend_access]
}

# One-off management commands, e.g.
#   gcloud run jobs execute thp-manage --wait --args=scripts.create_admin,you@example.com
resource "google_cloud_run_v2_job" "manage" {
  name                = "${local.name_prefix}-manage"
  location            = var.region
  deletion_protection = false

  template {
    template {
      service_account = google_service_account.api.email
      max_retries     = 0

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.main.connection_name]
        }
      }

      containers {
        image   = local.placeholder_image
        command = ["python", "-m"]
        args    = ["scripts.create_admin", "--help"]

        dynamic "env" {
          for_each = local.backend_secrets
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = env.value
                version = "latest"
              }
            }
          }
        }

        dynamic "env" {
          for_each = local.backend_env
          content {
            name  = env.key
            value = env.value
          }
        }

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, client, client_version]
  }

  depends_on = [google_secret_manager_secret_iam_member.backend_access]
}

# Public: web and API (API authorization is enforced in-app). Worker: invoker SA only.
resource "google_cloud_run_v2_service_iam_member" "public" {
  for_each = {
    api = google_cloud_run_v2_service.api.name
    web = google_cloud_run_v2_service.web.name
  }
  name     = each.value
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "worker_invoker" {
  name     = google_cloud_run_v2_service.worker.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.invoker.email}"
}
