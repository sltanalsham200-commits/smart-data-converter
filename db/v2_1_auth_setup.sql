-- Tools Forge v2.1 — Auth Setup
BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint 
    WHERE conname = 'subscribers_auth_user_id_key'
  ) THEN
    ALTER TABLE public.subscribers 
      ADD CONSTRAINT subscribers_auth_user_id_key UNIQUE (auth_user_id);
  END IF;
END $$;

CREATE OR REPLACE FUNCTION public.handle_new_auth_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_subscriber_id UUID;
  v_free_plan_id UUID;
BEGIN
  SELECT id INTO v_subscriber_id
  FROM public.subscribers
  WHERE auth_user_id = NEW.id;

  IF v_subscriber_id IS NULL THEN
    INSERT INTO public.subscribers (auth_user_id, email, status)
    VALUES (NEW.id, COALESCE(NEW.email, ''), 'active')
    ON CONFLICT (email) DO UPDATE
      SET auth_user_id = EXCLUDED.auth_user_id,
          updated_at = NOW()
    RETURNING id INTO v_subscriber_id;
  END IF;

  IF EXISTS (
    SELECT 1 FROM public.subscriptions 
    WHERE subscriber_id = v_subscriber_id
  ) THEN
    RETURN NEW;
  END IF;

  SELECT id INTO v_free_plan_id
  FROM public.plans
  WHERE name = 'free' AND billing_period = 'monthly'
  LIMIT 1;

  IF v_free_plan_id IS NULL THEN
    RAISE WARNING 'Free plan not found';
    RETURN NEW;
  END IF;

  INSERT INTO public.subscriptions (
    subscriber_id, plan_id, status, started_at, expires_at, auto_renew
  ) VALUES (
    v_subscriber_id, v_free_plan_id, 'active', NOW(), NOW() + INTERVAL '100 years', FALSE
  );

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW
  EXECUTE FUNCTION public.handle_new_auth_user();

COMMIT;
