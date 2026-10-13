-- ============================================================
-- Tools Forge — Keepalive infrastructure
-- Purpose: prevent Supabase Free auto-pause (7-day inactivity)
-- ============================================================

CREATE TABLE IF NOT EXISTS public.private_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.private_config ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.private_config FROM PUBLIC;
REVOKE ALL ON public.private_config FROM anon;
REVOKE ALL ON public.private_config FROM authenticated;

DROP FUNCTION IF EXISTS public.keepalive_ping(TEXT);

CREATE FUNCTION public.keepalive_ping(p_secret TEXT)
RETURNS TABLE(ok BOOLEAN, checked_at TIMESTAMPTZ)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_expected_hash TEXT;
    v_given_hash TEXT;
BEGIN
    IF p_secret IS NULL OR length(p_secret) < 32 THEN
        RETURN QUERY SELECT FALSE, NOW();
        RETURN;
    END IF;

    SELECT value INTO v_expected_hash
    FROM public.private_config WHERE key = 'keepalive_secret_hash';

    IF v_expected_hash IS NULL THEN
        RETURN QUERY SELECT FALSE, NOW();
        RETURN;
    END IF;

    v_given_hash := encode(sha256(p_secret::bytea), 'hex');

    IF v_given_hash != v_expected_hash THEN
        RETURN QUERY SELECT FALSE, NOW();
        RETURN;
    END IF;

    INSERT INTO public.system_heartbeat (check_type, status, response_time_ms)
    VALUES ('supabase', 'ok', 0);

    RETURN QUERY SELECT TRUE, NOW();
END;
$$;

REVOKE EXECUTE ON FUNCTION public.keepalive_ping(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keepalive_ping(TEXT) TO anon;

COMMENT ON FUNCTION public.keepalive_ping IS
'Keepalive endpoint for Cloudflare Worker. Verifies secret, logs heartbeat.';
