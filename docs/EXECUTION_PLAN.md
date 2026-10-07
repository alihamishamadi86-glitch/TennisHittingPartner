# Tennis Hitting Partner Platform — Execution Plan

Technical execution plan for the platform. Business economics are out of scope here;
see the original *Tennis Hitting Partner Agency Plan* for those.

**Stack:** Python (FastAPI) REST backend · Next.js (React + TypeScript) frontend ·
Google Cloud (Cloud Run, Cloud SQL Postgres + PostGIS, Pub/Sub, Cloud Tasks).

## Progress

| Milestone | Scope | Status |
|---|---|---|
| M0 | Foundation & infrastructure | 🟡 Code complete — awaiting GCP staging apply |
| M1 | Authentication (email/password + Google) | 🟡 Code complete — needs Google OAuth client per env |
| M2 | Profiles & levels | ✅ Code complete |
| M3 | Club discovery | ✅ Code complete |
| M4 | Availability & partner search | ⬜ |
| M5 | Booking core | ⬜ |
| M6 | Payments & policies | ⬜ |
| M7 | Notifications | ⬜ |
| M8 | Payouts, reviews, admin, retention | ⬜ |

## Working defaults (open decisions)

Assumed until decided otherwise:

1. **Market:** US-only at launch (affects SMS 10DLC, 1099 payouts, Places region bias).
2. **Booking type:** instant booking on open slots (no partner approval step).
3. **Partner selection:** client picks from search results.
4. **Admin tooling:** focused admin pages in Next.js (changed from SQLAdmin in M2 — the partner
   workflow needs custom logic, and the app's auth/roles are reused).

---

## 1. Architecture

```
                ┌──────────────────────┐
  Browser ───▶  │ Next.js (Cloud Run)  │
                └─────────┬────────────┘
                          │ REST (OpenAPI-typed client)
                ┌─────────▼────────────┐        ┌──────────────────┐
                │ FastAPI API          │──SQL──▶│ Cloud SQL         │
                │ (Cloud Run)          │        │ Postgres+PostGIS  │
                └──┬──────────┬────────┘        └──────────────────┘
          publish  │          │ schedule              ▲
                ┌──▼───────┐ ┌▼────────────┐          │
                │ Pub/Sub  │ │ Cloud Tasks │          │
                └──┬───────┘ └┬────────────┘          │
              push │          │ push at time T        │
                ┌──▼──────────▼─────────┐             │
                │ Worker service        │─────────────┘
                │ (FastAPI, Cloud Run)  │──▶ Places API / OSM / Stripe / Email / SMS
                └───────────────────────┘
```

| Concern | GCP service |
|---|---|
| API, worker, web | Cloud Run (3 services) |
| Database | Cloud SQL Postgres 16 + PostGIS |
| Events | Pub/Sub (push subscriptions → worker, dead-letter topics) |
| Delayed jobs (reminders, hold expiry) | Cloud Tasks — Pub/Sub has no scheduled delivery |
| Cron (club data refresh) | Cloud Scheduler → Pub/Sub |
| Files (profile photos) | Cloud Storage with signed URLs |
| Secrets | Secret Manager |
| CI/CD | Artifact Registry + GitHub Actions (Workload Identity Federation) |
| IaC | Terraform |
| Observability | Cloud Logging / Error Reporting, structured JSON logs with trace id |

### Pub/Sub conventions

1. **Idempotent consumers** — Pub/Sub is at-least-once; handlers record `processed_events(event_id)`.
2. **Dead-letter topic** on every subscription.
3. **Versioned envelope:** `{"event_id", "type", "version", "occurred_at", "data"}`.
4. **Transactional outbox** — events are written in the same DB transaction as the state
   change; a relay publishes them. No lost events, no phantom events.

### Event catalog (v1)

| Topic | Producer | Consumers |
|---|---|---|
| `user.registered` | API | welcome / verification email |
| `profile.completed` | API | partner verification queue |
| `clubs.discovery.requested` | API | scraper worker |
| `clubs.discovery.completed` | worker | city status → ready |
| `booking.created` / `confirmed` / `cancelled` / `completed` | API | notifications, reminder scheduling, payouts |
| `payment.succeeded` / `refunded` | Stripe webhook | booking confirmation, credits |
| `notification.send` | any | email/SMS sender |

---

## 2. Requirements design

### R1 — Registration (email/password + Google)

Auth is built in FastAPI (own user table, roles, JWT patterns).

- **Email/password:** Argon2 hashing, email verification, password reset (signed 1h tokens), rate-limited login.
- **Google:** OIDC Authorization Code + PKCE via Authlib, server-side. Verify ID token, read
  `sub`, `email`, `email_verified`. Link to an existing account when a verified email matches.
- **Sessions:** 15-min access JWT + rotating 30-day refresh token (DB-stored), both in
  httpOnly / Secure / SameSite=Lax cookies. Next.js middleware guards routes by role.
- **Tables:** `users`, `auth_identities(provider, provider_user_id)`, `refresh_tokens`, `email_tokens`.
- **Endpoints:** `POST /auth/register|login|logout|refresh|verify-email|forgot-password|reset-password`,
  `GET /auth/google/login`, `GET /auth/google/callback`, `GET /me`.

### R2 — Two user types with level profiles

At signup the user picks **Client** or **Partner** (`users.role`: `client | partner | admin`).
An onboarding wizard collects the profile; booking is gated until it is complete.

| Field | Client | Partner |
|---|---|---|
| NTRP (1.5–7.0, 0.5 steps) | self-rated | self-rated → admin-verified |
| UTR (optional) | ✓ | ✓ |
| Years playing, dominant hand, play style | ✓ | ✓ |
| Goals (rally, match play, fitness) | ✓ | — |
| Background (college/varsity/club), bio | — | ✓ |
| Photo | optional | required |
| Home city / location (PostGIS point) | ✓ | ✓ |
| Service radius, preferred clubs | — | ✓ |
| Verification: `applied → screened → approved/rejected` | — | ✓ |

- A short questionnaire suggests an NTRP rating to curb inflation.
- Matching rule: partner level ≥ client level (+ configurable margin).
- **Tables:** `client_profiles`, `partner_profiles`, `partner_clubs`, `partner_verifications`.
- **Endpoints:** `PUT /me/client-profile`, `PUT /me/partner-profile`, `POST /me/photo-upload-url`,
  `GET /admin/partners?status=applied`, `POST /admin/partners/{id}/verify`.

### R3 — Club discovery

Do **not** scrape Google Maps / Search HTML (ToS violation, brittle, blocked). Use a pipeline:

1. **Geocode** the city (Google Geocoding API) → centroid + bounding box.
2. **OpenStreetMap Overpass** (free): `sport=tennis` on `leisure=pitch|sports_centre` and
   `club=sport`. Captures public park courts.
3. **Google Places API (New) Text Search** — "tennis club", "tennis courts" in the city —
   for ratings, hours, phone, website.
4. **Optional enrichment crawler** for club websites (`httpx` + BeautifulSoup, Playwright
   fallback): court count, surface, booking link. Respect robots.txt, rate-limit, cache.
5. **Deduplicate** across sources: PostGIS `ST_DWithin(~75m)` + `rapidfuzz` name similarity.

**Flow:** user enters city → API checks `city_discoveries`. If fresh (< 30 days) return clubs;
otherwise publish `clubs.discovery.requested` and return `202`. Worker runs the pipeline,
upserts `clubs (geom geography(Point))`, publishes `clubs.discovery.completed`. Frontend polls
status. Cloud Scheduler refreshes active cities monthly.

**Compliance:** Places `place_id` may be stored indefinitely; other Places content has
caching limits — refresh rather than store forever. OSM requires attribution.

- **Endpoints:** `POST /cities/discover {city, country}`, `GET /cities/{id}/status`,
  `GET /clubs?city_id=&near=lat,lng&radius_km=`, `GET /clubs/{id}`.

### R4 — Booking

- **Availability:** partner weekly rules in their timezone (`availability_rules`) plus
  `availability_exceptions`. Slots computed server-side: rules − bookings − travel buffer.
- **Search:** `GET /partners/search?city_id=&club_id=&date=&duration=60&min_level=` — level
  match, free slots, serves that club/area.
- **Double-booking protection** (DB-level):
  ```sql
  EXCLUDE USING gist (partner_id WITH =, tstzrange(starts_at, ends_at) WITH &&)
    WHERE (status IN ('held', 'confirmed'))
  ```
- **Hold → pay:** booking created as `held` with `expires_at = now + 10 min`; a Cloud Tasks
  job expires unpaid holds.
- **State machine:** `held → confirmed → completed`, plus `expired | cancelled_free |
  cancelled_late | rained_out | partner_cancelled | no_show`.
- **Policies:** cancellation window, late-cancel fee, rain-credit expiry live in one pure
  module (`services/booking_policy.py`), config-driven and heavily unit-tested.
- **Gates:** complete profile + signed waiver (`waiver_versions`, `waiver_signatures` with
  IP, user agent, timestamp).
- **Endpoints:** `GET /partners/{id}/slots?from=&to=`, `POST /bookings`, `GET /bookings`,
  `POST /bookings/{id}/cancel`, `POST /bookings/{id}/complete` (partner),
  `POST /admin/bookings/{id}/rainout`.

---

## 3. Repository layout

```
TennisHittingPartner/
├── api/                      # FastAPI
│   ├── app/
│   │   ├── main.py           # API service entry
│   │   ├── worker.py         # Worker service entry (Pub/Sub push + Cloud Tasks routes)
│   │   ├── core/             # config, db, logging
│   │   ├── models/           # SQLAlchemy 2.0
│   │   ├── schemas/          # Pydantic v2
│   │   ├── routers/          # auth, profiles, clubs, partners, bookings, admin
│   │   ├── services/         # business logic
│   │   ├── integrations/     # google_oauth, places, overpass, stripe, gcs
│   │   └── events/           # envelope, outbox, relay, handlers
│   ├── alembic/
│   └── tests/
├── web/                      # Next.js App Router, TS, Tailwind
├── infra/terraform/          # Cloud Run, Cloud SQL, Pub/Sub, Tasks, IAM, secrets
├── docker-compose.yml        # postgis, pubsub-emulator, mailpit, api, worker
└── .github/workflows/
```

---

## 4. Milestones

### M0 — Foundation & infrastructure (weeks 1–2)
- Monorepo, docker-compose (PostGIS, Pub/Sub emulator, Mailpit), FastAPI + Next.js skeletons.
- Terraform for staging: Cloud Run, Cloud SQL, Pub/Sub, Secret Manager, Artifact Registry.
- CI (ruff, mypy, pytest, tsc, eslint) → build → deploy.
- Outbox + Pub/Sub publish/consume plumbing with a `system.ping` event.
- **Exit:** push to main deploys; a test event flows API → Pub/Sub → worker on staging.

**M0 status (2026-10-06):**
- [x] Monorepo, docker-compose (PostGIS, Pub/Sub emulator, Mailpit), Makefile
- [x] FastAPI API + worker, structured Cloud Logging output, health/readiness probes
- [x] Transactional outbox, relay, idempotent handler dispatch, `system.ping` round trip
- [x] Alembic baseline (PostGIS, btree_gist, outbox tables) and pytest suite
- [x] Next.js app, typed OpenAPI client, same-origin `/api` proxy, standalone Docker image
- [x] Terraform for staging (validated) and GitHub Actions CI + deploy workflows
- [x] Local exit check: `make smoke` passes through the real Pub/Sub emulator
- [ ] Create GCP project, `terraform apply`, configure GitHub variables (infra/README.md)
- [ ] Staging exit check: deploy workflow smoke test passes
- [ ] Start Twilio 10DLC registration (long lead time for M7)

### M1 — Authentication / R1 (weeks 3–4)
- Email/password with verification & reset, Google OIDC with account linking.
- Cookie sessions, role guards, Next.js auth pages.
- **Exit:** both signup paths work on staging; integration tests cover linking and token rotation.

**M1 status (2026-10-07):**
- [x] Email/password register + login (Argon2), per-account lockout, timing-safe unknown-user path
- [x] Rotating refresh tokens with reuse detection (family revocation, 30s multi-tab grace)
- [x] httpOnly cookie sessions; Origin check on state-changing requests; open-redirect guard
- [x] Email verification + password reset; tokens minted in the worker (never in Pub/Sub)
- [x] Google OIDC (PKCE + nonce + signed state cookie) with safe account linking
  (unverified password accounts are reclaimed, not merged — pre-account-takeover protection)
- [x] One-time role choice for Google sign-ups (`PUT /me/role`)
- [x] Next.js: login, register (role cards), forgot/reset, verify-email, onboarding, dashboard;
  `proxy.ts` renews expired sessions via `GET /auth/session/renew`
- [x] 47 backend tests; browser-verified register → verify email → sign out → sign in locally
- [ ] Create Google OAuth clients (local + staging) — see infra/README.md
- [ ] Staging exit check once M0 infra is applied

**Design notes**
- The refresh cookie is scoped to `/api/auth`, so page requests can't see it; protected pages
  without an access cookie bounce through `/api/auth/session/renew?next=…`.
- Admins are never self-assigned; an admin bootstrap command lands with the M2 admin queue.

### M2 — Profiles & levels / R2 (week 5)
- Role selection, onboarding wizards, NTRP questionnaire, photo upload (GCS signed URLs).
- Partner verification queue (SQLAdmin).
- **Exit:** partner applies → admin approves; clients see profile gate.

**M2 status (2026-10-07):**
- [x] Client and partner profiles (NTRP in 0.5 steps, UTR, years, hand, style, location;
  goals for clients; background, bio, travel radius for partners) with DB check constraints
- [x] NTRP questionnaire served by the API (`/levels/questionnaire`, `/levels/suggest`);
  self-assessment capped at 5.5, and at 4.0 without match experience
- [x] Profile photos: signed direct-to-GCS uploads (V4, content-type + size bound), ownership
  and type verified on attach, previous upload deleted; local-disk backend for development
- [x] Partner workflow `draft → applied → screened → approved/rejected` (resubmit after
  rejection) with an audit trail; minimum self-rated NTRP 4.5 to apply
- [x] Emails via Pub/Sub: admins on new applications, partner on each decision (with note)
- [x] Next.js: step-by-step profile forms for both roles, level quiz, photo upload, dashboard
  progress + application status, admin queue and decision page
- [x] `scripts.create_admin` (local: docker compose; GCP: `thp-manage` Cloud Run job)
- [x] 90 backend tests; browser-verified partner apply → admin approve → email, and player onboarding

**Deferred**
- `partner_clubs` moves to M3, where clubs exist.
- Image resizing/re-encoding of uploads and a sweep of never-attached uploads (M8).

### M3 — Club discovery / R3 (weeks 6–7)
- Geocode + Overpass + Places worker, dedupe, PostGIS storage, city cache, status polling.
- Map/list UI; partners select clubs; Scheduler refresh.
- **Exit:** new city populated in ≲30s; repeat lookup is instant.

**M3 status (2026-10-07):** implemented with open data instead of Google Places (cost):

| Need | Provider | Cost |
|---|---|---|
| Courts & clubs | OpenStreetMap via **Overpass** (`sport=tennis` pitches, centres, clubs) | Free |
| Naming unnamed courts | Overpass: parks/schools within 200 m of courts + neighbourhoods | Free |
| City geocoding | **Geoapify** (OSM-based) when keyed, else **Nominatim** | Free tier 3k/day · free |
| Extra source + addresses | **Geoapify Places**, filtered to tennis (no tennis category) | ~1 credit / 20 places |
| Map tiles | Leaflet + OSM tiles (dev); runtime-configurable for prod | Free (dev) |

- [x] `cities` (+ input `city_aliases` so re-phrasings don't re-geocode), `clubs` (PostGIS
  geography + GiST index), `partner_clubs`
- [x] Worker pipeline: sources fetched concurrently, succeeds if any answers; merge by OSM id;
  courts attached to venues (chaining through adjacent courts); remaining courts clustered;
  duplicate venues collapsed; upsert by stable key; vanished clubs hidden, not deleted
- [x] Resilience: Overpass mirror fallback, up to 5 attempts with Pub/Sub backoff, stale data
  kept while a refresh runs/fails, daily refresh of cities older than 30 days
- [x] API: `POST /cities/discover`, `GET /cities/{id}`, `GET /clubs` (city or lat/lon radius,
  distance-sorted), `GET|PUT /me/partner-clubs`, `POST /admin/cities/{id}/refresh`
- [x] Next.js `/clubs`: auto-searches the profile city, list + Leaflet map, filters; partners
  tick "I play here"; dashboard steps link to it
- [x] 126 backend tests; live run on Austin, TX found 296 sites / ~770 courts

**Postal codes (2026-10-08):** an optional postal code on searches and profiles. It is geocoded
once (cached in `postal_codes`), its city is discovered, and clubs are listed by distance
around it (2–25 km, across city limits). If the free-text region doesn't geocode, discovery
retries with city + country.

**Production notes**
- Public Overpass instances were intermittently overloaded during testing (504s). Discovery
  is low-volume (one query per city per month), but for launch either add a Geoapify key
  (second court source; results still flow when Overpass is down) or self-host Overpass
  (open source, `wiktorn/overpass-api` with a US extract) and set `OVERPASS_URLS`.
- OSM's tile server is for development only; set `MAP_TILE_URL` (e.g. Geoapify/MapTiler tiles)
  for production. Keep the OSM attribution (ODbL).

### M4 — Availability & partner search (week 8)
- Availability rules/exceptions, slot engine (timezone/DST tests), search endpoint + UI.
- **Exit:** client searches by city/club/date and sees real open slots.

### M5 — Booking core / R4 (weeks 9–10)
- Hold flow, exclusion constraint, Cloud Tasks expiry, state machine, waiver signing,
  "My sessions" for both roles, cancellation via policy module.
- **Exit:** concurrency tests pass; full booking lifecycle on staging.

### M6 — Payments & policies (weeks 11–12)
- Stripe Checkout / PaymentIntents, idempotent webhooks → `payment.*` events.
- Automatic partial refunds on late cancel, rain-out credit ledger, promo codes.
- **Exit:** all policy paths pass against Stripe test mode.

### M7 — Notifications (week 13)
- Email (Resend/Postmark) + SMS (Twilio): confirmation, 24h/2h reminders (Cloud Tasks),
  post-session rebook link. Start Twilio 10DLC registration during M0.
- **Exit:** a booking runs end-to-end with zero manual steps.

### M8 — Payouts, reviews, admin, retention (weeks 14+)
- Stripe Connect Express payouts on completion, two-way reviews, admin dashboard.
- Passes & subscriptions (Stripe Billing), referrals, production hardening
  (load tests, Cloud Armor, backups).
