"""Test Payment Provider — for local/CI testing ONLY."""
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timezone, timedelta

from payment_provider import PaymentProvider

logger = logging.getLogger("payment_test")


class TestPaymentProvider(PaymentProvider):
    name = "test"

    def __init__(self):
        self.webhook_secret = os.environ.get("TEST_WEBHOOK_SECRET", "test-secret-dev-only")
        env = os.environ.get("ENVIRONMENT", "development").lower()
        allow = os.environ.get("ALLOW_TEST_PAYMENTS", "false").lower() == "true"
        if env == "production" and not allow:
            raise RuntimeError("TestPaymentProvider disabled in production.")

    async def create_payment(
        self, *, amount_usd, subscriber_id, plan_id, billing_period, intent_id, return_url=None
    ) -> dict:
        external_id = "test_" + secrets.token_hex(8)
        return {
            "external_id": external_id,
            "pay_url": f"https://test.local/pay/{external_id}",
            "address": "TEST-ADDRESS",
            "amount_crypto": amount_usd,
            "currency": "USDT",
            "network": "TRC20",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "raw": {"test_mode": True, "intent_id": intent_id},
        }

    async def verify_and_parse_webhook(self, *, body_bytes, headers) -> dict:
        sig_header = headers.get("x-test-signature") or headers.get("X-Test-Signature") or ""
        expected = hmac.new(self.webhook_secret.encode(), body_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig_header, expected):
            raise ValueError("Invalid signature")
        payload = json.loads(body_bytes.decode())
        return {
            "external_id": payload.get("external_id"),
            "intent_id": payload.get("intent_id"),
            "status": payload.get("status", "confirmed"),
            "amount": float(payload.get("amount", 0)),
            "currency": payload.get("currency", "USDT"),
            "network": payload.get("network", "TRC20"),
            "tx_hash": payload.get("tx_hash", "test-hash-" + secrets.token_hex(4)),
            "raw": payload,
        }

    async def health(self) -> dict:
        return {"ok": True, "details": "test provider always healthy"}

    def sign_webhook(self, payload: dict):
        body = json.dumps(payload, separators=(",", ":")).encode()
        sig = hmac.new(self.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        return body, {"X-Test-Signature": sig}
