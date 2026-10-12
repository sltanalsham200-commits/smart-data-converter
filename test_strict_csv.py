import os

os.environ.setdefault("API_KEY", "test-key-local")

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
AUTH = {"X-API-Key": os.environ["API_KEY"]}


def csv_post(content, filename="t.csv"):
    return client.post(
        "/convert/csv",
        files={"file": (filename, content, "text/csv")},
        headers=AUTH,
    )


# ===== CORRUPT CSV: must be rejected with 400 =====

def test_corrupt_unclosed_quote():
    r = csv_post('a,b\n"unclosed,2')
    assert r.status_code == 400, f"got {r.status_code} body={r.text[:150]}"


def test_corrupt_unclosed_quote_at_eof():
    r = csv_post('a,b\nfoo,"bar')
    assert r.status_code == 400, f"got {r.status_code} body={r.text[:150]}"


def test_corrupt_chars_after_closing_quote():
    r = csv_post('a,b\n"foo"bar,2')
    assert r.status_code == 400, f"got {r.status_code} body={r.text[:150]}"


# ===== VALID CSV: must be accepted with 200 =====

def test_valid_comma_in_quotes():
    r = csv_post('a,b\n"hello, world",2')
    assert r.status_code == 200, f"got {r.status_code}"
    assert r.json()["data"][0]["a"] == "hello, world"


def test_valid_escaped_quotes():
    r = csv_post('a,b\n"say ""hi""",2')
    assert r.status_code == 200
    assert "hi" in r.json()["data"][0]["a"]


def test_valid_newline_in_quoted():
    r = csv_post('a,b\n"line1\nline2",2')
    assert r.status_code == 200
    assert "line1" in r.json()["data"][0]["a"]


def test_valid_standard_quoted():
    r = csv_post('a,b\n"x","y"')
    assert r.status_code == 200


# ===== ERROR HYGIENE =====

def test_corrupt_no_internal_leak():
    r = csv_post('a,b\n"unclosed,2')
    body = r.text
    for marker in ["Traceback", "site-packages", "main.py", "/data/"]:
        assert marker not in body, f"leaked marker: {marker}"
