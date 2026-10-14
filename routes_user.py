"""
User account endpoints — require Supabase Auth JWT.

Endpoints:
  GET  /v1/me               — subscriber + subscription + usage
  GET  /v1/subscription     — current subscription details
  GET  /v1/keys             — list API keys
  POST /v1/keys             — create new API key
  POST /v1/keys/{id}/revoke — revoke key
  POST /v1/keys/{id}/rotate — rotate key

All require: Authorization: Bearer <supabase-jwt>
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import keys as keys_mod
from auth_jwt import get_current_subscriber
from supabase_auth import get_supabase_client

logger = logging.getLogger("routes_user")

router = APIRouter(prefix="/v1", tags=["user"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class CreateKeyBody(BaseModel):
    name: str = Field(default="Default", max_length=64)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _current_subscription(client, subscriber_id: str) -> dict | None:
    """Return the active subscription + plan info, or None."""
    resp = (
        client.table("subscriptions")
        .select("id, status, started_at, expires_at, auto_renew, plan_id, plans(id, name, display_name, max_requests, rate_limit_per_min, billing_period, price_usd, allowed_tools)")
        .eq("subscriber_id", subscriber_id)
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )
    if not resp.data:
        return None
    return resp.data[0]


def _monthly_usage(client, subscriber_id: str) -> int:
    """Sum of request_count for current UTC month across all keys."""
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    resp = (
        client.table("usage_daily")
        .select("request_count")
        .eq("subscriber_id", subscriber_id)
        .gte("date", month_start.date().isoformat())
        .execute()
    )
    return sum(int(r.get("request_count", 0)) for r in (resp.data or []))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/me")
async def get_me(subscriber: dict = Depends(get_current_subscriber)):
    """Return account info + subscription + usage summary."""
    client = get_supabase_client()
    if client is None:
        raise HTTPException(status_code=503, detail="الخدمة غير متاحة مؤقتاً")

    sub = _current_subscription(client, subscriber["id"])
    usage = _monthly_usage(client, subscriber["id"])

    plan = None
    if sub and sub.get("plans"):
        plan = {
            "name": sub["plans"]["name"],
            "display_name": sub["plans"]["display_name"],
            "max_requests": sub["plans"]["max_requests"],
            "rate_limit_per_min": sub["plans"]["rate_limit_per_min"],
            "billing_period": sub["plans"]["billing_period"],
            "price_usd": float(sub["plans"]["price_usd"]),
            "allowed_tools": sub["plans"]["allowed_tools"],
        }

    return {
        "subscriber": {
            "id": subscriber["id"],
            "email": subscriber["email"],
            "status": subscriber["status"],
            "created_at": subscriber["created_at"],
        },
        "subscription": {
            "status": sub["status"] if sub else None,
            "started_at": sub["started_at"] if sub else None,
            "expires_at": sub["expires_at"] if sub else None,
            "auto_renew": sub["auto_renew"] if sub else None,
        } if sub else None,
        "plan": plan,
        "usage": {
            "current_month": usage,
            "max_requests": plan["max_requests"] if plan else 0,
            "remaining": max(0, (plan["max_requests"] if plan else 0) - usage),
        },
    }


@router.get("/subscription")
async def get_subscription(subscriber: dict = Depends(get_current_subscriber)):
    """Current subscription details."""
    client = get_supabase_client()
    if client is None:
        raise HTTPException(status_code=503, detail="الخدمة غير متاحة مؤقتاً")

    sub = _current_subscription(client, subscriber["id"])
    if not sub:
        raise HTTPException(status_code=404, detail="لا يوجد اشتراك حالياً")

    return {
        "id": sub["id"],
        "status": sub["status"],
        "started_at": sub["started_at"],
        "expires_at": sub["expires_at"],
        "auto_renew": sub["auto_renew"],
        "plan": sub.get("plans"),
    }


@router.get("/keys")
async def list_my_keys(subscriber: dict = Depends(get_current_subscriber)):
    """List all API keys belonging to the caller."""
    return {"keys": keys_mod.list_keys(subscriber["id"])}


@router.post("/keys", status_code=201)
async def create_my_key(
    body: CreateKeyBody,
    subscriber: dict = Depends(get_current_subscriber),
):
    """
    Create a new API key.
    ⚠️ The plaintext is returned ONLY ONCE — store it safely.
    """
    result = keys_mod.create_key(subscriber["id"], body.name)
    return {
        **result,
        "warning": "هذا آخر ظهور للمفتاح الكامل. احفظه في مكان آمن.",
    }


@router.post("/keys/{key_id}/revoke")
async def revoke_my_key(
    key_id: str,
    subscriber: dict = Depends(get_current_subscriber),
):
    """Revoke one of your keys."""
    ok = keys_mod.revoke_key(subscriber["id"], key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="المفتاح غير موجود أو مُلغى بالفعل")
    return {"status": "revoked", "id": key_id}


@router.post("/keys/{key_id}/rotate")
async def rotate_my_key(
    key_id: str,
    subscriber: dict = Depends(get_current_subscriber),
):
    """Revoke old key and issue a new one with the same name."""
    result = keys_mod.rotate_key(subscriber["id"], key_id)
    return {
        **result,
        "warning": "احفظ المفتاح الجديد. المفتاح القديم أُلغي ولن يعمل.",
    }
