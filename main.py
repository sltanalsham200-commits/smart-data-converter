from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from bs4 import BeautifulSoup
import csv
import io
import re
import unicodedata
from typing import Any, Dict, List

app = FastAPI(
    title="Smart Data Converter & Cleaner API",
    description="يحوّل بيانات CSV و HTML إلى JSON نظيف ومنظم",
    version="1.0.0"
)


class HTMLInput(BaseModel):
    html: str


def normalize_field_name(name: str) -> str:
    if not name:
        return "field"
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r"[\s\-\.]+", "_", name.strip())
    name = re.sub(r"[^\w\u0600-\u06FF]", "", name)
    name = name.strip("_").lower()
    if name and name[0].isdigit():
        name = "field_" + name
    return name or "field"


def clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value in ("", "-", "N/A", "n/a", "null", "NULL", "None"):
            return None
        arabic_digits = "٠١٢٣٤٥٦٧٨٩"
        for i, d in enumerate(arabic_digits):
            value = value.replace(d, str(i))
        try:
            if "." in value:
                return float(value)
            return int(value)
        except (ValueError, TypeError):
            return value
    return value


def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe"]):
        tag.decompose()
    return str(soup)


def parse_html_table(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        raise HTTPException(status_code=400, detail="لم يتم العثور على جدول في HTML")

    rows = table.find_all("tr")
    if len(rows) < 2:
        raise HTTPException(status_code=400, detail="الجدول لا يحتوي على بيانات كافية")

    headers = []
    header_cells = rows[0].find_all(["th", "td"])
    for cell in header_cells:
        headers.append(normalize_field_name(cell.get_text()))

    data = []
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        record = {}
        for i, cell in enumerate(cells):
            key = headers[i] if i < len(headers) else f"field_{i}"
            record[key] = clean_value(cell.get_text())
        data.append(record)
    return data


def remove_duplicates(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique = []
    for record in records:
        signature = tuple(sorted((k, str(v)) for k, v in record.items()))
        if signature not in seen:
            seen.add(signature)
            unique.append(record)
    return unique


@app.get("/")
def root():
    return {
        "name": "Smart Data Converter & Cleaner API",
        "version": "1.0.0",
        "endpoints": {
            "/convert/csv": "POST - رفع ملف CSV وتحويله إلى JSON",
            "/convert/html": "POST - إرسال HTML وتحويل جدوله إلى JSON",
            "/health": "GET - فحص حالة الخدمة"
        }
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/convert/csv")
async def convert_csv(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="الملف يجب أن يكون بصيغة CSV")

    try:
        content = await file.read()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")

        reader = csv.DictReader(io.StringIO(text))
        records = []
        for row in reader:
            record = {normalize_field_name(k): clean_value(v) for k, v in row.items()}
            records.append(record)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"خطأ في قراءة CSV: {str(e)}")

    cleaned = remove_duplicates(records)

    return JSONResponse({
        "success": True,
        "original_rows": len(records),
        "cleaned_rows": len(cleaned),
        "duplicates_removed": len(records) - len(cleaned),
        "columns": list(cleaned[0].keys()) if cleaned else [],
        "data": cleaned
    })


@app.post("/convert/html")
async def convert_html(payload: HTMLInput):
    if not payload.html.strip():
        raise HTTPException(status_code=400, detail="HTML فارغ")

    cleaned_html = clean_html(payload.html)
    records = parse_html_table(cleaned_html)
    cleaned = remove_duplicates(records)

    return JSONResponse({
        "success": True,
        "original_rows": len(records),
        "cleaned_rows": len(cleaned),
        "duplicates_removed": len(records) - len(cleaned),
        "columns": list(cleaned[0].keys()) if cleaned else [],
        "data": cleaned
    })
