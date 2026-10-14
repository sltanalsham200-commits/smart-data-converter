-- Tools Forge v2.4 — Cron infrastructure
BEGIN;

-- -------------------------------------------------------------
-- Table: cron_runs (audit of every cron tick)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.cron_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running','ok','error')),
    expired_count       INT NOT NULL DEFAULT 0,
    cleaned_webhooks    INT NOT NULL DEFAULT 0,
    error               TEXT,
    duration_ms         INT
);

CREATE INDEX IF NOT EXISTS idx_cron_runs_started
    ON public.cron_runs (started_at DESC);

ALTER TABLE public.cron_runs ENABLE ROW LEVEL SECURITY;

-- -------------------------------------------------------------
-- Table: notification_log (prevent duplicate notifications)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.notification_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscriber_id   UUID NOT NULL REFERENCES public.subscribers(id) ON DELETE CASCADE,
    type            TEXT NOT NULL,
    period_key      TEXT NOT NULL,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    channel         TEXT,
    details         JSONB,
    UNIQUE (subscriber_id, type, period_key)
);

CREATE INDEX IF NOT EXISTS idx_notification_log_subscriber
    ON public.notification_log (subscriber_id, sent_at DESC);

ALTER TABLE public.notification_log ENABLE ROW LEVEL SECURITY;

-- service_role only
GRANT ALL ON public.cron_runs TO service_role;
GRANT ALL ON public.notification_log TO service_role;

COMMIT;
