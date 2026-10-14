-- Tools Forge v2.2 — Payment infrastructure
BEGIN;

CREATE TABLE IF NOT EXISTS public.payment_intents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscriber_id       UUID NOT NULL REFERENCES public.subscribers(id) ON DELETE CASCADE,
    plan_id             UUID NOT NULL REFERENCES public.plans(id) ON DELETE RESTRICT,
    billing_period      TEXT NOT NULL CHECK (billing_period IN ('monthly','yearly')),
    amount_usd          NUMERIC(10,2) NOT NULL CHECK (amount_usd > 0),
    currency            TEXT NOT NULL DEFAULT 'USDT',
    network             TEXT,
    provider            TEXT NOT NULL,
    provider_invoice_id TEXT UNIQUE,
    payment_address     TEXT,
    pay_url             TEXT,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','seen','confirming','confirmed','failed','expired','cancelled')),
    payment_id          UUID REFERENCES public.payments(id) ON DELETE SET NULL,
    raw_provider        JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMPTZ,
    confirmed_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_payment_intents_subscriber
    ON public.payment_intents (subscriber_id, status);
CREATE INDEX IF NOT EXISTS idx_payment_intents_provider_invoice
    ON public.payment_intents (provider_invoice_id);
CREATE INDEX IF NOT EXISTS idx_payment_intents_active
    ON public.payment_intents (status, expires_at)
    WHERE status IN ('pending','seen','confirming');

ALTER TABLE public.payment_intents ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.webhook_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider        TEXT NOT NULL,
    event_id        TEXT,
    event_type      TEXT,
    payload_hash    TEXT NOT NULL,
    payload         JSONB,
    processed       BOOLEAN NOT NULL DEFAULT FALSE,
    processed_at    TIMESTAMPTZ,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_webhook_events_provider_event
    ON public.webhook_events (provider, event_id)
    WHERE event_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_webhook_events_provider_hash
    ON public.webhook_events (provider, payload_hash);
CREATE INDEX IF NOT EXISTS idx_webhook_events_processed
    ON public.webhook_events (provider, processed, created_at);

ALTER TABLE public.webhook_events ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION public.update_payment_intents_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS update_payment_intents_updated_at ON public.payment_intents;
CREATE TRIGGER update_payment_intents_updated_at
    BEFORE UPDATE ON public.payment_intents
    FOR EACH ROW
    EXECUTE FUNCTION public.update_payment_intents_updated_at();

GRANT ALL ON public.payment_intents TO service_role;
GRANT ALL ON public.webhook_events TO service_role;

COMMIT;
