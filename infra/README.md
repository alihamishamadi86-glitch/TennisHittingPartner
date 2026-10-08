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

## Club discovery (M3)

Works with no keys (free OSM services). Optional, recommended for production:

- **Geoapify key** (free tier, 3,000 credits/day): reliable geocoding plus a second court
  source. `printf '%s' "$KEY" | gcloud secrets versions add geoapify-api-key --data-file=-`
- **Overpass**: public instances are rate-limited and sometimes overloaded. For volume, run
  the open-source server and set `OVERPASS_URLS='["https://your-overpass/api/interpreter"]'`.
- **Map tiles**: set `MAP_TILE_URL` / `MAP_TILE_ATTRIBUTION` on the web service; OSM's own tile
  server is not for production traffic.

## Feature switches: payments and SMS

Both are **off by default**, so the platform can open for sign-ups before charging or texting:

| Switch | Off (default) | On |
| --- | --- | --- |
| `PAYMENTS_ENABLED` | Bookings are confirmed immediately with nothing charged online (the fee is settled with the partner). No late-cancellation fee. Checkout and Stripe webhooks return 404. | Bookings are held for 10 minutes and confirmed by payment. Stripe keys are needed (below). |
| `SMS_ENABLED` | Email reminders only. Phone verification and the text-reminder settings are hidden, and no texts are sent. | Phone verification, SMS opt-in, and texted reminders. Twilio is needed (below). |

They're set on each deploy from **GitHub Actions variables** (repo → Settings → Secrets and
variables → Actions → *Variables*, on the repo or the `staging` environment). They're plain
variables, not secrets: the values aren't sensitive, and secrets would mask them in the logs.

```bash
gh variable set PAYMENTS_ENABLED --body true   # then re-run the Deploy workflow
gh variable set SMS_ENABLED --body false
```

Anything other than `true`/`false` fails the deploy. The keys must be in place before a switch
is turned on: the API refuses to start with `PAYMENTS_ENABLED=true` in production unless Stripe
is configured. **After a `terraform apply`, re-run the Deploy workflow.** Terraform doesn't
manage these two variables, so an apply removes them and both switches fall back to off.

Locally, set them in the root `.env` (`PAYMENTS_ENABLED=true`), then `docker compose up -d`.

## Payments (M6)

When `PAYMENTS_ENABLED=true`, payments run on a **fake gateway** (simulated checkout) until
Stripe keys are configured. Production refuses to start with the fake gateway.

1. Stripe Dashboard (test mode) → Developers → API keys: copy the publishable and secret keys.
2. Developers → Webhooks → Add endpoint: `<api_url>/webhooks/stripe` (`terraform output -raw
   api_url`), events `payment_intent.succeeded` and `payment_intent.payment_failed`. Copy the
   signing secret (`whsec_…`).
3. Store the secrets and switch the provider:
   ```bash
   printf '%s' "$STRIPE_SECRET_KEY" | gcloud secrets versions add stripe-secret-key --data-file=-
   printf '%s' "$STRIPE_WEBHOOK_SECRET" | gcloud secrets versions add stripe-webhook-secret --data-file=-
   ```
   In `environments/staging.tfvars` set `payment_provider = "stripe"` and
   `stripe_publishable_key = "pk_test_…"`, then `terraform apply` and redeploy.

Locally: put `PAYMENT_PROVIDER=stripe`, `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY` and
`STRIPE_WEBHOOK_SECRET` in the root `.env`, then forward webhooks with the Stripe CLI:
`stripe listen --forward-to localhost:8000/webhooks/stripe` (it prints the `whsec_…` to use).
Test cards: `4242 4242 4242 4242` (success), `4000 0025 0000 3155` (3-D Secure).

## Club contacts (websites, phones, court booking links)

After discovery, the worker looks up each club's website, phone, email and online court-booking
page: OSM tags → Wikidata → (optional) Brave Search → the club's own site (homepage + contact
page; robots.txt respected; private/internal addresses refused). Coverage without a search key
is limited to clubs whose website is in OSM/Wikidata. To enable search (free tier):
`printf '%s' "$KEY" | gcloud secrets versions add brave-search-api-key --data-file=-`.
Backfill existing cities: `gcloud run jobs execute thp-manage --wait --args=scripts.enrich_clubs`
(add `,--force` to re-check everything).

## Notifications (M7)

Emails and texts are logged (console backends) until providers are configured.

- **Email (Resend):** verify your sending domain in Resend (adds SPF/DKIM DNS records), then
  `printf '%s' "$KEY" | gcloud secrets versions add resend-api-key --data-file=-` and set
  `email_backend = "resend"` and `email_from = "Tennis Hitting Partner <hello@yourdomain>"`.
- **SMS (Twilio):** `printf '%s' "$TOKEN" | gcloud secrets versions add twilio-auth-token --data-file=-`,
  set `sms_backend = "twilio"`, `twilio_account_sid` and either `twilio_messaging_service_sid`
  (recommended; handles opt-outs) or `twilio_from_number`. Point the number's incoming-message
  webhook to `<api_url>/webhooks/twilio/sms` so STOP replies turn reminders off.
  **US numbers need A2P 10DLC registration** (brand + campaign) before texts deliver reliably —
  start it early, it can take days to weeks.

Reminders (24 h and 2 h before) and the post-session rebook message are sent by the
`send-notifications` scheduler job every minute. No texts between 21:00 and 08:00 local time.

## First admin

Register the account in the web app, then promote it:

```bash
gcloud run jobs execute thp-manage --region us-central1 --wait \
  --args=scripts.create_admin,you@example.com
```

Locally: `docker compose exec api python -m scripts.create_admin you@example.com`.

## Notes

- Cloud Run URLs are deterministic (`https://<service>-<project-number>.<region>.run.app`), which
  lets Terraform wire push endpoints and OIDC audiences without dependency cycles.
- The worker is not public: only `thp-invoker@` (used by Pub/Sub push, Cloud Scheduler and
  Cloud Tasks) holds `run.invoker`, and the worker verifies the OIDC token in-app as well.
- Topics in `event_types` must match `api/app/events/catalog.py`.
- Email uses the `console` backend in staging (messages are written to Cloud Logging) until a
  provider is wired in M7 — verification/reset links can be read from the worker logs.
- Profile photos live in the public `<project>-media` bucket; the API signs upload URLs through
  IAM `signBlob` on its own service account (no key files).
- `enable_system_ping` exposes `POST /system/ping` for pipeline checks; turn it off (or put it
  behind admin auth, M1) before production.
