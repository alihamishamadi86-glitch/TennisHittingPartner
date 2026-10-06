# Public profile photos. Browsers upload directly with V4 signed URLs issued by the API.

resource "google_storage_bucket" "media" {
  name                        = "${var.project_id}-media"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "inherited"
  force_destroy               = var.environment != "production"

  cors {
    origin          = [local.run_url.web]
    method          = ["PUT", "GET"]
    response_header = ["Content-Type", "x-goog-content-length-range"]
    max_age_seconds = 3600
  }

  # Abandoned uploads (never attached to a profile) are cleaned up by an M8 sweep; keep
  # noncurrent versions from accumulating meanwhile.
  versioning {
    enabled = false
  }

  depends_on = [google_project_service.enabled]
}

# Profile photos are public marketing content.
resource "google_storage_bucket_iam_member" "media_public_read" {
  bucket = google_storage_bucket.media.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

resource "google_storage_bucket_iam_member" "media_api_admin" {
  bucket = google_storage_bucket.media.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.api.email}"
}

# Signing URLs without a key file uses IAM signBlob on the API's own service account.
resource "google_service_account_iam_member" "api_sign_blob" {
  service_account_id = google_service_account.api.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.api.email}"
}
