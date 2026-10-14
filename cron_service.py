"""
Cron business logic.

Currently runs:
1. Expire subscriptions past expires_at
2. Cleanup old webhook_events (> 90 days)
3. Cleanup old rate-limit traces if any
4. Record audit row in cron_runs

Called by: POST /v1/cron/tick (protected by X-Cron-Secret header)
Invoked by: Cloudflare Worker `tools-forge-cron` every hour
"""
import logging
import os
import time
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException, Header

from supabase_auth import get_supabase_client

logger = logging.getLogger("cron_service")

CRON_SECRET_ENV = "CRON_SECRET"


def verify_cron_secret(x_cron_secret: str | None) -> None:
    """Constant-time secret check."""
    import secrets as _secrets
    expected = os.environ.get(CRON_SECRET_ENV, "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="cron not configured")
    if not x_cron_secret or not _secrets.compare_digest(x_cron_secret, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


def run_tick() -> dict:
    """
    Runs all periodic jobs. Returns summary.
    Always writes a cron_runs row (status ok/error).
    """
    client = get_supabase_client()
    if client is None:
        raise HTTPException(status_code=503, detail="service unavailable")

    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()

    # Create audit row (status=running)
    try:
        run_row = client.table("cron_runs").insert({
            "status": "running",
        }).execute().data[0]
        run_id = run_row["id"]
    except Exception:
        logger.exception("cron_runs insert failed")
        raise HTTPException(status_code=503, detail="cron audit insert failed")

    expired_count = 0
    cleaned_webhooks = 0
    error_text = None

    try:
        # -------- Job 1: Expire subscriptions --------
        now_iso = started_at.isoformat()
        try:
            expired_resp = (
                client.table("subscriptions")
                .update({"status": "expired"})
                .lt("expires_at", now_iso)
                .eq("status", "active")
                .execute()
            )
            expired_count = len(expired_resp.data or [])
            if expired_count:
                logger.info("expired %d subscriptions", expired_count)
        except Exception as e:
            logger.exception("expire subscriptions failed")
            raise

        # -------- Job 2: Cleanup old webhook_events (>90 days) --------
        cutoff = (started_at - timedelta(days=90)).isoformat()
        try:
            cleanup_resp = (
                client.table("webhook_events")
                .delete()
                .lt("created_at", cutoff)
                .eq("processed", True)
                .execute()
            )
            cleaned_webhooks = len(cleanup_resp.data or [])
            if cleaned_webhooks:
                logger.info("cleaned %d old webhook events", cleaned_webhooks)
        except Exception as e:
            logger.exception("cleanup webhook events failed")
            # Non-fatal — continue

    except Exception as e:
        error_text = type(e).__name__
        duration_ms = int((time.monotonic() - t0) * 1000)
        try:
            client.table("cron_runs").update({
                "status": "error",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error": error_text,
                "duration_ms": duration_ms,
            }).eq("id", run_id).execute()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"cron failed: {error_text}")

    # -------- Success: finalize --------
    duration_ms = int((time.monotonic() - t0) * 1000)
    try:
        client.table("cron_runs").update({
            "status": "ok",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "expired_count": expired_count,
            "cleaned_webhooks": cleaned_webhooks,
            "duration_ms": duration_ms,
        }).eq("id", run_id).execute()
    except Exception:
        logger.exception("cron_runs finalize failed")

    return {
        "status": "ok",
        "expired_count": expired_count,
        "cleaned_webhooks": cleaned_webhooks,
        "duration_ms": duration_ms,
        "run_id": run_id,
    }
