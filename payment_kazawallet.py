"""
Kazawallet payment provider.

Official API reference (from merchant dashboard / help center):
- Base URL: https://outdoor.kasroad.com/wallet
- Create Payment Link: POST /createPaymentLink
- Webhook signature: SHA-256(amount + ':::' + order_id + ':::' + api_key)

Required env vars:
- KAZAWALLET_API_KEY         (x-api-key)
- KAZAWALLET_API_SECRET      (x-api-secret)
- KAZAWALLET_MERCHANT_EMAIL  (merchant-email header)
- KAZAWALLET_BASE_URL        (default: https://outdoor.kasroad.com/wallet)
- KAZAWALLET_ENV             (dev|production — default: production)

Payment method IDs (Production):
- TRC20 = 118
- BEP20 = 115
- ERC20 = 116
- SOL   = 117

Development:
- TRC20 = 15
- BEP20 = 13

Note: Webhook fires once — must be idempotent at the service layer.
"""
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

from payment_provider import PaymentProvider

logger = logging.getLogger("payment_kazawallet")

# Payment method IDs per environment
METHOD_IDS = {
    "production": {"TRC20": "118", "BEP20": "115", "ERC20": "116", "SOL": "117"},
    "development": {"TRC20": "15", "BEP20": "13"},
}


class KazawalletNotConfigured(RuntimeError):
    pass


class KazawalletAPIError(RuntimeError):
    pass


class KazawalletProvider(PaymentProvider):
    name = "kazawallet"

    def __init__(self):
        self.api_key = os.environ.get("KAZAWALLET_API_KEY", "").strip()
        self.api_secret = os.environ.get("KAZAWALLET_API_SECRET", "").strip()
        self.merchant_email = os.environ.get("KAZAWALLET_MERCHANT_EMAIL", "").strip()
        self.base_url = (
            os.environ.get("KAZAWALLET_BASE_URL", "https://outdoor.kasroad.com/wallet")
            .strip()
            .rstrip("/")
        )
        self.env = os.environ.get("KAZAWALLET_ENV", "production").strip().lower()
        if self.env not in ("production", "development"):
            self.env = "production"

        missing = [
            name
            for name, val in [
                ("KAZAWALLET_API_KEY", self.api_key),
                ("KAZAWALLET_API_SECRET", self.api_secret),
                ("KAZAWALLET_MERCHANT_EMAIL", self.merchant_email),
            ]
            if not val
        ]
        if missing:
            raise KazawalletNotConfigured("Missing env vars: " + ", ".join(missing))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _headers(self, with_secret: bool = True) -> dict:
        h = {
            "x-api-key": self.api_key,
            "merchant-email": self.merchant_email,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if with_secret:
            h["x-api-secret"] = self.api_secret
        return h

    def _method_id(self, network: Optional[str]) -> Optional[str]:
        if not network:
            return None
        mapping = METHOD_IDS.get(self.env, {})
        return mapping.get(network.upper())

    def _compute_signature(self, amount: str, order_id: str) -> str:
        """
        Official formula: SHA-256(amount + ':::' + order_id + ':::' + api_key)
        """
        raw = f"{amount}:::{order_id}:::{self.api_key}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

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
        Create a payment link at Kazawallet.

        Per docs:
          POST {base_url}/createPaymentLink
          body: { amount, currency, email, ref, redirectUrl }
          -> response: { payment_url, transaction_id, ... }
        """
        payload = {
            "amount": f"{amount_usd:.2f}",
            "currency": "USD",
            "email": self.merchant_email,
            "ref": intent_id,
        }
        if return_url:
            payload["redirectUrl"] = return_url

        url = f"{self.base_url}/createPaymentLink"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, headers=self._headers(), json=payload)
        except Exception as e:
            logger.exception("kazawallet create_payment HTTP failed")
            raise KazawalletAPIError(f"HTTP error: {type(e).__name__}") from e

        if resp.status_code >= 400:
            body_snippet = (resp.text or "")[:200]
            logger.warning("kazawallet create_payment HTTP %s: %s",
                           resp.status_code, body_snippet)
            raise KazawalletAPIError(f"HTTP {resp.status_code}")

        try:
            data = resp.json()
        except Exception:
            raise KazawalletAPIError("Invalid JSON response")

        # Response shape per docs (best-effort extraction — some fields
        # may vary by API version; we accept common aliases).
        payment_url = (
            data.get("payment_url")
            or data.get("paymentUrl")
            or data.get("url")
        )
        transaction_id = (
            data.get("transaction_id")
            or data.get("transactionId")
            or data.get("order_id")
            or data.get("orderId")
        )
        if not payment_url or not transaction_id:
            logger.warning("kazawallet unexpected response keys: %s",
                           list(data.keys()))
            raise KazawalletAPIError("Missing payment_url or transaction_id")

        return {
            "external_id": str(transaction_id),
            "pay_url": payment_url,
            "address": data.get("address") or data.get("wallet_address"),
            "amount_crypto": data.get("amount_crypto") or amount_usd,
            "currency": data.get("currency") or "USDT",
            "network": data.get("network"),
            "expires_at": data.get("expires_at")
                          or (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
            "raw": data,
        }

    # ------------------------------------------------------------------
    # verify_and_parse_webhook
    # ------------------------------------------------------------------
    async def verify_and_parse_webhook(self, *, body_bytes: bytes, headers: dict) -> dict:
        """
        Verify Kazawallet webhook signature.

        Per docs:
          Webhook payload includes: order_id, secret, amount, ref, status, currency
          secret = SHA-256(amount + ':::' + order_id + ':::' + api_key)
          status ∈ {fulfilled, timed_out}
        """
        try:
            payload = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            raise ValueError("Invalid JSON payload")

        order_id = str(payload.get("order_id", ""))
        amount = str(payload.get("amount", ""))
        received_secret = str(payload.get("secret", ""))
        ref = payload.get("ref")            # our intent_id
        status_raw = str(payload.get("status", "")).lower()
        currency = payload.get("currency", "USDT")

        if not (order_id and amount and received_secret):
            raise ValueError("Missing required webhook fields")

        expected = self._compute_signature(amount, order_id)
        if not hmac.compare_digest(expected, received_secret):
            raise ValueError("Invalid signature")

        # Normalize status
        if status_raw in ("fulfilled", "completed", "success", "paid"):
            normalized = "confirmed"
        elif status_raw in ("timed_out", "timeout", "expired", "failed", "cancelled"):
            normalized = "failed"
        else:
            normalized = "pending"

        return {
            "external_id": order_id,
            "intent_id": ref,
            "status": normalized,
            "amount": float(amount),
            "currency": currency or "USDT",
            "network": payload.get("network"),
            "tx_hash": payload.get("tx_hash") or payload.get("hash"),
            "raw": payload,
        }

    # ------------------------------------------------------------------
    # health
    # ------------------------------------------------------------------
    async def health(self) -> dict:
        """
        Lightweight configuration check (no external call).
        Returns ok=True if credentials present; ok=False otherwise.
        """
        configured = all([self.api_key, self.api_secret, self.merchant_email])
        return {
            "ok": configured,
            "details": (
                f"env={self.env}, configured={'yes' if configured else 'no'}"
            ),
        }
