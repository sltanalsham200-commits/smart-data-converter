"""
Payment endpoints.

Routes:
  POST /v1/payments/create              — create payment intent (JWT)
  GET  /v1/payments                     — list my payments (JWT)
  GET  /v1/payments/{intent_id}         — intent details (JWT)
  POST /v1/webhooks/payment/{provider}  — webhook receiver (public)
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth_jwt import get_current_subscriber
from payment_service import create_payment_intent, process_webhook
from supabase_auth import get_supabase_client

logger = logging.getLogger("routes_payments")

router = APIRouter(prefix="/v1", tags=["payments"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class CreatePaymentBody(BaseModel):
    plan_id: str = Field(..., min_length=1, max_length=64)
    billing_period: str = Field(..., pattern="^(monthly|yearly)$")


# ---------------------------------------------------------------------------
# POST /v1/payments/create
# ---------------------------------------------------------------------------
@router.post("/payments/create", status_code=201)
async def create_payment(
    body: CreatePaymentBody,
    subscriber: dict = Depends(get_current_subscriber),
):
    """Create a payment intent for a plan upgrade."""
    result = await create_payment_intent(
        subscriber_id=subscriber["id"],
        plan_id=body.plan_id,
        billing_period=body.billing_period,
    )
    return result


# ---------------------------------------------------------------------------
# GET /v1/payments
# ---------------------------------------------------------------------------
@router.get("/payments")
async def list_my_payments(subscriber: dict = Depends(get_current_subscriber)):
    """List confirmed payments for the caller."""
    client = get_supabase_client()
    if client is None:
        raise HTTPException(status_code=503, detail="الخدمة غير متاحة مؤقتاً")

    try:
        payments = (
            client.table("payments")
            .select("id, amount, currency, network, status, created_at, confirmed_at")
            .eq("subscriber_id", subscriber["id"])
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        ).data or []
    except Exception:
        logger.exception("list payments failed")
        raise HTTPException(status_code=503, detail="تعذّر جلب المدفوعات")

    # Also include pending intents
    try:
        intents = (
            client.table("payment_intents")
            .select("id, plan_id, billing_period, amount_usd, currency, network, status, pay_url, created_at, expires_at")
            .eq("subscriber_id", subscriber["id"])
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        ).data or []
    except Exception:
        intents = []

    return {"payments": payments, "pending_intents": intents}


# ---------------------------------------------------------------------------
# GET /v1/payments/{intent_id}
# ---------------------------------------------------------------------------
@router.get("/payments/{intent_id}")
async def get_payment_intent(
    intent_id: str,
    subscriber: dict = Depends(get_current_subscriber),
):
    """Fetch a single payment intent owned by the caller."""
    client = get_supabase_client()
    if client is None:
        raise HTTPException(status_code=503, detail="الخدمة غير متاحة مؤقتاً")

    try:
        resp = (
            client.table("payment_intents")
            .select("*")
            .eq("id", intent_id)
            .eq("subscriber_id", subscriber["id"])
            .limit(1)
            .execute()
        )
    except Exception:
        logger.exception("get intent failed")
        raise HTTPException(status_code=503, detail="تعذّر جلب الطلب")

    if not resp.data:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")

    row = resp.data[0]
    # Hide provider secrets / raw payload
    row.pop("raw_provider", None)
    return row


# ---------------------------------------------------------------------------
# POST /v1/webhooks/payment/{provider}   (public — signature verified)
# ---------------------------------------------------------------------------
@router.post("/webhooks/payment/{provider}")
async def receive_payment_webhook(provider: str, request: Request):
    """
    Receive a webhook from a payment provider.

    ⚠️ Security:
    - Never trusts client-supplied subscriber_id/amount/status.
    - Signature verification happens inside process_webhook().
    - Idempotent: repeated events are ignored.
    """
    body_bytes = await request.body()
    headers = dict(request.headers)

    try:
        result = await process_webhook(provider.lower(), body_bytes, headers)
    except HTTPException:
        raise
    except Exception:
        logger.exception("webhook processing crashed")
        raise HTTPException(status_code=500, detail="خطأ في معالجة الإشعار")

    return {"ok": True, **result}
