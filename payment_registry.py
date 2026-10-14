"""
Payment provider registry.

Selects provider at runtime based on env var PAYMENT_PROVIDER.
Defaults to 'test' for development.
"""
import logging
import os

from payment_provider import PaymentProvider

logger = logging.getLogger("payment_registry")

_PROVIDER_INSTANCE: PaymentProvider | None = None


def get_provider() -> PaymentProvider:
    """
    Return the configured provider (singleton).

    Selection order:
      1. PAYMENT_PROVIDER env var
      2. 'test' by default
    """
    global _PROVIDER_INSTANCE
    if _PROVIDER_INSTANCE is not None:
        return _PROVIDER_INSTANCE

    name = os.environ.get("PAYMENT_PROVIDER", "test").strip().lower()
    logger.info("Selected payment provider: %s", name)

    if name == "test":
        from payment_test import TestPaymentProvider
        _PROVIDER_INSTANCE = TestPaymentProvider()

    elif name == "kazawallet":
        # Lazy import — will raise if credentials missing
        from payment_kazawallet import KazawalletProvider
        _PROVIDER_INSTANCE = KazawalletProvider()

    else:
        raise RuntimeError(f"Unknown PAYMENT_PROVIDER: {name}")

    return _PROVIDER_INSTANCE


def _reset_for_tests() -> None:
    """For unit tests only."""
    global _PROVIDER_INSTANCE
    _PROVIDER_INSTANCE = None
