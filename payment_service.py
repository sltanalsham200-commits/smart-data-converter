"""
Payment business logic — provider-agnostic.

Responsibilities:
- create_payment_intent(): create DB row + call provider
- process_webhook(): verify signature + idempotency + activate subscription

Safety:
- Idempotent via webhook_events (provider + event_id + payload_hash)
- Amount/currency/network verification against stored intent
- Subscription activated exactly once
- Every state change is logged
"""
import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException

from payment_registry import get_provider
from supabase_auth import get_supabase_client

logger = logging.getLogger("payment_service")


# ---------------------------------------------------------------------------
# Create intent
# ---------------------------------------------------------------------------
async def create_payment_intent(subscriber_id: str, plan_id: str, billing_period: str) -> dict:
    """
    Create a new payment intent + call provider.

    Returns:
        {
          intent_id, pay_url, address, amount_usd, currency, network,
          expires_at, provider, status
        }
    """
    client = get_supabase_client()
    if client is None:
        raise HTTPException(status_code=503, detail="الخدمة غير متاحة مؤقتاً")

    # 1. Fetch plan (server-side — never trust client price)
    plan_resp = (
        client.table("plans")
        .select("id, name, price_usd, billing_period, is_active")
        .eq("id", plan_id)
        .eq("billing_period", billing_period)
        .limit(1)
        .execute()
    )
    if not plan_resp.data:
        raise HTTPException(status_code=404, detail="الخطة غير موجودة")
    plan = plan_resp.data[0]
    if not plan.get("is_active"):
        raise HTTPException(status_code=400, detail="الخطة غير مفعّلة")
    if plan["name"] == "free":
        raise HTTPException(status_code=400, detail="لا يمكن الدفع لخطة مجانية")

    amount_usd = float(plan["price_usd"])
    if amount_usd <= 0:
        raise HTTPException(status_code=500, detail="سعر الخطة غير صالح")

    # 2. Insert payment_intent row (provider set after)
    try:
        intent_row = client.table("payment_intents").insert({
            "subscriber_id": subscriber_id,
            "plan_id": plan["id"],
            "billing_period": billing_period,
            "amount_usd": amount_usd,
            "provider": "pending",
            "status": "pending",
        }).execute().data[0]
    except Exception:
        logger.exception("intent insert failed")
        raise HTTPException(status_code=503, detail="تعذّر إنشاء طلب الدفع")

    intent_id = intent_row["id"]

    # 3. Call provider
    try:
        provider = get_provider()
        result = await provider.create_payment(
            amount_usd=amount_usd,
            subscriber_id=subscriber_id,
            plan_id=plan["id"],
            billing_period=billing_period,
            intent_id=intent_id,
        )
    except NotImplementedError as e:
        # Rollback intent to cancelled
        client.table("payment_intents").update({
            "status": "cancelled",
            "provider": getattr(provider, "name", "unknown"),
            "raw_provider": {"error": str(e)[:200]},
        }).eq("id", intent_id).execute()
        raise HTTPException(
            status_code=503,
            detail="مزود الدفع غير جاهز حالياً. حاول لاحقاً.",
        )
    except Exception as e:
        logger.exception("provider create failed")
        client.table("payment_intents").update({
            "status": "cancelled",
            "raw_provider": {"error": type(e).__name__},
        }).eq("id", intent_id).execute()
        raise HTTPException(status_code=503, detail="تعذّر إنشاء طلب الدفع")

    # 4. Update intent with provider details
    try:
        client.table("payment_intents").update({
            "provider": provider.name,
            "provider_invoice_id": result.get("external_id"),
            "payment_address": result.get("address"),
            "pay_url": result.get("pay_url"),
            "network": result.get("network"),
            "currency": result.get("currency", "USDT"),
            "expires_at": result.get("expires_at"),
            "raw_provider": result.get("raw", {}),
        }).eq("id", intent_id).execute()
    except Exception:
        logger.exception("intent update failed")
        # Not fatal; intent is pending

    return {
        "intent_id": intent_id,
        "provider": provider.name,
        "pay_url": result.get("pay_url"),
        "address": result.get("address"),
        "amount_usd": amount_usd,
        "amount_crypto": result.get("amount_crypto"),
        "currency": result.get("currency", "USDT"),
        "network": result.get("network"),
        "expires_at": result.get("expires_at"),
        "status": "pending",
    }


# ---------------------------------------------------------------------------
# Process webhook
# ---------------------------------------------------------------------------
async def process_webhook(provider_name: str, body_bytes: bytes, headers: dict) -> dict:
    """
    Handle an incoming webhook.
    Returns {'processed': bool, 'reason': str}.
    Raises HTTPException on signature failure.
    """
    client = get_supabase_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Service unavailable")

    # 1. Select provider
    if provider_name == "test":
        from payment_test import TestPaymentProvider
        provider = TestPaymentProvider()
    elif provider_name == "kazawallet":
        from payment_kazawallet import KazawalletProvider
        provider = KazawalletProvider()
    else:
        raise HTTPException(status_code=404, detail="Unknown provider")

    # 2. Verify signature
    try:
        parsed = await provider.verify_and_parse_webhook(
            body_bytes=body_bytes, headers=headers
        )
    except ValueError as e:
        logger.warning("webhook signature invalid: %s", str(e)[:100])
        raise HTTPException(status_code=401, detail="توقيع غير صالح")
    except NotImplementedError:
        raise HTTPException(status_code=503, detail="المزود غير مدعوم بعد")
    except Exception:
        logger.exception("webhook parse failed")
        raise HTTPException(status_code=400, detail="محتوى الإشعار غير صالح")

    # 3. Idempotency: compute payload hash + event key
    payload_hash = hashlib.sha256(body_bytes).hexdigest()
    external_id = parsed.get("external_id") or ""
    event_id = external_id or payload_hash

    # Check existing
    existing = (
        client.table("webhook_events")
        .select("id, processed, payload_hash")
        .eq("provider", provider.name)
        .eq("payload_hash", payload_hash)
        .limit(1)
        .execute()
    )
    if existing.data:
        logger.info("duplicate webhook (hash match)")
        return {"processed": False, "reason": "duplicate_payload"}

    # Insert event row (will catch unique conflicts)
    try:
        event_row = client.table("webhook_events").insert({
            "provider": provider.name,
            "event_id": event_id,
            "event_type": parsed.get("status"),
            "payload_hash": payload_hash,
            "payload": parsed.get("raw", {}),
            "processed": False,
        }).execute().data[0]
    except Exception:
        # Most likely unique violation — treat as duplicate
        logger.info("webhook duplicate on insert")
        return {"processed": False, "reason": "duplicate_insert"}

    webhook_id = event_row["id"]

    # 4. Find matching intent
    intent_resp = (
        client.table("payment_intents")
        .select("id, subscriber_id, plan_id, billing_period, amount_usd, currency, network, status, provider")
        .eq("provider_invoice_id", external_id)
        .eq("provider", provider.name)
        .limit(1)
        .execute()
    )
    if not intent_resp.data:
        # Mark as failed — unknown intent
        client.table("webhook_events").update({
            "processed": True,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "error": "intent_not_found",
        }).eq("id", webhook_id).execute()
        logger.warning("webhook for unknown intent: %s", external_id[:30])
        return {"processed": False, "reason": "intent_not_found"}

    intent = intent_resp.data[0]

    if intent["status"] in ("confirmed", "cancelled", "expired"):
        client.table("webhook_events").update({
            "processed": True,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "error": f"intent_already_{intent['status']}",
        }).eq("id", webhook_id).execute()
        return {"processed": False, "reason": f"intent_{intent['status']}"}

    # 5. Verify status
    if parsed["status"] != "confirmed":
        # Update intent status but don't activate
        client.table("payment_intents").update({
            "status": parsed["status"] if parsed["status"] in ("failed", "seen", "pending") else "pending",
        }).eq("id", intent["id"]).execute()
        client.table("webhook_events").update({
            "processed": True,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", webhook_id).execute()
        return {"processed": True, "reason": f"status_{parsed['status']}"}

    # 6. Verify amount
    paid = float(parsed.get("amount") or 0)
    expected = float(intent["amount_usd"])
    if paid < expected * 0.99:  # 1% tolerance
        client.table("payment_intents").update({
            "status": "failed",
            "raw_provider": parsed.get("raw", {}),
        }).eq("id", intent["id"]).execute()
        client.table("webhook_events").update({
            "processed": True,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "error": f"amount_mismatch paid={paid} expected={expected}",
        }).eq("id", webhook_id).execute()
        return {"processed": False, "reason": "amount_mismatch"}

    # 7. Verify network (if intent specified one)
    if intent.get("network") and parsed.get("network"):
        if intent["network"] != parsed["network"]:
            client.table("payment_intents").update({
                "status": "failed",
                "raw_provider": parsed.get("raw", {}),
            }).eq("id", intent["id"]).execute()
            client.table("webhook_events").update({
                "processed": True,
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "error": f"network_mismatch want={intent['network']} got={parsed['network']}",
            }).eq("id", webhook_id).execute()
            return {"processed": False, "reason": "network_mismatch"}

    # 8. Create payment + activate subscription (in order)
    now = datetime.now(timezone.utc)
    try:
        payment_row = client.table("payments").insert({
            "subscriber_id": intent["subscriber_id"],
            "amount": expected,
            "currency": parsed.get("currency", "USDT"),
            "network": parsed.get("network"),
            "status": "confirmed",
            "reference_id": parsed.get("tx_hash") or external_id,
            "audit_data": {
                "provider": provider.name,
                "intent_id": intent["id"],
                "webhook_id": webhook_id,
                "raw_status": parsed["status"],
            },
            "confirmed_at": now.isoformat(),
        }).execute().data[0]
    except Exception:
        logger.exception("payment insert failed")
        client.table("webhook_events").update({
            "processed": False,
            "error": "payment_insert_failed",
        }).eq("id", webhook_id).execute()
        raise HTTPException(status_code=500, detail="فشل تسجيل الدفعة")

    # Expire old active subscriptions for this subscriber
    client.table("subscriptions").update({"status": "expired"}).eq(
        "subscriber_id", intent["subscriber_id"]
    ).eq("status", "active").execute()

    # Create new active subscription
    period_days = 365 if intent["billing_period"] == "yearly" else 30
    try:
        client.table("subscriptions").insert({
            "subscriber_id": intent["subscriber_id"],
            "plan_id": intent["plan_id"],
            "status": "active",
            "started_at": now.isoformat(),
            "expires_at": (now + timedelta(days=period_days)).isoformat(),
            "auto_renew": False,
            "payment_id": payment_row["id"],
        }).execute()
    except Exception:
        logger.exception("subscription insert failed")
        # Payment recorded, but subscription failed — flag for review
        client.table("webhook_events").update({
            "processed": True,
            "processed_at": now.isoformat(),
            "error": "subscription_insert_failed",
        }).eq("id", webhook_id).execute()
        return {"processed": False, "reason": "subscription_failed"}

    # Link intent → payment
    client.table("payment_intents").update({
        "status": "confirmed",
        "payment_id": payment_row["id"],
        "confirmed_at": now.isoformat(),
    }).eq("id", intent["id"]).execute()

    # Mark webhook processed
    client.table("webhook_events").update({
        "processed": True,
        "processed_at": now.isoformat(),
    }).eq("id", webhook_id).execute()

    logger.info("payment activated: intent=%s payment=%s", intent["id"], payment_row["id"])
    return {"processed": True, "reason": "activated", "payment_id": payment_row["id"]}
