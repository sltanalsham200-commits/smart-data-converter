-- Tools Forge v2.5 — Multi-provider / multi-network support
BEGIN;

-- 1. Expand currency list in payments
ALTER TABLE public.payments DROP CONSTRAINT IF EXISTS payments_currency_check;
ALTER TABLE public.payments ADD CONSTRAINT payments_currency_check
    CHECK (currency IN ('USDT','USDC','BTC','ETH','SOL','USD'));

-- 2. Expand network list in payments
ALTER TABLE public.payments DROP CONSTRAINT IF EXISTS payments_network_check;
ALTER TABLE public.payments ADD CONSTRAINT payments_network_check
    CHECK (
        network IS NULL OR
        network IN ('TRC20','BEP20','ERC20','SOL','BTC','POLYGON','MAINNET')
    );

-- 3. Add provider tracking fields to payment_intents
ALTER TABLE public.payment_intents
    ADD COLUMN IF NOT EXISTS provider_currency TEXT,
    ADD COLUMN IF NOT EXISTS provider_network TEXT,
    ADD COLUMN IF NOT EXISTS provider_payment_method_id TEXT,
    ADD COLUMN IF NOT EXISTS redirect_url TEXT;

-- 4. Update default currency (USDT remains)
-- No change needed

COMMIT;
