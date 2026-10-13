-- ============================================================
-- TEST: increment_usage RPC
-- Creates: subscriber + subscription + api_key (temporary)
-- Tests: quota check + atomic increment
-- CLEANS: everything at the end
-- ============================================================

BEGIN;

-- Variables
DO $$
DECLARE
  v_subscriber_id UUID;
  v_plan_id UUID;
  v_subscription_id UUID;
  v_api_key_id UUID;
  v_result RECORD;
  i INT;
BEGIN
  -- Get free plan
  SELECT id INTO v_plan_id FROM plans WHERE name = 'free' AND billing_period = 'monthly';
  RAISE NOTICE 'Plan ID: %', v_plan_id;

  -- Create test subscriber
  INSERT INTO subscribers (email, status)
  VALUES ('test@tools-forge.internal', 'active')
  RETURNING id INTO v_subscriber_id;
  RAISE NOTICE 'Subscriber ID: %', v_subscriber_id;

  -- Create subscription (30 days)
  INSERT INTO subscriptions (subscriber_id, plan_id, status, started_at, expires_at, auto_renew)
  VALUES (v_subscriber_id, v_plan_id, 'active', NOW(), NOW() + INTERVAL '30 days', false)
  RETURNING id INTO v_subscription_id;
  RAISE NOTICE 'Subscription ID: %', v_subscription_id;

  -- Create API key
  INSERT INTO api_keys (subscriber_id, key_hash, key_prefix, name, status)
  VALUES (v_subscriber_id, encode(sha256('test_key_123'::bytea), 'hex'), 'tf_live_', 'test', 'active')
  RETURNING id INTO v_api_key_id;
  RAISE NOTICE 'API Key ID: %', v_api_key_id;

  -- Test 1: First call should be allowed (1/500)
  SELECT * INTO v_result FROM increment_usage(v_api_key_id, 'smart-data-converter');
  RAISE NOTICE 'Call 1: allowed=%, current=%, max=%', v_result.allowed, v_result.current_usage, v_result.max_requests;
  IF v_result.allowed IS NOT TRUE OR v_result.current_usage != 1 THEN
    RAISE EXCEPTION 'TEST 1 FAILED';
  END IF;

  -- Test 2: 499 more calls (total 500)
  FOR i IN 1..499 LOOP
    SELECT * INTO v_result FROM increment_usage(v_api_key_id, 'smart-data-converter');
  END LOOP;
  RAISE NOTICE 'After 500 calls: current=%, max=%', v_result.current_usage, v_result.max_requests;
  IF v_result.current_usage != 500 THEN
    RAISE EXCEPTION 'TEST 2 FAILED: expected 500, got %', v_result.current_usage;
  END IF;
  IF v_result.allowed IS NOT TRUE THEN
    RAISE EXCEPTION 'TEST 2 FAILED: should still be allowed at 500';
  END IF;

  -- Test 3: Call 501 should be allowed=false
  SELECT * INTO v_result FROM increment_usage(v_api_key_id, 'smart-data-converter');
  RAISE NOTICE 'Call 501: allowed=%, current=%, max=%', v_result.allowed, v_result.current_usage, v_result.max_requests;
  IF v_result.allowed IS NOT FALSE THEN
    RAISE EXCEPTION 'TEST 3 FAILED: should be rejected at 501';
  END IF;

  -- Test 4: Verify usage_daily row
  IF (SELECT request_count FROM usage_daily WHERE api_key_id = v_api_key_id AND tool_name = 'smart-data-converter') != 501 THEN
    RAISE EXCEPTION 'TEST 4 FAILED: usage_daily should be 501';
  END IF;

  RAISE NOTICE '✅ ALL 4 TESTS PASSED';
END $$;

-- CLEANUP
ROLLBACK;

-- ============================================================
-- END
-- ============================================================
