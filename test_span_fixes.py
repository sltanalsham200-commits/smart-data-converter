import os
os.environ.setdefault("API_KEY", "test-key-local")

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
AUTH = {"X-API-Key": os.environ["API_KEY"]}


def post_html(html):
    return client.post("/convert/html", json={"html": html}, headers=AUTH)


def test_rowspan_aligns_correctly():
    html = """
    <table>
        <tr><th>Name</th><th>Dept</th></tr>
        <tr><td rowspan="2">Ali</td><td>Sales</td></tr>
        <tr><td>HR</td></tr>
    </table>
    """
    r = post_html(html)
    assert r.status_code == 200
    j = r.json()
    assert j["columns"] == ["name", "dept"]
    assert j["data"] == [
        {"name": "Ali", "dept": "Sales"},
        {"name": "Ali", "dept": "HR"},
    ]


def test_colspan_names_are_numbered():
    html = """
    <table>
        <tr><th>N</th><th colspan="2">Contact</th></tr>
        <tr><td>Ali</td><td>a@b</td><td>123</td></tr>
    </table>
    """
    r = post_html(html)
    assert r.status_code == 200
    j = r.json()
    assert j["columns"] == ["n", "contact", "contact_1"]
    assert j["data"][0]["contact"] == "a@b"
    assert j["data"][0]["contact_1"] == 123


def test_nested_table_removed():
    html = """
    <table>
        <tr><th>Outer</th></tr>
        <tr><td><table><tr><td>Inner</td></tr></table></td></tr>
    </table>
    """
    r = post_html(html)
    assert r.status_code == 200
    j = r.json()
    assert j["columns"] == ["outer"]
    for row in j["data"]:
        assert "Inner" not in str(row)


def test_huge_colspan_capped():
    html = '<table><tr><th>A</th></tr><tr><td colspan="999999">X</td></tr></table>'
    r = post_html(html)
    assert r.status_code == 200
    cols = r.json()["columns"]
    assert len(cols) <= 100
