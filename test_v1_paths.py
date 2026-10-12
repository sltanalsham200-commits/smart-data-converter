import os
os.environ.setdefault("API_KEY", "test-key-local")

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
AUTH = {"X-API-Key": os.environ["API_KEY"]}
HTML = "<table><tr><th>N</th></tr><tr><td>Ali</td></tr></table>"


def test_v1_health():
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_legacy_health_still_works():
    r = client.get("/health")
    assert r.status_code == 200


def test_v1_root():
    r = client.get("/v1/")
    assert r.status_code == 200


def test_v1_convert_html():
    r = client.post("/v1/convert/html", json={"html": HTML}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["data"][0]["n"] == "Ali"


def test_legacy_convert_html_still_works():
    r = client.post("/convert/html", json={"html": HTML}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["data"][0]["n"] == "Ali"


def test_v1_convert_csv():
    content = "name,age\nAli,25"
    r = client.post(
        "/v1/convert/csv",
        files={"file": ("t.csv", content, "text/csv")},
        headers=AUTH,
    )
    assert r.status_code == 200
    assert r.json()["data"][0]["name"] == "Ali"


def test_v1_requires_api_key():
    r = client.post("/v1/convert/html", json={"html": HTML})
    assert r.status_code == 401


def test_v1_size_limit_applies():
    big = "<table><tr><th>A</th></tr><tr><td>" + ("X" * (520 * 1024)) + "</td></tr></table>"
    r = client.post("/v1/convert/html", json={"html": big}, headers=AUTH)
    assert r.status_code == 413
