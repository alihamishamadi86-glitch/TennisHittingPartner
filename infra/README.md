# Infrastructure

One GCP project per environment. Terraform state lives in a GCS bucket per environment.

## First-time setup (staging)

```bash
# 1. Create the project + state bucket (once)
gcloud projects create <PROJECT_ID>
gcloud billing projects link <PROJECT_ID> --billing-account <BILLING_ACCOUNT>
gcloud storage buckets create gs://<PROJECT_ID>-tfstate --project <PROJECT_ID> \
  --location us-central1 --uniform-bucket-level-access
gcloud storage buckets update gs://<PROJECT_ID>-tfstate --versioning

# 2. Fill in the CHANGE-ME values
#    terraform/environments/staging.tfvars, terraform/environments/staging.gcs.tfbackend

# 3. Apply
cd terraform
gcloud auth application-default login
terraform init -backend-config=environments/staging.gcs.tfbackend
terraform apply -var-file=environments/staging.tfvars
```

The first apply deploys Google's placeholder container to each Cloud Run service; CI replaces it.

## Connect GitHub Actions

In the GitHub repo: **Settings → Environments → `staging`**, add variables:

| Variable | Value |
|---|---|
| `GCP_PROJECT_ID` | the project id |
| `GCP_REGION` | `us-central1` |
| `GCP_WIF_PROVIDER` | `terraform output -raw github_workload_identity_provider` |
| `GCP_DEPLOYER_SA` | `terraform output -raw github_deployer_service_account` |

Every push to `main` then runs CI → builds images → runs migrations (Cloud Run job) →
deploys worker, API, web → runs `scripts/smoke_ping.sh` against the deployed API.

## Google sign-in (M1)

The OAuth client can't be created by Terraform; do it once per environment:

1. **Google Auth Platform → Branding / Audience**: configure the consent screen (External,
   app name, support email). Scopes: `openid`, `email`, `profile`.
2. **Clients → Create client → Web application**. Authorized redirect URI:
   `<web_url>/api/auth/google/callback` (use `terraform output -raw web_url`).
   For local dev, create a separate client with `http://localhost:3000/api/auth/google/callback`
   and put `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in a root `.env` for docker compose.
3. Set `google_client_id` in `environments/staging.tfvars`, `terraform apply`, then store the
   secret and redeploy so Cloud Run picks up the new version:
   ```bash
   printf '%s' "$CLIENT_SECRET" | gcloud secrets versions add google-oauth-client-secret --data-file=-
   ```

Until `google_client_id` is set, the API reports Google as unavailable and the UI hides the button.

## Notes

- Cloud Run URLs are deterministic (`https://<service>-<project-number>.<region>.run.app`), which
  lets Terraform wire push endpoints and OIDC audiences without dependency cycles.
- The worker is not public: only `thp-invoker@` (used by Pub/Sub push, Cloud Scheduler and
  Cloud Tasks) holds `run.invoker`, and the worker verifies the OIDC token in-app as well.
- Topics in `event_types` must match `api/app/events/catalog.py`.
- Email uses the `console` backend in staging (messages are written to Cloud Logging) until a
  provider is wired in M7 — verification/reset links can be read from the worker logs.
- `enable_system_ping` exposes `POST /system/ping` for pipeline checks; turn it off (or put it
  behind admin auth, M1) before production.
