import os
os.environ.setdefault("API_KEY", "test-key-local")

import asyncio
import httpx
from main import app

AUTH = {"X-API-Key": os.environ["API_KEY"]}
BOUNDARY = "----TestBoundary"


def csv_part_bytes(size_bytes):
    """يبني جسم multipart بحجم تقريبي"""
    rows = b"1,2,3,4,5\n" * ((size_bytes // 10) + 1)
    header = b"a,b,c,d,e\n"
    return header + rows


def build_multipart_prefix():
    return (
        f"--{BOUNDARY}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="t.csv"\r\n'
        f"Content-Type: text/csv\r\n\r\n"
    ).encode()


def build_multipart_suffix():
    return f"\r\n--{BOUNDARY}--\r\n".encode()


def test_chunked_no_content_length_over_1mb():
    """multipart chunked بدون Content-Length، بحجم 1.5MB"""
    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            prefix = build_multipart_prefix()
            suffix = build_multipart_suffix()
            body = csv_part_bytes(1_500_000)

            async def gen():
                yield prefix
                # نرسل على دفعات
                chunk = 65_536
                for i in range(0, len(body), chunk):
                    yield body[i:i+chunk]
                yield suffix

            r = await client.post(
                "/convert/csv",
                content=gen(),
                headers={
                    **AUTH,
                    "Content-Type": f"multipart/form-data; boundary={BOUNDARY}",
                },
            )
            return r.status_code, r.text[:200]
    return asyncio.run(run())


def test_multipart_no_cl_under_1mb_ok():
    """multipart chunked صغير (100KB) يجب أن ينجح"""
    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            prefix = build_multipart_prefix()
            suffix = build_multipart_suffix()
            body = csv_part_bytes(100_000)

            async def gen():
                yield prefix
                yield body
                yield suffix

            r = await client.post(
                "/convert/csv",
                content=gen(),
                headers={
                    **AUTH,
                    "Content-Type": f"multipart/form-data; boundary={BOUNDARY}",
                },
            )
            return r.status_code, r.text[:200]
    return asyncio.run(run())


if __name__ == "__main__":
    print("=" * 60)

    s, b = test_chunked_no_content_length_over_1mb()
    print(f"TEST 1 (chunked 1.5MB no CL): status={s}")
    print(f"        body={b}")
    print(f"        {'PASS' if s == 413 else 'FAIL'}")

    print()

    s, b = test_multipart_no_cl_under_1mb_ok()
    print(f"TEST 2 (chunked 100KB): status={s}")
    print(f"        body={b}")
    print(f"        {'PASS' if s == 200 else 'FAIL'}")

    print("=" * 60)
