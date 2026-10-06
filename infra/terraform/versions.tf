terraform {
  required_version = ">= 1.9"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Partial config: `terraform init -backend-config=environments/<env>.gcs.tfbackend`
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_project" "this" {}

locals {
  name_prefix = "thp"

  # Cloud Run's deterministic URLs, so services can reference each other (and themselves,
  # e.g. as the OIDC audience) without dependency cycles.
  run_url = { for svc in ["api", "worker", "web"] :
    svc => "https://${local.name_prefix}-${svc}-${data.google_project.this.number}.${var.region}.run.app"
  }

  placeholder_image = "us-docker.pkg.dev/cloudrun/container/hello"
}
