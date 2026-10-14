"""
Admin / infrastructure endpoints.

Routes:
  POST /v1/cron/tick   — periodic jobs (protected by X-Cron-Secret)

These endpoints are NOT for end users.
"""
import logging

from fastapi import APIRouter, Header, HTTPException

from cron_service import run_tick, verify_cron_secret

logger = logging.getLogger("routes_admin")

router = APIRouter(prefix="/v1", tags=["admin"])


@router.post("/cron/tick")
async def cron_tick(x_cron_secret: str = Header(None)):
    """
    Run periodic maintenance jobs.

    Auth: X-Cron-Secret header (compared timing-safe).
    Called by: Cloudflare Worker `tools-forge-cron` every hour.

    Jobs:
    - Expire past-due subscriptions
    - Cleanup old webhook_events (>90 days)
    """
    verify_cron_secret(x_cron_secret)
    try:
        result = run_tick()
    except HTTPException:
        raise
    except Exception:
        logger.exception("cron tick crashed")
        raise HTTPException(status_code=500, detail="cron failed")
    return result
