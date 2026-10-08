variable "project_id" {
  type        = string
  description = "GCP project id for this environment (one project per environment)."
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "environment" {
  type = string
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "github_repository" {
  type        = string
  description = "owner/repo allowed to deploy via Workload Identity Federation."
}

variable "event_types" {
  type        = list(string)
  description = "Pub/Sub topics. Keep in sync with api/app/events/catalog.py (EVENT_TYPES)."
  default = [
    "system.ping",
    "user.registered",
    "auth.email_verification_requested",
    "auth.password_reset_requested",
    "partner.application_submitted",
    "partner.verification_decided",
    "clubs.discovery.requested",
    "booking.confirmed",
    "booking.cancelled",
    "booking.completed",
    "booking.rained_out",
    "payment.refund_requested",
  ]
}

variable "db_tier" {
  type    = string
  default = "db-f1-micro"
}

variable "db_deletion_protection" {
  type    = bool
  default = true
}

variable "enable_system_ping" {
  type    = bool
  default = true
}

variable "google_client_id" {
  type        = string
  default     = ""
  description = "OAuth 2.0 Web client id for Google sign-in. Empty disables Google sign-in."
}

variable "payment_provider" {
  type        = string
  default     = "fake"
  description = "\"stripe\" once keys are in Secret Manager; \"fake\" simulates payments (never in production)."
  validation {
    condition     = contains(["fake", "stripe"], var.payment_provider)
    error_message = "payment_provider must be fake or stripe."
  }
}

variable "stripe_publishable_key" {
  type        = string
  default     = ""
  description = "Stripe publishable key (pk_test_… / pk_live_…). Public by design."
}
