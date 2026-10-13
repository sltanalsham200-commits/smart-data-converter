-- Tools Forge — Rollback (Emergency)
-- Drops all 8 tables in correct order (FK dependencies)

DROP TABLE IF EXISTS public.system_heartbeat CASCADE;
DROP TABLE IF EXISTS public.visits CASCADE;
DROP TABLE IF EXISTS public.payments CASCADE;
DROP TABLE IF EXISTS public.usage_daily CASCADE;
DROP TABLE IF EXISTS public.api_keys CASCADE;
DROP TABLE IF EXISTS public.subscriptions CASCADE;
DROP TABLE IF EXISTS public.subscribers CASCADE;
DROP TABLE IF EXISTS public.plans CASCADE;
