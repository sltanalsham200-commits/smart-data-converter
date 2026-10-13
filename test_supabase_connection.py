"""
Test Supabase connection via .env.local
Run: python test_supabase_connection.py
"""
import os
from pathlib import Path

# Load .env.local
env_file = Path(__file__).parent / ".env.local"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

print("=" * 60)
print("SUPABASE CONNECTION TEST")
print("=" * 60)

# Check env vars
if not SUPABASE_URL:
    print("❌ SUPABASE_URL not set in .env.local")
    raise SystemExit(1)
if not SUPABASE_SERVICE_KEY:
    print("❌ SUPABASE_SERVICE_KEY not set in .env.local")
    raise SystemExit(1)

print(f"✅ SUPABASE_URL: {SUPABASE_URL[:40]}...")
print(f"✅ SUPABASE_SERVICE_KEY: {SUPABASE_SERVICE_KEY[:20]}...")
print()

# Test connection
try:
    from supabase import create_client
    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    print("✅ Supabase client created")
except Exception as e:
    print(f"❌ Failed to create client: {e}")
    raise SystemExit(1)

# Test read from plans
print()
print("--- Test 1: Read plans ---")
try:
    response = client.table("plans").select("*").execute()
    print(f"✅ plans returned {len(response.data)} rows")
    for p in response.data:
        print(f"   - {p['name']:8s} | {p['display_name']:10s} | {p['price_usd']}$ | {p['max_requests']} req")
except Exception as e:
    print(f"❌ Failed to read plans: {e}")
    raise SystemExit(1)

# Test insert/read/delete (subscriber)
print()
print("--- Test 2: Insert/Delete subscriber ---")
try:
    # Insert
    test_email = "test-connection@tools-forge.internal"
    client.table("subscribers").delete().eq("email", test_email).execute()  # cleanup first
    insert_resp = client.table("subscribers").insert({
        "email": test_email,
        "status": "active"
    }).execute()
    new_id = insert_resp.data[0]["id"]
    print(f"✅ Inserted subscriber: {new_id}")

    # Read back
    read_resp = client.table("subscribers").select("*").eq("id", new_id).execute()
    if not read_resp.data:
        raise Exception("read back failed")
    print(f"✅ Read back: {read_resp.data[0]['email']}")

    # Delete
    client.table("subscribers").delete().eq("id", new_id).execute()
    print(f"✅ Deleted test subscriber")
except Exception as e:
    print(f"❌ Failed: {e}")
    raise SystemExit(1)

print()
print("=" * 60)
print("✅ ALL CONNECTION TESTS PASSED")
print("=" * 60)
