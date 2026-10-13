-- ============================================================
-- Tools Forge — increment_usage RPC v3
-- Fixes:
--   - Monthly quota (was: daily)
--   - Check subscribers.status
--   - Check plans.is_active
--   - Check plans.allowed_tools
--   - SET search_path (SECURITY DEFINER hardening)
-- ============================================================

CREATE OR REPLACE FUNCTION increment_usage(
    p_api_key_id UUID,
    p_tool TEXT
)
RETURNS TABLE(allowed BOOLEAN, current_usage INT, max_requests INT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_subscriber_id UUID;
    v_max INT;
    v_current_monthly INT;
BEGIN
    -- 1. Verify: key active + subscriber active + subscription active
    --          + not expired + plan active + tool allowed
    SELECT ak.subscriber_id, p.max_requests
    INTO v_subscriber_id, v_max
    FROM api_keys ak
    JOIN subscribers sub ON sub.id = ak.subscriber_id
    JOIN subscriptions s ON s.subscriber_id = ak.subscriber_id
    JOIN plans p ON p.id = s.plan_id
    WHERE ak.id = p_api_key_id
      AND ak.status = 'active'
      AND sub.status = 'active'
      AND s.status = 'active'
      AND s.expires_at > NOW()
      AND p.is_active = TRUE
      AND (p.allowed_tools @> '["all"]'::jsonb
           OR p.allowed_tools @> to_jsonb(ARRAY[p_tool]))
    LIMIT 1;

    IF v_subscriber_id IS NULL THEN
        RETURN QUERY SELECT FALSE, 0, 0;
        RETURN;
    END IF;

    -- 2. Upsert today's row (atomic increment for stats)
    INSERT INTO usage_daily (api_key_id, subscriber_id, tool_name, date, request_count)
    VALUES (p_api_key_id, v_subscriber_id, p_tool, CURRENT_DATE, 1)
    ON CONFLICT (api_key_id, date, tool_name)
    DO UPDATE SET
        request_count = usage_daily.request_count + 1,
        updated_at = NOW();

    -- 3. Compute monthly usage (from start of current month)
    SELECT COALESCE(SUM(request_count), 0)::INT
    INTO v_current_monthly
    FROM usage_daily
    WHERE api_key_id = p_api_key_id
      AND date >= date_trunc('month', CURRENT_DATE)::date;

    -- 4. Check quota
    IF v_current_monthly > v_max THEN
        RETURN QUERY SELECT FALSE, v_current_monthly, v_max;
    ELSE
        RETURN QUERY SELECT TRUE, v_current_monthly, v_max;
    END IF;
END;
$$;

-- Ensure service_role can execute, PUBLIC cannot
REVOKE EXECUTE ON FUNCTION increment_usage(UUID, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION increment_usage(UUID, TEXT) TO service_role;

COMMENT ON FUNCTION increment_usage IS
'Atomic monthly quota check + increment. Fixes v3: monthly SUM, subscribers.status, plans.is_active, allowed_tools.';
