import os
os.environ.setdefault("API_KEY", "test-key-local")

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
AUTH = {"X-API-Key": os.environ["API_KEY"]}


def post_html(html):
    return client.post("/convert/html", json={"html": html}, headers=AUTH)


# ===== rowspan =====

def test_rowspan_basic():
    """جدول فيه rowspan. نريد معرفة ما يحدث."""
    html = """
    <table>
        <tr><th>Name</th><th>Dept</th></tr>
        <tr><td rowspan="2">Ali</td><td>Sales</td></tr>
        <tr><td>HR</td></tr>
    </table>
    """
    r = post_html(html)
    print("=" * 60)
    print("TEST: rowspan")
    print(f"status: {r.status_code}")
    print(f"body:   {r.json()}")
    print("=" * 60)
    # لا نؤكد أي نتيجة. نكتشف فقط.


# ===== colspan =====

def test_colspan_basic():
    """جدول فيه colspan."""
    html = """
    <table>
        <tr><th>N</th><th colspan="2">Contact</th></tr>
        <tr><td>Ali</td><td>a@b</td><td>123</td></tr>
    </table>
    """
    r = post_html(html)
    print("=" * 60)
    print("TEST: colspan")
    print(f"status: {r.status_code}")
    print(f"body:   {r.json()}")
    print("=" * 60)


if __name__ == "__main__":
    test_rowspan_basic()
    test_colspan_basic()
