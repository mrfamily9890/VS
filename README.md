# VahanSync

VahanSync is an India-focused, multi-tenant fleet operations ERP for operators who need one system of record for vehicles, components, workshop inventory, maintenance, costs, and regulatory compliance.

## Run locally

Install the web dependencies:

```bash
npm install
npm run dev
```

In a second terminal, create the API environment once and start the backend:

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
npm run migrate
npm run api
```

The seeded development account is `admin@example.com` / `ChangeMe!123`. Replace these values with `VAHANA_SEED_ADMIN_EMAIL` and `VAHANA_SEED_ADMIN_PASSWORD` before sharing an environment.

Open the local Vite URL shown in the terminal. The production web build and API tests can be verified with:

```bash
npm run build
npm run test:api
```

## Production foundation

The browser is now a client of the Vahana API. Local development uses SQLite, while production is designed for PostgreSQL through `VAHANA_DATABASE_URL`.

The first production slice includes:

- Multi-tenant organizations and organization-scoped vehicle queries
- JWT authentication with password hashing and role-ready memberships
- Vehicle register API with duplicate registration protection
- Audit event creation for vehicle mutations
- API-backed fleet dashboard and add-vehicle workflow
- Health endpoint, request IDs, CORS configuration, and automated API coverage

The current operations slice also includes:

- Vehicle component register, preventive maintenance plans, and work-order status updates
- Workshop parts catalogue, stock locations, receipt/issue movements, reorder thresholds, and transaction history
- Compliance document register with vehicle linkage and expired-document status calculation
- Organization-scoped expense ledger with live costs and finance dashboard views
- Role checks for operational mutations and runtime rejection of development secrets in staging/production
- Alembic baseline migrations for controlled schema rollout
- Vendor register, purchase orders, line-level totals, procurement status transitions, and audit events
- Document update endpoint and unified alerts for expiring compliance records and low stock
- Authenticated compliance-document file upload/download with checksums and configurable local storage
- Durable, idempotent operational notifications for expiry and reorder events
- Fuel and toll/FASTag transaction ledgers with INR paise precision
- GST-ready expense fields, approval transitions, and monthly finance summaries
- Telematics device registration, validated readings, last-seen state, and latest-vehicle telemetry
- Configurable identity-provider metadata and token-version session revocation
- Structured request timing logs, storage-provider boundaries, health detail, and recovery runbook
- Six-role organisation model with role-aware navigation and workspace messaging for owner, fleet manager, inventory manager, driver, mechanic/technician, and accountant
- User membership management for owners
- Notification preferences and queued delivery records for in-app, email, SMS, WhatsApp, and push channels
- Subscription catalogue and organisation plan state with Starter, Growth, Scale, and Enterprise tiers

## Recommended subscription model

VahanSync is priced by managed fleet size rather than by every operational action:

| Plan | Vehicle band | Included vehicles | Platform fee | Additional vehicle |
| --- | ---: | ---: | ---: | ---: |
| Starter | 1–10 vehicles | 3 | ₹2,999/month | ₹500/month |
| Growth | 11–49 vehicles | 15 | ₹9,999/month | ₹450/month |
| Scale | 50–99 vehicles | 50 | ₹24,999/month | ₹350/month |
| Enterprise | 100+ vehicles | 100 | Custom | ₹300/month |

Every organisation starts with a 14-day free trial, and every plan supports unlimited member onboarding. The vehicle-band rules prevent selecting a smaller tier than the active fleet. The subscription view calculates overage vehicles and an estimated monthly subtotal. Razorpay checkout is now available through the backend subscription endpoint and verified webhooks; recurring billing becomes active after Razorpay plan IDs and credentials are configured.

## Organisation access model

The first person who submits `/signup` creates the organisation and becomes its owner. Owners create durable invitations from the workspace; invitees activate their account and set their own password through the single-use invitation link.

Each user has exactly one explicit role: `owner`, `fleet_manager`, `inventory_manager`, `driver`, `technician`, or `accountant`. Email addresses are globally unique, invitations cannot grant owner access, and only owners can invite or revoke members. Operational roles are intentionally shareable across a team; “no duplicates” means no duplicate identity or simultaneous invitation, not one person per operational function.

The API remains the security boundary. Drivers only receive vehicles assigned to their user ID, technicians only receive assigned work orders, and every query remains organization-scoped. Mobile numbers are normalized to international format when supplied; SMS and WhatsApp deliveries remain explicitly queued until server-side provider credentials, sender configuration, templates, and applicable consent are configured.

### Supabase and Razorpay deployment

Supabase is the target production platform and the production authentication authority:

```text
VAHANA_DATABASE_URL=postgresql://...
VAHANA_AUTH_PROVIDER=supabase
VAHANA_SUPABASE_URL=https://<project>.supabase.co
VAHANA_SUPABASE_ANON_KEY=<browser-safe-anon-key>
VAHANA_SUPABASE_JWT_SECRET=<server-only-jwt-secret>
# Or use the project's asymmetric signing keys:
# VAHANA_SUPABASE_JWKS_URL=https://<project>.supabase.co/auth/v1/.well-known/jwks.json
VAHANA_STORAGE_BACKEND=supabase
VAHANA_SUPABASE_SERVICE_ROLE_KEY=<server-only-service-role-key>
VAHANA_SUPABASE_STORAGE_BUCKET=documents
```

Run `npm run migrate` against the Supabase database before starting the API. The service-role key is backend-only; the browser receives only the anon key. Organisation signup, invitation acceptance, and owner-created users provision their accounts in Supabase Auth; API users are then linked by their Auth subject. The local password endpoint remains available only for development.

Configure Razorpay with `VAHANA_RAZORPAY_KEY_ID`, `VAHANA_RAZORPAY_KEY_SECRET`, `VAHANA_RAZORPAY_WEBHOOK_SECRET`, and one Razorpay plan ID per paid tier (`VAHANA_RAZORPAY_PLAN_STARTER`, `VAHANA_RAZORPAY_PLAN_GROWTH`, `VAHANA_RAZORPAY_PLAN_SCALE`). Point the Razorpay webhook to `/api/v1/webhooks/razorpay`. Until these values are configured, checkout intentionally returns a configuration error rather than pretending payments are live.

Configure mobile delivery providers only on the API:

```text
VAHANA_SMS_PROVIDER=...
VAHANA_SMS_API_URL=...
VAHANA_SMS_AUTH_TOKEN=...
VAHANA_SMS_ACCOUNT_SID=...
VAHANA_SMS_FROM_NUMBER=...
VAHANA_WHATSAPP_PROVIDER=...
VAHANA_WHATSAPP_API_URL=...
VAHANA_WHATSAPP_AUTH_TOKEN=...
VAHANA_WHATSAPP_ACCOUNT_SID=...
VAHANA_WHATSAPP_FROM_NUMBER=...
VAHANA_WHATSAPP_SENDER_ID=...
VAHANA_WHATSAPP_TEMPLATE_ID=...
```

For Twilio, set `VAHANA_SMS_PROVIDER=twilio` and/or
`VAHANA_WHATSAPP_PROVIDER=twilio`. The API derives the Twilio Messages URL
when `VAHANA_*_API_URL` is omitted, uses the account SID and auth token only
on the server, and sends WhatsApp messages with the `whatsapp:` address
prefix. Configure an approved WhatsApp sender/template and recipient opt-in
before enabling production delivery.

For non-development environments, set a unique `VAHANA_JWT_SECRET` and a non-default `VAHANA_SEED_ADMIN_PASSWORD`. Set `VAHANA_STORAGE_PATH` to a persistent volume or select an approved object-storage adapter with `VAHANA_STORAGE_BACKEND` and its provider settings. The current local bootstrap uses `Base.metadata.create_all` for development and tests; production rollout should run a reviewed schema migration before starting the API.

See [ARCHITECTURE.md](ARCHITECTURE.md) for domain boundaries and the enterprise delivery sequence.
See [OPERATIONS.md](OPERATIONS.md) for deployment, observability, backup, and recovery procedures.
