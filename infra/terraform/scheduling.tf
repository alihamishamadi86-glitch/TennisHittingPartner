# Safety-net sweep for the transactional outbox (the API also relays right after commit).
resource "google_cloud_scheduler_job" "outbox_relay" {
  name      = "${local.name_prefix}-outbox-relay"
  region    = var.region
  schedule  = "* * * * *"
  time_zone = "Etc/UTC"

  http_target {
    http_method = "POST"
    uri         = "${local.run_url.worker}/tasks/outbox-relay"
    oidc_token {
      service_account_email = google_service_account.invoker.email
      audience              = local.run_url.worker
    }
  }

  retry_config {
    retry_count = 1
  }

  depends_on = [google_project_service.enabled]
}

# Daily: re-discover clubs for cities whose data is older than CITY_REFRESH_DAYS.
resource "google_cloud_scheduler_job" "refresh_cities" {
  name      = "${local.name_prefix}-refresh-cities"
  region    = var.region
  schedule  = "17 4 * * *"
  time_zone = "Etc/UTC"

  http_target {
    http_method = "POST"
    uri         = "${local.run_url.worker}/tasks/refresh-cities"
    oidc_token {
      service_account_email = google_service_account.invoker.email
      audience              = local.run_url.worker
    }
  }

  depends_on = [google_project_service.enabled]
}

# Delayed jobs (booking hold expiry, reminders) — used from M5 onward.
resource "google_cloud_tasks_queue" "default" {
  name     = "${local.name_prefix}-default"
  location = var.region

  retry_config {
    max_attempts  = 10
    min_backoff   = "5s"
    max_backoff   = "300s"
    max_doublings = 5
  }

  depends_on = [google_project_service.enabled]
}
