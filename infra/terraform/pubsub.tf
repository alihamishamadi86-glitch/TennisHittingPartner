# Per event type: topic → push subscription to the worker, with a dead-letter topic.
# Mirrors api/scripts/pubsub_bootstrap.py for the local emulator.

locals {
  pubsub_agent = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_topic" "events" {
  for_each   = toset(var.event_types)
  name       = each.value
  depends_on = [google_project_service.enabled]
}

resource "google_pubsub_topic" "dead_letter" {
  for_each   = toset(var.event_types)
  name       = "${each.value}.dlq"
  depends_on = [google_project_service.enabled]
}

resource "google_pubsub_subscription" "worker" {
  for_each = toset(var.event_types)
  name     = "${each.value}.worker"
  topic    = google_pubsub_topic.events[each.value].id

  ack_deadline_seconds = 60

  push_config {
    push_endpoint = "${local.run_url.worker}/pubsub/push"
    oidc_token {
      service_account_email = google_service_account.invoker.email
      audience              = local.run_url.worker
    }
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter[each.value].id
    max_delivery_attempts = 10
  }
}

# Retains dead-lettered messages for inspection / replay.
resource "google_pubsub_subscription" "dead_letter" {
  for_each                   = toset(var.event_types)
  name                       = "${each.value}.dlq.inspect"
  topic                      = google_pubsub_topic.dead_letter[each.value].id
  message_retention_duration = "604800s"
}

# The Pub/Sub service agent must be able to forward to the DLQ and ack the source subscription.
resource "google_pubsub_topic_iam_member" "dlq_publisher" {
  for_each = toset(var.event_types)
  topic    = google_pubsub_topic.dead_letter[each.value].id
  role     = "roles/pubsub.publisher"
  member   = local.pubsub_agent
}

resource "google_pubsub_subscription_iam_member" "dlq_subscriber" {
  for_each     = toset(var.event_types)
  subscription = google_pubsub_subscription.worker[each.value].id
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_agent
}
