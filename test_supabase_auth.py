"""
Tests for supabase_auth layer.
Runs against real Supabase (uses .env.local).
Creates temporary data, then cleans up.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Load .env.local
env_file = Path(__file__).parent / ".env.local"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

import pytest
from fastapi import HTTPException

from supabase_auth import (
    generate_api_key,
    hash_api_key,
    verify_subscriber_key,
    raise_for_subscriber_key,
    get_supabase_client,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def test_setup():
    """Create subscriber + subscription + api_key, yield, then cleanup."""
    client = get_supabase_client()
    assert client is not None, "Supabase not configured"

    # Get free plan
    plan = client.table("plans").select("id").eq("name", "free").eq(
        "billing_period", "monthly"
    ).limit(1).execute().data[0]

    # Create subscriber
    sub_email = f"pytest-{uuid.uuid4().hex[:8]}@test.internal"
    subscriber = client.table("subscribers").insert({
        "email": sub_email,
        "status": "active",
    }).execute().data[0]

    # Create subscription (using Python datetime, not SQL)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=30)
    sub = client.table("subscriptions").insert({
        "subscriber_id": subscriber["id"],
        "plan_id": plan["id"],
        "status": "active",
        "started_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "auto_renew": False,
    }).execute().data[0]

    # Create API key
    plaintext_key = generate_api_key()
    key_row = client.table("api_keys").insert({
        "subscriber_id": subscriber["id"],
        "key_hash": hash_api_key(plaintext_key),
        "key_prefix": plaintext_key[:8],
        "name": "pytest-key",
        "status": "active",
    }).execute().data[0]

    yield {
        "client": client,
        "subscriber": subscriber,
        "subscription": sub,
        "api_key_id": key_row["id"],
        "plaintext_key": plaintext_key,
    }

    # Cleanup
    client.table("usage_daily").delete().eq("api_key_id", key_row["id"]).execute()
    client.table("api_keys").delete().eq("id", key_row["id"]).execute()
    client.table("subscriptions").delete().eq("id", sub["id"]).execute()
    client.table("subscribers").delete().eq("id", subscriber["id"]).execute()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_generate_api_key_format():
    key = generate_api_key()
    assert key.startswith("tf_live_")
    assert len(key) == len("tf_live_") + 32
    # Check hex
    int(key[len("tf_live_"):], 16)


def test_hash_api_key_deterministic():
    key = "tf_live_test123"
    h1 = hash_api_key(key)
    h2 = hash_api_key(key)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_hash_api_key_different_for_different_inputs():
    assert hash_api_key("a") != hash_api_key("b")


def test_verify_valid_key(test_setup):
    result = verify_subscriber_key(
        test_setup["plaintext_key"], "smart-data-converter"
    )
    assert result is not None
    assert result["allowed"] is True
    assert result["current_usage"] == 1
    assert result["max_requests"] == 500
    assert result["api_key_id"] == test_setup["api_key_id"]


def test_verify_invalid_key():
    result = verify_subscriber_key("tf_live_invalid", "smart-data-converter")
    assert result is None


def test_verify_wrong_hash(test_setup):
    # Hash of a different key
    wrong_key = generate_api_key()
    result = verify_subscriber_key(wrong_key, "smart-data-converter")
    assert result is None


def test_raise_for_subscriber_key_success(test_setup):
    result = raise_for_subscriber_key(
        test_setup["plaintext_key"], "smart-data-converter"
    )
    assert result["allowed"] is True


def test_raise_for_subscriber_key_invalid():
    with pytest.raises(HTTPException) as exc_info:
        raise_for_subscriber_key("tf_live_invalid", "smart-data-converter")
    assert exc_info.value.status_code == 401


def test_quota_exhaustion(test_setup):
    """
    Exhaust quota (500 free requests) then verify 429.
    Note: This test makes 500 RPC calls. May take a few seconds.
    """
    client = test_setup["client"]
    api_key_id = test_setup["api_key_id"]

    # Manually set usage to 499 for TODAY (faster than 500 calls)
    # NOTE: RPC uses CURRENT_DATE, so we must match it exactly.
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()

    client.table("usage_daily").upsert({
        "api_key_id": api_key_id,
        "subscriber_id": test_setup["subscriber"]["id"],
        "tool_name": "smart-data-converter",
        "date": today,
        "request_count": 499,
    }, on_conflict="api_key_id,date,tool_name").execute()

    # Call 1: should be allowed (uses last slot → 500/500)
    result = verify_subscriber_key(
        test_setup["plaintext_key"], "smart-data-converter"
    )
    assert result["allowed"] is True
    assert result["current_usage"] == 500

    # Call 2: should be rejected — Fair Quota: counter does NOT increment
    result = verify_subscriber_key(
        test_setup["plaintext_key"], "smart-data-converter"
    )
    assert result["allowed"] is False
    # Fair Quota: rejected requests do not consume quota
    assert result["current_usage"] == 500

    # Verify DB counter stayed at 500 (Fair Quota confirmed)
    db_row = (
        client.table("usage_daily")
        .select("request_count")
        .eq("api_key_id", api_key_id)
        .eq("tool_name", "smart-data-converter")
        .execute()
    )
    assert db_row.data[0]["request_count"] == 500

    # Via raise_for_subscriber_key -> 429
    with pytest.raises(HTTPException) as exc_info:
        raise_for_subscriber_key(
            test_setup["plaintext_key"], "smart-data-converter"
        )
    assert exc_info.value.status_code == 429
