from fastapi.testclient import TestClient
from main import app, normalize_field_name, clean_value

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "endpoints" in response.json()


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


def test_convert_html_simple():
    html = """
    <table>
        <tr><th>Name</th><th>Age</th></tr>
        <tr><td>Ali</td><td>25</td></tr>
        <tr><td>Sara</td><td>30</td></tr>
    </table>
    """
    response = client.post("/convert/html", json={"html": html})
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
    response = client.post("/convert/html", json={"html": html})
    assert response.status_code == 200
    data = response.json()
    assert data["cleaned_rows"] == 2
    assert data["duplicates_removed"] == 1


def test_convert_html_no_table():
    response = client.post("/convert/html", json={"html": "<p>No table here</p>"})
    assert response.status_code == 400


def test_convert_csv():
    csv_content = "Name,Age,City\nAli,25,Damascus\nSara,30,Aleppo\nAli,25,Damascus"
    response = client.post(
        "/convert/csv",
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["cleaned_rows"] == 2
    assert data["duplicates_removed"] == 1
    assert "name" in data["columns"]
