"""
JWT-based authentication for Tools Forge API.

Uses Supabase Auth (via service_role) to verify the caller's JWT.
This delegates ES256 signature verification to Supabase — no local
crypto libraries required.

Flow:
  1. Extract Bearer token from Authorization header.
  2. Call supabase.auth.get_user(token) → verifies signature, expiry.
  3. Look up subscriber by auth_user_id.
  4. Return subscriber row (or None).

Security:
- Never trusts client-supplied subscriber_id.
- Never logs the raw token.
- Fails closed on any error.
"""
import logging
from typing import Optional

from fastapi import Header, HTTPException

from supabase_auth import get_supabase_client

logger = logging.getLogger("auth_jwt")


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    """Extract the JWT from `Authorization: Bearer <token>`."""
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


async def get_current_subscriber(
    authorization: Optional[str] = Header(None),
) -> dict:
    """
    FastAPI dependency. Returns the subscriber row for the caller.

    Raises:
      - 401 if Authorization is missing/invalid/expired
      - 403 if the auth user has no subscriber record
      - 503 if Supabase is unreachable
    """
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="مطلوب ترويسة Authorization بصيغة Bearer",
        )

    client = get_supabase_client()
    if client is None:
        logger.error("Supabase client unavailable")
        raise HTTPException(
            status_code=503,
            detail="الخدمة غير متاحة مؤقتاً",
        )

    # 1. Verify JWT with Supabase
    try:
        user_resp = client.auth.get_user(token)
    except Exception as e:
        # Do not log the token itself
        logger.warning("JWT verification failed: %s", type(e).__name__)
        raise HTTPException(status_code=401, detail="رمز الدخول غير صالح أو منتهٍ")

    if user_resp is None or user_resp.user is None:
        raise HTTPException(status_code=401, detail="رمز الدخول غير صالح")

    auth_user_id = user_resp.user.id
    if not auth_user_id:
        raise HTTPException(status_code=401, detail="رمز الدخول غير صالح")

    # 2. Look up subscriber row by auth_user_id
    try:
        row_resp = (
            client.table("subscribers")
            .select("id, email, status, auth_user_id, created_at, updated_at")
            .eq("auth_user_id", auth_user_id)
            .limit(1)
            .execute()
        )
    except Exception:
        logger.exception("Subscriber lookup failed")
        raise HTTPException(status_code=503, detail="الخدمة غير متاحة مؤقتاً")

    if not row_resp.data:
        raise HTTPException(
            status_code=403,
            detail="لا يوجد حساب مرتبط بهذا المستخدم. تواصل مع الدعم.",
        )

    subscriber = row_resp.data[0]

    if subscriber.get("status") != "active":
        raise HTTPException(
            status_code=403,
            detail="الحساب غير مفعّل",
        )

    return subscriber


def raise_for_subscriber_ownership(resource_subscriber_id: str, current_subscriber: dict) -> None:
    """
    Ensure the caller owns the requested resource.
    Raises 403 if mismatch.
    """
    if str(resource_subscriber_id) != str(current_subscriber["id"]):
        raise HTTPException(status_code=403, detail="غير مصرّح بالوصول إلى هذا المورد")
