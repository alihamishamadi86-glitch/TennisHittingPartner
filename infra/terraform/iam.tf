# Runtime identities — one per workload, least privilege.
resource "google_service_account" "api" {
  account_id   = "${local.name_prefix}-api"
  display_name = "THP API (Cloud Run)"
}

resource "google_service_account" "worker" {
  account_id   = "${local.name_prefix}-worker"
  display_name = "THP worker (Cloud Run)"
}

resource "google_service_account" "web" {
  account_id   = "${local.name_prefix}-web"
  display_name = "THP web (Cloud Run)"
}

# Identity Pub/Sub, Cloud Scheduler and Cloud Tasks use to call the worker (OIDC).
resource "google_service_account" "invoker" {
  account_id   = "${local.name_prefix}-invoker"
  display_name = "THP push invoker"
}

# for_each keys must be known at plan time, so key by workload name — SA emails are only
# known after the accounts exist.
locals {
  backend_service_accounts = {
    api    = google_service_account.api.email
    worker = google_service_account.worker.email
  }
  backend_roles = ["roles/cloudsql.client", "roles/pubsub.publisher", "roles/cloudtasks.enqueuer", "roles/logging.logWriter"]
}

resource "google_project_iam_member" "backend_roles" {
  for_each = {
    for pair in setproduct(keys(local.backend_service_accounts), local.backend_roles) :
    "${pair[0]}|${pair[1]}" => { workload = pair[0], role = pair[1] }
  }
  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${local.backend_service_accounts[each.value.workload]}"
}

# API/worker enqueue Cloud Tasks that run as the invoker identity.
resource "google_service_account_iam_member" "backend_act_as_invoker" {
  for_each           = local.backend_service_accounts
  service_account_id = google_service_account.invoker.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${each.value}"
}

# Pub/Sub service agent mints OIDC tokens for push subscriptions.
resource "google_service_account_iam_member" "pubsub_token_creator" {
  service_account_id = google_service_account.invoker.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
  depends_on         = [google_project_service.enabled]
}
