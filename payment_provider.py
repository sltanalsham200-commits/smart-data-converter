"""
Payment Provider abstraction.

Allows swapping providers (Kazawallet, NOWPayments, test, ...) without
changing subscription logic.

Each provider must implement:
- create_payment()
- verify_and_parse_webhook()
- (optional) get_payment_status()

The rest of the system (subscriptions, usage) is provider-agnostic.
"""
from abc import ABC, abstractmethod
from typing import Optional


class PaymentProvider(ABC):
    """
    Interface for crypto payment providers.
    """

    name: str = "unknown"

    @abstractmethod
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
        Create a payment intent at the provider.

        Returns a dict with at least:
          - external_id (provider's id)
          - pay_url (URL to redirect user to)
          - address (optional, for direct crypto address)
          - amount_crypto (float, amount in crypto)
          - currency (e.g. 'USDT')
          - network (e.g. 'TRC20')
          - expires_at (ISO8601, optional)
          - raw (dict, provider's raw response)
        """
        raise NotImplementedError

    @abstractmethod
    async def verify_and_parse_webhook(
        self,
        *,
        body_bytes: bytes,
        headers: dict,
    ) -> dict:
        """
        Verify webhook authenticity and parse payload.

        Must RAISE on invalid signature.

        Returns a normalized dict:
          - external_id (provider's transaction/payment id)
          - intent_id (our internal id, if returned by provider)
          - status ('confirmed'|'failed'|'pending'|'seen')
          - amount (float)
          - currency (str)
          - network (str)
          - tx_hash (str, optional)
          - raw (dict)
        """
        raise NotImplementedError

    @abstractmethod
    async def health(self) -> dict:
        """
        Lightweight health check (API reachable?).
        Returns {'ok': bool, 'details': str}.
        """
        raise NotImplementedError
