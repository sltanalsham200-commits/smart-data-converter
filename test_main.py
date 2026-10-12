import os

from fastapi.testclient import TestClient

# Set a test API key BEFORE importing main
os.environ.setdefault("API_KEY", "test-key-local")

from main import app, normalize_field_name, clean_value  # noqa: E402

client = TestClient(app)

TEST_KEY = os.environ["API_KEY"]
AUTH = {"X-API-Key": TEST_KEY}


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "endpoints" in response.json()


def test_missing_key_returns_401():
    response = client.post(
        "/convert/html",
        json={"html": "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>"},
    )
    assert response.status_code == 401


def test_wrong_key_returns_401():
    response = client.post(
        "/convert/html",
        json={"html": "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>"},
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401


def test_normalize_field_name():
    assert normalize_field_name("First Name") == "first_name"
    assert normalize_field_name("  العميل  ") == "العميل"
    assert normalize_field_name("2nd Column") == "field_2nd_column"
    assert normalize_field_name("Price ($)") == "price"


def test_clean_value():
    assert clean_value("  hello  ") == "hello"
    assert clean_value("") is None
    assert clean_value("N/A") is None
    assert clean_value("١٢٣") == 123
    assert clean_value("45.5") == 45.5
    # Leading zeros preserved
    assert clean_value("00123") == "00123"
    # Long numeric strings preserved
    assert clean_value("1234567890123") == "1234567890123"


def test_convert_html_simple():
    html = """
    <table>
        <tr><th>Name</th><th>Age</th></tr>
        <tr><td>Ali</td><td>25</td></tr>
        <tr><td>Sara</td><td>30</td></tr>
    </table>
    """
    response = client.post("/convert/html", json={"html": html}, headers=AUTH)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["cleaned_rows"] == 2
    assert data["data"][0]["name"] == "Ali"
    assert data["data"][0]["age"] == 25


def test_convert_html_with_duplicates():
    html = """
    <table>
        <tr><th>City</th></tr>
        <tr><td>Damascus</td></tr>
        <tr><td>Damascus</td></tr>
        <tr><td>Aleppo</td></tr>
    </table>
    """
    response = client.post("/convert/html", json={"html": html}, headers=AUTH)
    assert response.status_code == 200
    data = response.json()
    assert data["cleaned_rows"] == 2
    assert data["duplicates_removed"] == 1


def test_convert_html_no_table():
    response = client.post(
        "/convert/html", json={"html": "<p>No table here</p>"}, headers=AUTH
    )
    assert response.status_code == 400


def test_convert_html_too_large():
    """HTML > 500KB must return 413."""
    big = "<table><tr><th>A</th></tr><tr><td>" + ("X" * (520 * 1024)) + "</td></tr></table>"
    response = client.post("/convert/html", json={"html": big}, headers=AUTH)
    assert response.status_code == 413


def test_convert_csv():
    csv_content = "Name,Age,City\nAli,25,Damascus\nSara,30,Aleppo\nAli,25,Damascus"
    response = client.post(
        "/convert/csv",
        files={"file": ("test.csv", csv_content, "text/csv")},
        headers=AUTH,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["cleaned_rows"] == 2
    assert data["duplicates_removed"] == 1
    assert "name" in data["columns"]


def test_convert_csv_too_large():
    """CSV > 500KB must return 413."""
    header = "a,b,c,d,e\n"
    row = "1,2,3,4,5\n"
    big_csv = header + (row * 60000)  # ~ 600KB
    response = client.post(
        "/convert/csv",
        files={"file": ("big.csv", big_csv, "text/csv")},
        headers=AUTH,
    )
    assert response.status_code == 413


def test_csv_wrong_extension():
    response = client.post(
        "/convert/csv",
        files={"file": ("data.txt", "a,b\n1,2", "text/plain")},
        headers=AUTH,
    )
    assert response.status_code == 400


def test_csv_error_message_no_leak():
    """Error messages must not leak internal file paths or tracebacks."""
    response = client.post(
        "/convert/csv",
        files={"file": ("data.csv", 'a,b\n"unclosed,2', "text/csv")},
        headers=AUTH,
    )
    body = response.text
    for marker in ["Traceback", "File \"", "site-packages", "/data/", "main.py"]:
        assert marker not in body, f"Leaked: {marker}"
