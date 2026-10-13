-- ============================================================
-- Tools Forge — Fix: add missing updated_at columns
-- Reason: api_keys and subscriptions have BEFORE UPDATE triggers
--         that set NEW.updated_at, but the column was missing.
--         This caused ALL updates to fail silently.
-- ============================================================

BEGIN;

-- 1. Add updated_at to api_keys
ALTER TABLE public.api_keys
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- 2. Add updated_at to subscriptions
ALTER TABLE public.subscriptions
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

COMMIT;
