from fastapi import FastAPI, UploadFile, File, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from bs4 import BeautifulSoup
import csv
import io
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional

app = FastAPI(
    title="Smart Data Converter & Cleaner API",
    description="""
## نظرة عامة
يحوّل ملفات CSV و HTML إلى JSON نظيف ومنظم.

## المصادقة
يتطلب كل طلب ترويسة `X-API-Key`.

## الحالات الخاصة المدعومة
- **الأصفار البادئة**: `"00123"` تبقى نصاً (لا تُحوَّل إلى `123`).
- **الأعمدة المكررة**: تُعاد تسميتها (`name`, `name_1`, `name_2`).
- **الأرقام العربية**: `"١٢٣"` → `123`.
- **الصفوف المكررة**: تُحذف تلقائياً.
- **BOM**: تُزال عند القراءة.

## الحالات غير المدعومة حالياً
- `rowspan` / `colspan`: تُعالج كخلايا عادية (قد تفقد بعض البيانات).
- الفاصلة المنقوطة (`;`) كفاصل: تُعامل كعمود واحد.
- جداول متعددة في HTML: يُعالج الجدول الأول فقط.
""",
    version="1.1.0"
)

API_KEY = os.getenv("API_KEY", "")


async def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if not API_KEY:
        return
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح")


class HTMLInput(BaseModel):
    html: str = Field(..., description="كود HTML يحتوي على جدول واحد على الأقل")


def normalize_field_name(name: str) -> str:
    """توحيد أسماء الحقول: مسافات → `_`, أحرف خاصة تُزال."""
    if not name:
        return "field"
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r"[\s\-\.]+", "_", name.strip())
    name = re.sub(r"[^\w\u0600-\u06FF]", "", name)
    name = name.strip("_").lower()
    if name and name[0].isdigit():
        name = "field_" + name
    return name or "field"


def ensure_unique_columns(columns: List[str]) -> List[str]:
    """يضمن عدم تكرار أسماء الأعمدة بإضافة `_1`, `_2`, إلخ."""
    seen = {}
    result = []
    for c in columns:
        if c in seen:
            seen[c] += 1
            result.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 0
            result.append(c)
    return result


def clean_value(value: Any) -> Any:
    """
    تنظيف القيم مع الحفاظ على البيانات الحساسة.
    
    - الأصفار البادئة: تبقى نصاً.
    - الأرقام العربية: تُحوَّل إلى إنجليزية.
    - القيم الفارغة: تصبح None.
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value in ("", "-", "N/A", "n/a", "null", "NULL", "None"):
            return None
        arabic_digits = "٠١٢٣٤٥٦٧٨٩"
        for i, d in enumerate(arabic_digits):
            value = value.replace(d, str(i))
        
        # Preserve leading zeros (IDs, invoice numbers, etc.)
        if len(value) > 1 and value.startswith("0") and not value.startswith("0."):
            return value
        
        # Preserve very long numbers (phone, credit cards)
        if len(value) > 10 and value.isdigit():
            return value
        
        try:
            if "." in value:
                return float(value)
            return int(value)
        except (ValueError, TypeError):
            return value
    return value


def clean_html(html: str) -> str:
    """يزيل وسوم script/style/noscript/iframe."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe"]):
        tag.decompose()
    return str(soup)


def parse_html_table(html: str) -> List[Dict[str, Any]]:
    """يستخرج أول جدول HTML ويحوّله إلى قائمة قواميس."""
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

    headers = ensure_unique_columns(headers)

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
    """يزيل الصفوف المكررة."""
    seen = set()
    unique = []
    for record in records:
        signature = tuple(sorted((k, str(v)) for k, v in record.items()))
        if signature not in seen:
            seen.add(signature)
            unique.append(record)
    return unique


@app.get("/", summary="معلومات API")
def root():
    return {
        "name": "Smart Data Converter & Cleaner API",
        "version": "1.1.0",
        "auth": "required (X-API-Key)",
        "endpoints": {
            "/convert/csv": "POST - رفع ملف CSV",
            "/convert/html": "POST - إرسال HTML",
            "/health": "GET - فحص الحالة"
        }
    }


@app.get("/health", summary="فحص الحالة")
def health():
    return {"status": "ok"}


@app.post("/convert/csv", summary="تحويل CSV إلى JSON")
async def convert_csv(file: UploadFile = File(...), x_api_key: Optional[str] = Header(None)):
    """
    يستقبل ملف CSV ويعيده JSON نظيفاً.
    
    - يحذف الصفوف المكررة.
    - يوحّد أسماء الأعمدة.
    - يحافظ على الأصفار البادئة.
    """
    await verify_api_key(x_api_key)
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="الملف يجب أن يكون بصيغة CSV")

    try:
        content = await file.read()
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1")

        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise HTTPException(status_code=400, detail="لا توجد رؤوس أعمدة")

        normalized_headers = ensure_unique_columns(
            [normalize_field_name(h) for h in reader.fieldnames]
        )

        records = []
        for row in reader:
            record = {}
            for original_key, normalized_key in zip(reader.fieldnames, normalized_headers):
                record[normalized_key] = clean_value(row.get(original_key))
            records.append(record)
    except HTTPException:
        raise
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


@app.post("/convert/html", summary="تحويل HTML إلى JSON")
async def convert_html(payload: HTMLInput, x_api_key: Optional[str] = Header(None)):
    """
    يستقبل HTML ويعيد أول جدول كـ JSON نظيف.
    
    - يزيل script/style/iframe.
    - يفكّ كيانات HTML (`&amp;` → `&`).
    - يحافظ على الأصفار البادئة.
    """
    await verify_api_key(x_api_key)
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
