-- ============================================================
-- Tools Forge — Supabase Fixes v2
-- Adds: updated_at triggers + atomic usage RPC
-- ============================================================

-- 1. Function to auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 2. Apply trigger to all tables with updated_at
DROP TRIGGER IF EXISTS update_subscribers_updated_at ON subscribers;
CREATE TRIGGER update_subscribers_updated_at
  BEFORE UPDATE ON subscribers
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_plans_updated_at ON plans;
CREATE TRIGGER update_plans_updated_at
  BEFORE UPDATE ON plans
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_subscriptions_updated_at ON subscriptions;
CREATE TRIGGER update_subscriptions_updated_at
  BEFORE UPDATE ON subscriptions
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_api_keys_updated_at ON api_keys;
CREATE TRIGGER update_api_keys_updated_at
  BEFORE UPDATE ON api_keys
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- 3. COMMENT on allowed_tools
COMMENT ON COLUMN plans.allowed_tools IS 
  'JSON array. Use ["all"] for all tools, or specific list of tool names.';

-- 4. Atomic usage increment RPC
--    Returns: { allowed: bool, current_usage: int, max_requests: int }
CREATE OR REPLACE FUNCTION increment_usage(
  p_api_key_id UUID,
  p_tool TEXT
)
RETURNS TABLE(allowed BOOLEAN, current_usage INT, max_requests INT) AS $$
DECLARE
  v_subscriber_id UUID;
  v_max INT;
  v_current INT;
BEGIN
  -- Get subscriber + plan limit
  SELECT ak.subscriber_id,
         p.max_requests
  INTO v_subscriber_id, v_max
  FROM api_keys ak
  JOIN subscriptions s ON s.subscriber_id = ak.subscriber_id
  JOIN plans p ON p.id = s.plan_id
  WHERE ak.id = p_api_key_id
    AND ak.status = 'active'
    AND s.status = 'active'
    AND s.expires_at > NOW()
  LIMIT 1;

  IF v_subscriber_id IS NULL THEN
    RETURN QUERY SELECT FALSE, 0, 0;
    RETURN;
  END IF;

  -- Upsert today's usage
  INSERT INTO usage_daily (api_key_id, subscriber_id, tool_name, date, request_count)
  VALUES (p_api_key_id, v_subscriber_id, p_tool, CURRENT_DATE, 1)
  ON CONFLICT (api_key_id, date, tool_name)
  DO UPDATE SET request_count = usage_daily.request_count + 1
  RETURNING usage_daily.request_count INTO v_current;

  -- Check quota
  IF v_current > v_max THEN
    RETURN QUERY SELECT FALSE, v_current, v_max;
  ELSE
    RETURN QUERY SELECT TRUE, v_current, v_max;
  END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION increment_usage IS 
  'Atomic quota check + increment. Returns (allowed, current, max).';

-- ============================================================
-- END
-- ============================================================
