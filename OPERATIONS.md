# Vahana operations runbook

## Production rollout

1. Create a Supabase project and private `documents` Storage bucket.
2. Set `VAHANA_ENVIRONMENT=production`, the Supabase PostgreSQL URL, `VAHANA_AUTH_PROVIDER=supabase`, `VAHANA_SUPABASE_JWT_SECRET`, and a non-default seed password.
3. Set `VAHANA_SUPABASE_SERVICE_ROLE_KEY` only in the API environment, never in Vite or browser configuration.
4. Set `VAHANA_CORS_ORIGINS` to the deployed web origin and `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` in the web build environment. The backend service-role key is required for provisioning Supabase Auth users during signup, invitation acceptance, and owner-created user flows; never expose it to the browser.
5. Run `npm run migrate` from the release artifact before starting Uvicorn.
6. Configure Razorpay plan IDs, the server-side key secret, and a webhook for `/api/v1/webhooks/razorpay`.
7. Configure SMS and WhatsApp provider credentials, sender IDs, approved templates, and recipient opt-in policy when mobile delivery is enabled. For Twilio, set the provider to `twilio` plus the account SID, auth token, and SMS/WhatsApp sender numbers; the API derives the Messages endpoint when no custom URL is provided. Keep all provider credentials in the API environment.
8. Start the API with a process supervisor and expose `/health` to the load balancer.

The default local storage adapter is intentionally explicit. Production should use `VAHANA_STORAGE_BACKEND=supabase` with a private bucket and the service-role key held only by the API.

## Backup and recovery

- Back up PostgreSQL with daily full backups and point-in-time recovery.
- Version document objects independently with retention and encryption enabled.
- Test a restore into an isolated database at least monthly.
- Restore the database first, then the document objects, then run `npm run migrate`.
- Verify `/health`, authentication, document downloads, and a tenant-scoped read before traffic is restored.
- Run `VAHANA_BACKUP_SOURCE_URL=... VAHANA_RESTORE_TARGET_URL=... python -m backend.app.backup_restore` against an isolated PostgreSQL target to verify both database and restore tooling. Set `VAHANA_BACKUP_FILE` to choose the temporary custom-format dump path.

## Observability

Every response includes `x-request-id`. API logs emit structured request completion fields: request ID, method, path, status, and duration. Forward these fields to the deployment log collector and alert on sustained 5xx responses, migration failures, database saturation, and storage errors.
