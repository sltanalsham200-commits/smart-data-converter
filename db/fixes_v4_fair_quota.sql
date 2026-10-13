-- ============================================================
-- Tools Forge — Fair quota: deny-before-increment
-- v4.1: Rejected requests (429) no longer consume the quota.
-- RPC name unchanged → no Python changes needed.
-- ============================================================

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
BEGIN
    -- 1. Lookup + Lock (atomic)
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
        RETURN QUERY SELECT FALSE, FALSE, 0, 0, 0, NULL::UUID, NULL::UUID;
        RETURN;
    END IF;

    -- 2. Compute current monthly usage (BEFORE increment)
    SELECT COALESCE(SUM(request_count), 0)::INT
    INTO v_current_monthly
    FROM public.usage_daily
    WHERE subscriber_id = v_subscriber_id
      AND date >= date_trunc('month', CURRENT_DATE)::date;

    -- 3. Deny BEFORE increment (fair: rejected requests don't count)
    IF v_current_monthly >= v_max THEN
        RETURN QUERY SELECT TRUE, FALSE, v_current_monthly, v_max,
                            v_rate_limit, v_api_key_id, v_subscriber_id;
        RETURN;
    END IF;

    -- 4. Increment + record last_used_at
    UPDATE public.api_keys SET last_used_at = NOW() WHERE id = v_api_key_id;

    INSERT INTO public.usage_daily
        (api_key_id, subscriber_id, tool_name, date, request_count)
    VALUES (v_api_key_id, v_subscriber_id, p_tool, CURRENT_DATE, 1)
    ON CONFLICT (api_key_id, date, tool_name)
    DO UPDATE SET
        request_count = public.usage_daily.request_count + 1,
        updated_at = NOW();

    -- 5. Return success
    RETURN QUERY SELECT TRUE, TRUE, v_current_monthly + 1, v_max,
                        v_rate_limit, v_api_key_id, v_subscriber_id;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.verify_and_increment(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.verify_and_increment(TEXT, TEXT) TO service_role;

COMMENT ON FUNCTION public.verify_and_increment IS
'v4.1: Fair quota — deny-before-increment. Rejected requests do not consume quota.';
