"""
API key generation and management.

Design:
- Plaintext keys generated with `secrets.token_hex(16)` (32 hex chars).
- Prefix: `tf_live_`
- Only SHA-256 hash is stored in DB.
- Plaintext returned exactly once (at creation).
- Revoke/rotate supported.

Security:
- Never logs the plaintext key.
- Rejects keys from revoked state at auth time (DB check).
"""
import hashlib
import logging
import secrets
from typing import Optional

from fastapi import HTTPException

from supabase_auth import get_supabase_client

logger = logging.getLogger("keys")

KEY_PREFIX = "tf_live_"
KEY_BYTES = 16  # 32 hex chars


def generate_key() -> tuple[str, str, str]:
    """
    Returns (plaintext, key_hash, key_prefix_display).
    plaintext:        tf_live_<32 hex>
    key_hash:         SHA-256 hex (64 chars)
    key_prefix_display: first 12 chars (e.g. "tf_live_ab12")
    """
    random_part = secrets.token_hex(KEY_BYTES)
    plaintext = KEY_PREFIX + random_part
    key_hash = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    prefix_display = plaintext[:12]
    return plaintext, key_hash, prefix_display


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def create_key(subscriber_id: str, name: str) -> dict:
    """
    Create a new API key for a subscriber.
    Returns dict with plaintext (once!) + metadata.
    """
    client = get_supabase_client()
    if client is None:
        raise HTTPException(status_code=503, detail="الخدمة غير متاحة مؤقتاً")

    plaintext, key_hash, prefix_display = generate_key()

    try:
        row = client.table("api_keys").insert({
            "subscriber_id": subscriber_id,
            "key_hash": key_hash,
            "key_prefix": prefix_display,
            "name": name or "Default",
            "status": "active",
        }).execute()
    except Exception:
        logger.exception("API key insert failed")
        raise HTTPException(status_code=503, detail="تعذّر إنشاء المفتاح")

    if not row.data:
        raise HTTPException(status_code=503, detail="تعذّر إنشاء المفتاح")

    created = row.data[0]
    return {
        "id": created["id"],
        "name": created["name"],
        "key_prefix": created["key_prefix"],
        "plaintext": plaintext,   # only this once
        "created_at": created["created_at"],
        "status": created["status"],
    }


def list_keys(subscriber_id: str) -> list[dict]:
    """List all keys belonging to a subscriber (no plaintext)."""
    client = get_supabase_client()
    if client is None:
        raise HTTPException(status_code=503, detail="الخدمة غير متاحة مؤقتاً")

    try:
        resp = (
            client.table("api_keys")
            .select("id, name, key_prefix, status, created_at, last_used_at, revoked_at")
            .eq("subscriber_id", subscriber_id)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception:
        logger.exception("list_keys failed")
        raise HTTPException(status_code=503, detail="تعذّر جلب المفاتيح")

    return resp.data or []


def revoke_key(subscriber_id: str, key_id: str) -> bool:
    """Revoke a key. Returns True if a row was updated."""
    client = get_supabase_client()
    if client is None:
        raise HTTPException(status_code=503, detail="الخدمة غير متاحة مؤقتاً")

    try:
        resp = (
            client.table("api_keys")
            .update({"status": "revoked", "revoked_at": "now()"})
            .eq("id", key_id)
            .eq("subscriber_id", subscriber_id)   # ownership check
            .eq("status", "active")               # only active
            .execute()
        )
    except Exception:
        logger.exception("revoke_key failed")
        raise HTTPException(status_code=503, detail="تعذّر إلغاء المفتاح")

    return bool(resp.data)


def rotate_key(subscriber_id: str, key_id: str) -> dict:
    """
    Revoke old key and create new one with same name.
    Returns new key dict (with plaintext).
    """
    client = get_supabase_client()
    if client is None:
        raise HTTPException(status_code=503, detail="الخدمة غير متاحة مؤقتاً")

    # Fetch old key (ownership + name)
    try:
        old = (
            client.table("api_keys")
            .select("id, name, status")
            .eq("id", key_id)
            .eq("subscriber_id", subscriber_id)
            .limit(1)
            .execute()
        )
    except Exception:
        logger.exception("rotate_key lookup failed")
        raise HTTPException(status_code=503, detail="تعذّر تدوير المفتاح")

    if not old.data:
        raise HTTPException(status_code=404, detail="المفتاح غير موجود")

    old_name = old.data[0].get("name") or "Default"

    # Revoke old
    revoked = revoke_key(subscriber_id, key_id)
    if not revoked:
        raise HTTPException(status_code=400, detail="لا يمكن تدوير مفتاح ملغى بالفعل")

    # Create new
    return create_key(subscriber_id, old_name)
