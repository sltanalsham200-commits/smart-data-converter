"""
Kazawallet payment provider.

⚠️ STATUS: SKELETON — awaiting merchant account + official API docs.

Reference (to be verified before production):
- Merchant: https://www.kazawallet.com/ar/merchant
- API docs: https://www.kazawallet.com/api-docs
- Terms:    https://www.kazawallet.com/terms-of-service

Before going live, MUST:
1. Read current official API docs (endpoints, request/response shapes,
   signature algorithm, webhook format).
2. Fill in the TODO sections below with verified values.
3. Test against sandbox or staging (if provided).
4. Test with a small real payment (user-approved).

Required env vars (when activated):
- KAZAWALLET_API_KEY       — merchant API key
- KAZAWALLET_API_SECRET    — merchant API secret (never logged)
- KAZAWALLET_WEBHOOK_SECRET — webhook signing secret
- KAZAWALLET_BASE_URL      — e.g. https://api.kazawallet.com
"""
import hashlib
import hmac
import logging
import os
from typing import Optional

from payment_provider import PaymentProvider

logger = logging.getLogger("payment_kazawallet")


class KazawalletNotConfigured(RuntimeError):
    pass


class KazawalletProvider(PaymentProvider):
    name = "kazawallet"

    def __init__(self):
        self.api_key = os.environ.get("KAZAWALLET_API_KEY", "").strip()
        self.api_secret = os.environ.get("KAZAWALLET_API_SECRET", "").strip()
        self.webhook_secret = os.environ.get("KAZAWALLET_WEBHOOK_SECRET", "").strip()
        self.base_url = os.environ.get("KAZAWALLET_BASE_URL", "").strip().rstrip("/")

        missing = [
            name for name, val in [
                ("KAZAWALLET_API_KEY", self.api_key),
                ("KAZAWALLET_API_SECRET", self.api_secret),
                ("KAZAWALLET_WEBHOOK_SECRET", self.webhook_secret),
                ("KAZAWALLET_BASE_URL", self.base_url),
            ] if not val
        ]
        if missing:
            raise KazawalletNotConfigured(
                "Missing env vars: " + ", ".join(missing)
            )

    # ------------------------------------------------------------------
    # create_payment
    # ------------------------------------------------------------------
    async def create_payment(
        self,
        *,
        amount_usd: float,
        subscriber_id: str,
        plan_id: str,
        billing_period: str,
        intent_id: str,
        return_url: Optional[str] = None,
    ) -> dict:
        """
        TODO: Implement per official docs.

        Required steps (verify exact names/fields in docs):
        1. Build request body with:
             - amount (amount_usd or its crypto equivalent)
             - currency (USDT)
             - network (TRC20 / ERC20 / BEP20 — whatever merchant supports)
             - order_id / reference (use intent_id)
             - callback_url (our webhook)
             - return_url (optional)
        2. Sign the request using KAZAWALLET_API_SECRET
           (algorithm to be confirmed — likely HMAC-SHA256).
        3. POST to `{base_url}/<PAYMENT_ENDPOINT>` (verify exact path).
        4. Parse response → return normalized dict:
             external_id, pay_url, address, amount_crypto,
             currency, network, expires_at, raw.
        5. NEVER log api_secret or full signature.
        """
        raise NotImplementedError(
            "Kazawallet create_payment pending official API docs. "
            "Fill in after merchant account approval."
        )

    # ------------------------------------------------------------------
    # verify_and_parse_webhook
    # ------------------------------------------------------------------
    async def verify_and_parse_webhook(self, *, body_bytes: bytes, headers: dict) -> dict:
        """
        TODO: Implement per official docs.

        Required steps (verify exact scheme in docs):
        1. Extract the signature from the header name Kazawallet uses
           (common candidates: X-Signature, Signature, X-Kaza-Signature).
        2. Recompute HMAC over body (algorithm TBD — likely SHA-256 or SHA-512).
        3. Compare using `hmac.compare_digest` (timing-safe).
        4. Reject with ValueError if signature mismatch.
        5. Parse JSON payload.
        6. Return normalized dict:
             external_id, intent_id, status,
             amount, currency, network, tx_hash, raw.
        7. Map Kazawallet's status values → our normalized set:
             confirmed | failed | pending | seen
        """
        raise NotImplementedError(
            "Kazawallet webhook verification pending official API docs."
        )

    # ------------------------------------------------------------------
    # health
    # ------------------------------------------------------------------
    async def health(self) -> dict:
        """
        TODO: Implement a lightweight ping.
        Until then, report 'unimplemented' so monitoring does not
        wrongly assume health.
        """
        return {
            "ok": False,
            "details": "kazawallet adapter not yet implemented",
        }

    # ------------------------------------------------------------------
    # Helpers (used once implementation begins)
    # ------------------------------------------------------------------
    def _sign_hmac(self, payload: bytes, algo: str = "sha256") -> str:
        """
        Generic HMAC signer — DO NOT use until confirmed against docs.
        Kept here so implementation has a single place to define signing.
        """
        if algo == "sha256":
            digest = hashlib.sha256
        elif algo == "sha512":
            digest = hashlib.sha512
        else:
            raise ValueError(f"Unsupported algo: {algo}")
        return hmac.new(self.api_secret.encode(), payload, digest).hexdigest()

    def _verify_webhook_signature(
        self, body_bytes: bytes, signature: str, algo: str = "sha256"
    ) -> bool:
        """
        Generic webhook signature verifier — DO NOT use until confirmed.
        """
        expected = hmac.new(
            self.webhook_secret.encode(), body_bytes, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature or "")
