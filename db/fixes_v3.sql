-- ============================================================
-- Tools Forge — Security Fixes v3
-- Created: 2026-10-13
-- Purpose:
--   1. Revoke dangerous privileges from anon/authenticated
--   2. Revoke EXECUTE from PUBLIC on user functions
--   3. Prevent multiple active subscriptions per subscriber
--   4. Drop redundant index
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- FIX 1: Revoke ALL from anon + authenticated on existing objects
-- ------------------------------------------------------------
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated;

-- ------------------------------------------------------------
-- FIX 2: Revoke EXECUTE from PUBLIC on user-defined functions
-- (rls_auto_enable is Supabase internal — leave it alone)
-- ------------------------------------------------------------
REVOKE EXECUTE ON FUNCTION increment_usage(UUID, TEXT) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION update_updated_at_column() FROM PUBLIC;

GRANT EXECUTE ON FUNCTION increment_usage(UUID, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION update_updated_at_column() TO service_role;

-- ------------------------------------------------------------
-- FIX 3: One active subscription per subscriber
-- ------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_subscription_per_subscriber
ON subscriptions (subscriber_id)
WHERE status = 'active';

-- ------------------------------------------------------------
-- FIX 4: Drop redundant index (kept by UNIQUE constraint)
-- ------------------------------------------------------------
DROP INDEX IF EXISTS public.idx_api_keys_hash;

-- ------------------------------------------------------------
-- FIX 5: Future-proof — revoke defaults
-- ------------------------------------------------------------
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL ON SEQUENCES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL ON FUNCTIONS FROM anon, authenticated;

COMMIT;
