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


def csv_post_bytes(content, filename="t.csv"):
    return client.post(
        "/convert/csv",
        files={"file": (filename, content, "text/csv")},
        headers=AUTH,
    )


# ===== 1. Duplicate headers: data preservation =====

def test_dup_headers_preserve_values():
    """name,name,age / Ali,Bob,25 → Ali in name, Bob in name_1"""
    r = csv_post("name,name,age\nAli,Bob,25")
    assert r.status_code == 200, f"status={r.status_code}"
    j = r.json()
    assert j["columns"] == ["name", "name_1", "age"], f"cols={j['columns']}"
    rec = j["data"][0]
    assert rec["name"] == "Ali", f"got {rec}"
    assert rec["name_1"] == "Bob", f"got {rec}"
    assert rec["age"] == 25


def test_triple_dup_headers():
    """a,a,a / 1,2,3 → a=1, a_1=2, a_2=3"""
    r = csv_post("a,a,a\n1,2,3")
    assert r.status_code == 200
    j = r.json()
    assert j["columns"] == ["a", "a_1", "a_2"]
    rec = j["data"][0]
    assert rec["a"] == 1
    assert rec["a_1"] == 2
    assert rec["a_2"] == 3


# ===== 2. Encoding =====

def test_utf8_arabic_accepted():
    content = "الاسم,العمر\nمحمد,25".encode("utf-8")
    r = csv_post_bytes(content)
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:150]}"
    j = r.json()
    assert j["data"][0].get("الاسم") == "محمد"


def test_utf8_bom_stripped():
    content = "\ufeffname,age\nAli,25".encode("utf-8")
    r = csv_post_bytes(content)
    assert r.status_code == 200
    assert r.json()["columns"] == ["name", "age"]


def test_invalid_encoding_rejected():
    """UTF-16-LE bytes must NOT be silently accepted as garbage."""
    content = "name,age\nAli,25".encode("utf-16-le")
    r = csv_post_bytes(content)
    assert r.status_code == 400, f"got {r.status_code}, body={r.text[:200]}"


# ===== 3. Deduplication =====

def test_dedup_identical_rows():
    r = csv_post("a,b\nx,y\nx,y\nz,w")
    assert r.status_code == 200
    j = r.json()
    assert j["cleaned_rows"] == 2
    assert j["duplicates_removed"] == 1


def test_dedup_distinct_rows_preserved():
    """Distinct rows must never be merged."""
    r = csv_post("a\n1\n2\n01\n1.0\nABC")
    assert r.status_code == 200
    j = r.json()
    # 1(int), 2(int), "01"(str), 1.0(float), "ABC"(str) → 5 distinct
    assert j["cleaned_rows"] == 5, f"got {j['cleaned_rows']}, data={j['data']}"


# ===== 4. Size limits =====

def test_csv_oversize_413():
    row = "1,2,3,4,5\n"
    big = "a,b,c,d,e\n" + (row * 60000)
    r = csv_post(big)
    assert r.status_code == 413, f"got {r.status_code}"


def test_html_oversize_413():
    big = "<table><tr><th>A</th></tr><tr><td>" + ("X" * (520 * 1024)) + "</td></tr></table>"
    r = client.post("/convert/html", json={"html": big}, headers=AUTH)
    assert r.status_code == 413


# ===== 5. Regression =====

def test_simple_csv_still_works():
    r = csv_post("Name,Age\nAli,25\nSara,30")
    assert r.status_code == 200
    j = r.json()
    assert j["cleaned_rows"] == 2


def test_leading_zeros_still_preserved():
    r = csv_post("Code\n00123\n00456")
    assert r.status_code == 200
    j = r.json()
    assert j["data"][0]["code"] == "00123"
    assert j["data"][1]["code"] == "00456"
