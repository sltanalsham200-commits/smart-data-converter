-- ============================================================
-- Tools Forge — Database Schema v2
-- Created: 2026-10-13
-- Target: Supabase PostgreSQL 17.11 (Frankfurt)
-- Note: Replaces v1 schema (with better structure)
-- ============================================================

-- ============================================================
-- Table 1: plans
-- ============================================================
CREATE TABLE public.plans (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name                TEXT NOT NULL,
  display_name        TEXT NOT NULL,
  price_usd           NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (price_usd >= 0),
  max_requests        INTEGER NOT NULL CHECK (max_requests > 0),
  billing_period      TEXT NOT NULL CHECK (billing_period IN ('monthly','yearly')),
  rate_limit_per_min  INTEGER NOT NULL CHECK (rate_limit_per_min > 0),
  allowed_tools       JSONB NOT NULL DEFAULT '["all"]'::jsonb,
  is_active           BOOLEAN NOT NULL DEFAULT TRUE,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (name, billing_period)
);
ALTER TABLE public.plans ENABLE ROW LEVEL SECURITY;
CREATE INDEX idx_plans_name ON public.plans(name);
CREATE INDEX idx_plans_active ON public.plans(is_active) WHERE is_active = TRUE;

-- ============================================================
-- Table 2: subscribers
-- ============================================================
CREATE TABLE public.subscribers (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email           TEXT NOT NULL UNIQUE,
  status          TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active','suspended','deleted')),
  auth_user_id    UUID,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.subscribers ENABLE ROW LEVEL SECURITY;
CREATE INDEX idx_subscribers_email ON public.subscribers(email);
CREATE INDEX idx_subscribers_status ON public.subscribers(status);

-- ============================================================
-- Table 3: subscriptions
-- ============================================================
CREATE TABLE public.subscriptions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subscriber_id   UUID NOT NULL REFERENCES public.subscribers(id) ON DELETE CASCADE,
  plan_id         UUID NOT NULL REFERENCES public.plans(id) ON DELETE RESTRICT,
  status          TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active','expired','cancelled','pending')),
  started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at      TIMESTAMPTZ,
  auto_renew      BOOLEAN NOT NULL DEFAULT FALSE,
  payment_id      UUID,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;
CREATE INDEX idx_subscriptions_subscriber ON public.subscriptions(subscriber_id);
CREATE INDEX idx_subscriptions_status ON public.subscriptions(status);
CREATE INDEX idx_subscriptions_expires ON public.subscriptions(expires_at);

-- ============================================================
-- Table 4: api_keys (SHA-256 hash only)
-- ============================================================
CREATE TABLE public.api_keys (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subscriber_id   UUID NOT NULL REFERENCES public.subscribers(id) ON DELETE CASCADE,
  key_hash        TEXT NOT NULL UNIQUE,
  key_prefix      TEXT NOT NULL,
  name            TEXT,
  status          TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active','revoked')),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_used_at    TIMESTAMPTZ,
  revoked_at      TIMESTAMPTZ
);
ALTER TABLE public.api_keys ENABLE ROW LEVEL SECURITY;
CREATE INDEX idx_api_keys_hash ON public.api_keys(key_hash);
CREATE INDEX idx_api_keys_subscriber ON public.api_keys(subscriber_id);
CREATE INDEX idx_api_keys_status ON public.api_keys(status);

-- ============================================================
-- Table 5: usage_daily (aggregated per key+date+tool)
-- ============================================================
CREATE TABLE public.usage_daily (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  api_key_id      UUID NOT NULL REFERENCES public.api_keys(id) ON DELETE CASCADE,
  subscriber_id   UUID NOT NULL REFERENCES public.subscribers(id) ON DELETE CASCADE,
  tool_name       TEXT NOT NULL,
  date            DATE NOT NULL DEFAULT CURRENT_DATE,
  request_count   INTEGER NOT NULL DEFAULT 0 CHECK (request_count >= 0),
  success_count   INTEGER NOT NULL DEFAULT 0 CHECK (success_count >= 0),
  error_count     INTEGER NOT NULL DEFAULT 0 CHECK (error_count >= 0),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (api_key_id, date, tool_name)
);
ALTER TABLE public.usage_daily ENABLE ROW LEVEL SECURITY;
CREATE INDEX idx_usage_daily_key_date ON public.usage_daily(api_key_id, date);
CREATE INDEX idx_usage_daily_subscriber_date ON public.usage_daily(subscriber_id, date);
CREATE INDEX idx_usage_daily_date ON public.usage_daily(date);

-- ============================================================
-- Table 6: payments
-- ============================================================
CREATE TABLE public.payments (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subscriber_id   UUID NOT NULL REFERENCES public.subscribers(id) ON DELETE RESTRICT,
  amount          NUMERIC(10,2) NOT NULL CHECK (amount > 0),
  currency        TEXT NOT NULL DEFAULT 'USD'
                  CHECK (currency IN ('USD','USDT')),
  network         TEXT CHECK (network IN ('TRC20','ERC20') OR network IS NULL),
  status          TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','confirmed','rejected','refunded')),
  reference_id    TEXT UNIQUE,
  audit_data      JSONB,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  confirmed_at    TIMESTAMPTZ
);
ALTER TABLE public.payments ENABLE ROW LEVEL SECURITY;
CREATE INDEX idx_payments_subscriber ON public.payments(subscriber_id);
CREATE INDEX idx_payments_status ON public.payments(status);
CREATE INDEX idx_payments_reference ON public.payments(reference_id);

-- ============================================================
-- Table 7: visits (aggregated daily)
-- ============================================================
CREATE TABLE public.visits (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  date            DATE NOT NULL DEFAULT CURRENT_DATE,
  page            TEXT NOT NULL,
  country         TEXT,
  referrer        TEXT,
  visitor_hash    TEXT,
  count           INTEGER NOT NULL DEFAULT 1 CHECK (count >= 0),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (date, page, referrer, country)
);
ALTER TABLE public.visits ENABLE ROW LEVEL SECURITY;
CREATE INDEX idx_visits_date ON public.visits(date);
CREATE INDEX idx_visits_page ON public.visits(page);

-- ============================================================
-- Table 8: system_heartbeat
-- ============================================================
CREATE TABLE public.system_heartbeat (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  check_type        TEXT NOT NULL
                    CHECK (check_type IN ('supabase','render','cloudflare')),
  status            TEXT NOT NULL CHECK (status IN ('ok','fail')),
  response_time_ms  INTEGER CHECK (response_time_ms >= 0 OR response_time_ms IS NULL),
  error_code        TEXT,
  checked_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.system_heartbeat ENABLE ROW LEVEL SECURITY;
CREATE INDEX idx_heartbeat_type ON public.system_heartbeat(check_type);
CREATE INDEX idx_heartbeat_checked_at ON public.system_heartbeat(checked_at);
CREATE INDEX idx_heartbeat_status ON public.system_heartbeat(status);

-- ============================================================
-- END OF SCHEMA v2
-- ============================================================
