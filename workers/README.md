# Tools Forge - Cloudflare Workers

Source code for all Cloudflare Workers.

## Workers

### 1. convert/ - tools-forge-convert
Offloads CSV/HTML to JSON conversion from Render to Cloudflare edge.
Endpoint: tools-forge-convert.sltanalsham200.workers.dev
Auth: X-API-Key (legacy or tf_live_ via Supabase)
Secrets: SUPABASE_URL, SUPABASE_SERVICE_KEY, LEGACY_API_KEY

### 2. cron/ - tools-forge-cron
Hourly job for subscription expiry + cleanup.
Schedule: 0 * * * *
Secrets: API_BASE, CRON_SECRET, TELEGRAM_*

### 3. keepalive/ - tools-forge-db-keepalive
Prevents Supabase auto-pause (every 6 hours).
Schedule: 0 */6 * * *
Secrets: SUPABASE_URL, SUPABASE_ANON_KEY, KEEPALIVE_SECRET, TELEGRAM_*

## Deploy
From Ubuntu (via proot):
  cd workers/<name>
  wrangler deploy

## Notes
- All workers share the same Supabase project.
- Secrets stored in Cloudflare Worker secrets only.
