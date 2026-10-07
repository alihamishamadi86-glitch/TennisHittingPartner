# Secrets injected into the backend (API, worker, migrate job) as environment variables.

resource "random_password" "jwt" {
  length  = 64
  special = false
}

resource "google_secret_manager_secret" "jwt_secret" {
  secret_id = "jwt-secret"
  replication {
    auto {}
  }
  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_version" "jwt_secret" {
  secret      = google_secret_manager_secret.jwt_secret.id
  secret_data = random_password.jwt.result
}

# The OAuth client is created manually in the console (see infra/README.md). Terraform seeds a
# placeholder version; set the real value with:
#   printf '%s' "$SECRET" | gcloud secrets versions add google-oauth-client-secret --data-file=-
resource "google_secret_manager_secret" "google_client_secret" {
  secret_id = "google-oauth-client-secret"
  replication {
    auto {}
  }
  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_version" "google_client_secret_placeholder" {
  secret      = google_secret_manager_secret.google_client_secret.id
  secret_data = "unset"
  lifecycle {
    ignore_changes = [secret_data, enabled]
  }
}

# Geoapify (OSM-based geocoding/places, free tier). Optional: without it the backend uses the
# free OSM services (Nominatim + Overpass). Set with:
#   printf '%s' "$KEY" | gcloud secrets versions add geoapify-api-key --data-file=-
resource "google_secret_manager_secret" "geoapify_api_key" {
  secret_id = "geoapify-api-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_version" "geoapify_api_key_placeholder" {
  secret      = google_secret_manager_secret.geoapify_api_key.id
  secret_data = " " # blank = disabled; the app strips whitespace
  lifecycle {
    ignore_changes = [secret_data, enabled]
  }
}

locals {
  # env var name => secret id
  backend_secrets = {
    DATABASE_URL         = google_secret_manager_secret.database_url.secret_id
    JWT_SECRET           = google_secret_manager_secret.jwt_secret.secret_id
    GOOGLE_CLIENT_SECRET = google_secret_manager_secret.google_client_secret.secret_id
    GEOAPIFY_API_KEY     = google_secret_manager_secret.geoapify_api_key.secret_id
  }
}

resource "google_secret_manager_secret_iam_member" "backend_access" {
  for_each = {
    for pair in setproduct(keys(local.backend_service_accounts), keys(local.backend_secrets)) :
    "${pair[0]}|${pair[1]}" => { workload = pair[0], env = pair[1] }
  }
  secret_id = local.backend_secrets[each.value.env]
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.backend_service_accounts[each.value.workload]}"

  depends_on = [
    google_secret_manager_secret_version.database_url,
    google_secret_manager_secret_version.jwt_secret,
    google_secret_manager_secret_version.google_client_secret_placeholder,
    google_secret_manager_secret_version.geoapify_api_key_placeholder,
  ]
}
