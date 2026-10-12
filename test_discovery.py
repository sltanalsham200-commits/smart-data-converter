import os
os.environ.setdefault("API_KEY", "test-key-local")

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
AUTH = {"X-API-Key": os.environ["API_KEY"]}


def post_html(html):
    return client.post("/convert/html", json={"html": html}, headers=AUTH)


def post_csv(content):
    return client.post(
        "/convert/csv",
        files={"file": ("t.csv", content, "text/csv")},
        headers=AUTH,
    )


def show(title, r):
    print("=" * 60)
    print(f"TEST: {title}")
    print(f"status: {r.status_code}")
    try:
        print(f"body:   {r.json()}")
    except Exception:
        print(f"body:   {r.text[:300]}")
    print("=" * 60)
    print()


# 1. rowspan
show("rowspan", post_html("""
<table>
  <tr><th>Name</th><th>Dept</th></tr>
  <tr><td rowspan="2">Ali</td><td>Sales</td></tr>
  <tr><td>HR</td></tr>
</table>
"""))

# 2. colspan
show("colspan", post_html("""
<table>
  <tr><th>N</th><th colspan="2">Contact</th></tr>
  <tr><td>Ali</td><td>a@b</td><td>123</td></tr>
</table>
"""))

# 3. emoji + RTL
show("emoji + RTL", post_html("""
<table>
  <tr><th>Name</th><th>Note</th></tr>
  <tr><td>محمد</td><td>مرحباً 👋</td></tr>
  <tr><td>Sara</td><td>Test 🇸🇾</td></tr>
</table>
"""))

# 4. huge single cell (~600KB) — over 500KB file limit for HTML
big_cell = "X" * (600 * 1024)
show("huge single cell (600KB)", post_html(
    f"<table><tr><th>A</th></tr><tr><td>{big_cell}</td></tr></table>"
))

# 5. CSV with newlines inside quoted cell
show("CSV newline in quoted cell", post_csv('a,b\n"line1\nline2",2'))

# 6. CSV with huge single cell (~100KB under limit)
huge_val = "Y" * (100 * 1024)
show("CSV huge cell (100KB)", post_csv(f'a\n{huge_val}'))

# 7. multiple HTML tables
show("multiple tables", post_html("""
<table><tr><th>A</th></tr><tr><td>1</td></tr></table>
<table><tr><th>B</th></tr><tr><td>2</td></tr></table>
"""))

# 8. nested table
show("nested table", post_html("""
<table>
  <tr><th>Outer</th></tr>
  <tr><td><table><tr><td>Inner</td></tr></table></td></tr>
</table>
"""))
