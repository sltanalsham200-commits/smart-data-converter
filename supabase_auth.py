"""
Supabase-based authentication layer for Tools Forge API.

Uses unified verify_and_increment RPC (1 DB round-trip per request).
Handles: per-subscriber quota, atomic locking, last_used_at update,
and returns rate_limit_per_min for the in-memory rate limiter.

Coexists with legacy API_KEY (for backward compatibility).
"""
import hashlib
import logging
import os
from functools import lru_cache
from typing import Optional

from fastapi import HTTPException
from supabase import create_client, Client

logger = logging.getLogger("supabase_auth")


# ---------------------------------------------------------------------------
# Supabase client (cached)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_supabase_client() -> Optional[Client]:
    """
    Returns cached Supabase client.
    Returns None if env vars are not configured (legacy mode).
    """
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()

    if not url or not key:
        return None

    try:
        return create_client(url, key)
    except Exception:
        logger.exception("Failed to create Supabase client")
        return None


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------
def hash_api_key(key: str) -> str:
    """SHA-256 hex digest of an API key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    """
    Generates a new API key with prefix `tf_live_` + 32 hex chars.
    Returns the plaintext key (only time it's visible).
    """
    import secrets
    return "tf_live_" + secrets.token_hex(16)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
def verify_subscriber_key(api_key: str, tool_name: str) -> Optional[dict]:
    """
    Verify a subscriber's API key + check quota + increment usage.

    Single DB round-trip via verify_and_increment RPC.

    Returns dict with:
        {
            "subscriber_id": UUID,
            "api_key_id": UUID,
            "allowed": bool,
            "current_usage": int,
            "max_requests": int,
            "rate_limit_per_min": int,
        }
    Or None if key is invalid/inactive/expired.
    """
    client = get_supabase_client()
    if client is None:
        return None

    key_hash = hash_api_key(api_key)

    # Single RPC call: verify + increment + return rate_limit
    try:
        rpc_resp = client.rpc(
            "verify_and_increment",
            {"p_key_hash": key_hash, "p_tool": tool_name},
        ).execute()
    except Exception:
        logger.exception("Supabase RPC verify_and_increment failed")
        return None

    if not rpc_resp.data:
        return None

    row = rpc_resp.data[0] if isinstance(rpc_resp.data, list) else rpc_resp.data

    # key_valid = False → invalid key, don't leak reason
    if not row.get("key_valid", False):
        return None

    return {
        "subscriber_id": row.get("out_subscriber_id"),
        "api_key_id": row.get("out_key_id"),
        "allowed": row.get("quota_allowed", False),
        "current_usage": row.get("current_usage", 0),
        "max_requests": row.get("max_requests", 0),
        "rate_limit_per_min": row.get("rate_limit_per_min", 0),
        "rate_allowed": row.get("rate_allowed", True),
        "rate_current": row.get("rate_current", 0),
    }


def raise_for_subscriber_key(api_key: str, tool_name: str) -> dict:
    """
    Wrapper that raises HTTPException on failure.
    Returns the result dict on success.
    """
    result = verify_subscriber_key(api_key, tool_name)

    if result is None:
        raise HTTPException(
            status_code=401,
            detail="مفتاح API غير صالح",
        )

    if not result.get("rate_allowed", True):
        raise HTTPException(
            status_code=429,
            detail=(
                f"تجاوز حد الطلبات "
                f"({result['rate_current']}/{result['rate_limit_per_min']} في الدقيقة)"
            ),
        )

    if not result["allowed"]:
        raise HTTPException(
            status_code=429,
            detail=(
                f"تم استنفاد الحصة الشهرية "
                f"({result['current_usage']}/{result['max_requests']})"
            ),
        )

    return result
