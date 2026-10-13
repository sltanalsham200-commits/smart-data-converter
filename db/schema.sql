-- Tools Forge — Database Schema
-- Created: 2026-10-12
-- Target: Supabase PostgreSQL 17.11 (Frankfurt)

CREATE TABLE IF NOT EXISTS public.plans (
  id SERIAL PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  daily_limit INTEGER NOT NULL,
  monthly_price_usd NUMERIC(10,2) NOT NULL DEFAULT 0,
  features JSONB NOT NULL DEFAULT '{}'::jsonb,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.plans ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.subscribers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  name TEXT,
  telegram_chat_id TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.subscribers ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS idx_subscribers_email ON public.subscribers(email);

CREATE TABLE IF NOT EXISTS public.subscriptions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subscriber_id UUID NOT NULL REFERENCES public.subscribers(id) ON DELETE CASCADE,
  plan_id INTEGER NOT NULL REFERENCES public.plans(id),
  status TEXT NOT NULL DEFAULT 'active',
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS idx_subscriptions_subscriber ON public.subscriptions(subscriber_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON public.subscriptions(status);

CREATE TABLE IF NOT EXISTS public.api_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subscriber_id UUID NOT NULL REFERENCES public.subscribers(id) ON DELETE CASCADE,
  key_hash TEXT UNIQUE NOT NULL,
  key_prefix TEXT NOT NULL,
  label TEXT,
  last_used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  revoked_at TIMESTAMPTZ
);
ALTER TABLE public.api_keys ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON public.api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_subscriber ON public.api_keys(subscriber_id);

CREATE TABLE IF NOT EXISTS public.usage_daily (
  id BIGSERIAL PRIMARY KEY,
  api_key_id UUID NOT NULL REFERENCES public.api_keys(id) ON DELETE CASCADE,
  date DATE NOT NULL DEFAULT CURRENT_DATE,
  request_count INTEGER NOT NULL DEFAULT 0,
  bytes_in BIGINT NOT NULL DEFAULT 0,
  bytes_out BIGINT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(api_key_id, date)
);
ALTER TABLE public.usage_daily ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS idx_usage_daily_key_date ON public.usage_daily(api_key_id, date);

CREATE TABLE IF NOT EXISTS public.payments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subscriber_id UUID NOT NULL REFERENCES public.subscribers(id) ON DELETE RESTRICT,
  amount NUMERIC(12,2) NOT NULL,
  currency TEXT NOT NULL DEFAULT 'USDT',
  method TEXT NOT NULL,
  external_tx_id TEXT UNIQUE,
  status TEXT NOT NULL DEFAULT 'pending',
  raw_payload JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  confirmed_at TIMESTAMPTZ
);
ALTER TABLE public.payments ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS idx_payments_subscriber ON public.payments(subscriber_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON public.payments(status);

CREATE TABLE IF NOT EXISTS public.visits (
  id BIGSERIAL PRIMARY KEY,
  path TEXT NOT NULL,
  referrer TEXT,
  country TEXT,
  user_agent_hash TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.visits ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS idx_visits_created_at ON public.visits(created_at);

CREATE TABLE IF NOT EXISTS public.system_heartbeat (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL,
  status TEXT NOT NULL,
  response_ms INTEGER,
  note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.system_heartbeat ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS idx_heartbeat_created_at ON public.system_heartbeat(created_at);
