-- Tools Forge v2.6 — Centralized rate limiting
BEGIN;

CREATE TABLE IF NOT EXISTS public.rate_limit_events (
  id BIGSERIAL PRIMARY KEY,
  api_key_id UUID NOT NULL REFERENCES public.api_keys(id) ON DELETE CASCADE,
  request_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rate_limit_key_time
  ON public.rate_limit_events (api_key_id, request_at DESC);
ALTER TABLE public.rate_limit_events ENABLE ROW LEVEL SECURITY;
GRANT ALL ON public.rate_limit_events TO service_role;

DROP FUNCTION IF EXISTS public.verify_and_increment(TEXT, TEXT);

CREATE FUNCTION public.verify_and_increment(
    p_key_hash TEXT,
    p_tool TEXT
)
RETURNS TABLE(
    key_valid BOOLEAN,
    quota_allowed BOOLEAN,
    current_usage INT,
    max_requests INT,
    rate_limit_per_min INT,
    rate_allowed BOOLEAN,
    rate_current INT,
    out_key_id UUID,
    out_subscriber_id UUID
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_api_key_id UUID;
    v_subscriber_id UUID;
    v_max INT;
    v_rate_limit INT;
    v_current_monthly INT;
    v_rate_count INT;
BEGIN
    SELECT ak.id, ak.subscriber_id, p.max_requests, p.rate_limit_per_min
    INTO v_api_key_id, v_subscriber_id, v_max, v_rate_limit
    FROM public.api_keys ak
    JOIN public.subscribers sb ON sb.id = ak.subscriber_id
    JOIN public.subscriptions s ON s.subscriber_id = ak.subscriber_id
    JOIN public.plans p ON p.id = s.plan_id
    WHERE ak.key_hash = p_key_hash
      AND ak.status = 'active'
      AND sb.status = 'active'
      AND s.status = 'active'
      AND s.expires_at > NOW()
      AND p.is_active = TRUE
      AND (p.allowed_tools @> '["all"]'::jsonb
           OR p.allowed_tools @> to_jsonb(ARRAY[p_tool]))
    LIMIT 1
    FOR UPDATE OF ak, sb;

    IF v_api_key_id IS NULL THEN
        RETURN QUERY SELECT FALSE, FALSE, 0, 0, 0, FALSE, 0, NULL::UUID, NULL::UUID;
        RETURN;
    END IF;

    DELETE FROM public.rate_limit_events
    WHERE api_key_id = v_api_key_id
      AND request_at < NOW() - INTERVAL '60 seconds';

    SELECT COUNT(*)::INT INTO v_rate_count
    FROM public.rate_limit_events
    WHERE api_key_id = v_api_key_id
      AND request_at >= NOW() - INTERVAL '60 seconds';

    SELECT COALESCE(SUM(request_count), 0)::INT
    INTO v_current_monthly
    FROM public.usage_daily
    WHERE subscriber_id = v_subscriber_id
      AND date >= date_trunc('month', CURRENT_DATE)::date;

    IF v_rate_count >= v_rate_limit THEN
        RETURN QUERY SELECT TRUE,
                            (v_current_monthly < v_max),
                            v_current_monthly,
                            v_max,
                            v_rate_limit,
                            FALSE,
                            v_rate_count,
                            v_api_key_id,
                            v_subscriber_id;
        RETURN;
    END IF;

    INSERT INTO public.rate_limit_events (api_key_id) VALUES (v_api_key_id);

    IF v_current_monthly >= v_max THEN
        RETURN QUERY SELECT TRUE, FALSE, v_current_monthly,
                            v_max, v_rate_limit, TRUE, v_rate_count + 1,
                            v_api_key_id, v_subscriber_id;
        RETURN;
    END IF;

    UPDATE public.api_keys SET last_used_at = NOW() WHERE id = v_api_key_id;

    INSERT INTO public.usage_daily
        (api_key_id, subscriber_id, tool_name, date, request_count)
    VALUES (v_api_key_id, v_subscriber_id, p_tool, CURRENT_DATE, 1)
    ON CONFLICT (api_key_id, date, tool_name)
    DO UPDATE SET
        request_count = public.usage_daily.request_count + 1,
        updated_at = NOW();

    RETURN QUERY SELECT TRUE, TRUE, v_current_monthly + 1, v_max, v_rate_limit,
                        TRUE, v_rate_count + 1, v_api_key_id, v_subscriber_id;
END;
$$;

GRANT EXECUTE ON FUNCTION public.verify_and_increment(TEXT, TEXT) TO service_role;

COMMIT;
