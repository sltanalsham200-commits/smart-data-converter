import os
os.environ.setdefault("API_KEY", "test-key-local")

import asyncio
import httpx
from main import app

AUTH = {"X-API-Key": os.environ["API_KEY"]}
BOUNDARY = "----TestBoundary"


def build_prefix():
    return (
        f"--{BOUNDARY}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="t.csv"\r\n'
        f"Content-Type: text/csv\r\n\r\n"
    ).encode()


def build_suffix():
    return f"\r\n--{BOUNDARY}--\r\n".encode()


def build_body(size_bytes):
    header = b"a,b,c,d,e\n"
    rows = b"1,2,3,4,5\n" * ((size_bytes // 10) + 1)
    return header + rows


def _run_chunked(body, prefix, suffix, chunk_size):
    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            async def gen():
                yield prefix
                for i in range(0, len(body), chunk_size):
                    yield body[i:i+chunk_size]
                yield suffix

            r = await client.post(
                "/convert/csv",
                content=gen(),
                headers={
                    **AUTH,
                    "Content-Type": f"multipart/form-data; boundary={BOUNDARY}",
                },
            )
            return r.status_code
    return asyncio.run(run())


# ===== 1. chunked 1.5MB → 413 =====

def test_chunked_no_content_length_over_1mb():
    body = build_body(1_500_000)
    s = _run_chunked(body, build_prefix(), build_suffix(), chunk_size=65_536)
    assert s == 413, f"expected 413, got {s}"


# ===== 2. Content-Length كبير → 413 (via TestClient) =====

def test_content_length_1_5mb():
    from fastapi.testclient import TestClient
    client = TestClient(app)
    big = build_body(1_500_000)
    r = client.post(
        "/convert/csv",
        files={"file": ("t.csv", big, "text/csv")},
        headers=AUTH,
    )
    assert r.status_code == 413


# ===== 3. chunked 100KB → 200 =====

def test_chunked_under_1mb_ok():
    body = build_body(100_000)
    s = _run_chunked(body, build_prefix(), build_suffix(), chunk_size=8_192)
    assert s == 200, f"expected 200, got {s}"


# ===== 4. Regression: small CSV still works =====

def test_small_csv_still_works():
    from fastapi.testclient import TestClient
    client = TestClient(app)
    r = client.post(
        "/convert/csv",
        files={"file": ("t.csv", "a,b\n1,2", "text/csv")},
        headers=AUTH,
    )
    assert r.status_code == 200


# ===== 5. Regression: 500KB file limit still applies =====

def test_csv_over_500kb_still_413():
    from fastapi.testclient import TestClient
    client = TestClient(app)
    big = build_body(700_000)
    r = client.post(
        "/convert/csv",
        files={"file": ("t.csv", big, "text/csv")},
        headers=AUTH,
    )
    assert r.status_code == 413


# ===== 6. Regression: HTML 500KB limit =====

def test_html_over_500kb_still_413():
    from fastapi.testclient import TestClient
    client = TestClient(app)
    big = "<table><tr><th>A</th></tr><tr><td>" + ("X" * (520 * 1024)) + "</td></tr></table>"
    r = client.post("/convert/html", json={"html": big}, headers=AUTH)
    assert r.status_code == 413


# ===== 7. Regression: small HTML works =====

def test_small_html_still_works():
    from fastapi.testclient import TestClient
    client = TestClient(app)
    small = "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>"
    r = client.post("/convert/html", json={"html": small}, headers=AUTH)
    assert r.status_code == 200
