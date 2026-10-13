"""
Supabase-based authentication layer for Tools Forge API.

Handles:
- Per-subscriber API keys (SHA-256 hashed)
- Subscription status verification
- Atomic quota check via increment_usage RPC

Coexists with legacy API_KEY (for backward compatibility).
"""
import hashlib
import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

from fastapi import HTTPException
from supabase import create_client, Client


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

    Returns dict with:
        {
            "subscriber_id": UUID,
            "api_key_id": UUID,
            "allowed": bool,
            "current_usage": int,
            "max_requests": int
        }
    Or None if key is invalid/inactive/expired.
    """
    client = get_supabase_client()
    if client is None:
        return None

    key_hash = hash_api_key(api_key)

    # 1. Find the key
    try:
        key_resp = (
            client.table("api_keys")
            .select("id, subscriber_id, status")
            .eq("key_hash", key_hash)
            .eq("status", "active")
            .limit(1)
            .execute()
        )
    except Exception:
        return None

    if not key_resp.data:
        return None

    key_row = key_resp.data[0]
    api_key_id = key_row["id"]
    subscriber_id = key_row["subscriber_id"]

    # 2. Update last_used_at (fire-and-forget)
    try:
        client.table("api_keys").update(
            {"last_used_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", api_key_id).execute()
    except Exception:
        pass  # Not critical

    # 3. Atomic quota check + increment via RPC
    try:
        rpc_resp = client.rpc(
            "increment_usage",
            {"p_api_key_id": api_key_id, "p_tool": tool_name},
        ).execute()
    except Exception:
        return None

    if not rpc_resp.data:
        return None

    row = rpc_resp.data[0] if isinstance(rpc_resp.data, list) else rpc_resp.data

    return {
        "subscriber_id": subscriber_id,
        "api_key_id": api_key_id,
        "allowed": row.get("allowed", False),
        "current_usage": row.get("current_usage", 0),
        "max_requests": row.get("max_requests", 0),
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

    if not result["allowed"]:
        raise HTTPException(
            status_code=429,
            detail=(
                f"تم استنفاد الحصة الشهرية "
                f"({result['current_usage']}/{result['max_requests']})"
            ),
        )

    return result
