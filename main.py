import csv
import io
import logging
import os
import re
import secrets
import unicodedata
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# FAIL-FAST: refuse to start if API_KEY is missing or empty.
# ---------------------------------------------------------------------------
API_KEY = os.getenv("API_KEY", "").strip()

if not API_KEY:
    logging.basicConfig(level=logging.ERROR)
    logging.error("=" * 60)
    logging.error("SECURITY CONFIGURATION ERROR")
    logging.error("=" * 60)
    logging.error("Environment variable API_KEY is not set or empty.")
    logging.error("The service will NOT start.")
    logging.error("Set API_KEY in Render environment variables and redeploy.")
    logging.error("=" * 60)
    raise RuntimeError("API_KEY environment variable is required")

# ---------------------------------------------------------------------------
# Documented size limits.
# ---------------------------------------------------------------------------
MAX_FILE_SIZE = 500 * 1024
MAX_HTML_SIZE = 500 * 1024

logger = logging.getLogger("smart_data_converter")

MAX_REQUEST_SIZE = 1024 * 1024  # 1 MB hard cap for Content-Length


class SizeLimitMiddleware:
    """Pure ASGI middleware: enforces a max request body size, including
    chunked/streamed requests without Content-Length.

    The body is counted as it is received; if it exceeds the limit, the
    response is replaced with a 413 payload, regardless of what the
    endpoint tries to return."""

    def __init__(self, app, max_size: int = MAX_REQUEST_SIZE):
        self.app = app
        self.max_size = max_size

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        if not (path.startswith("/convert/") or path.startswith("/v1/convert/")):
            return await self.app(scope, receive, send)

        # Fast path: reject based on Content-Length if present
        headers = dict(scope.get("headers", []))
        cl = headers.get(b"content-length")
        if cl is not None:
            try:
                if int(cl) > self.max_size:
                    return await self._reply(send, 413,
                        "حجم الطلب يتجاوز الحد الأقصى (1 MB)")
            except (ValueError, TypeError):
                return await self._reply(send, 400,
                    "قيمة Content-Length غير صالحة")

        # Slow path: count bytes as they arrive
        bytes_seen = 0
        over_limit = False

        async def limited_receive():
            nonlocal bytes_seen, over_limit
            msg = await receive()
            if msg.get("type") == "http.request":
                body = msg.get("body", b"")
                bytes_seen += len(body)
                if bytes_seen > self.max_size:
                    over_limit = True
                    return {"type": "http.request",
                            "body": b"",
                            "more_body": False}
            return msg

        response_sent = False

        async def limited_send(msg):
            nonlocal response_sent
            if over_limit and not response_sent:
                response_sent = True
                await self._reply(send, 413,
                    "حجم الطلب يتجاوز الحد الأقصى (1 MB)")
                return
            if response_sent:
                return
            await send(msg)

        await self.app(scope, limited_receive, limited_send)

    async def _reply(self, send, status: int, detail: str):
        body = ('{"detail":"' + detail + '"}').encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})


app = FastAPI(
    title="Smart Data Converter & Cleaner API",
    description=(
        "يحوّل ملفات CSV و HTML إلى JSON نظيف ومنظم.\n\n"
        "**المصادقة**: كل طلب يحتاج ترويسة `X-API-Key`.\n\n"
        "**الحد الأقصى**: 500 KB للملف أو لمحتوى HTML.\n\n"
        "**الحالات المدعومة**: أصفار بادئة، أرقام عربية، أعمدة مكررة، BOM.\n\n"
        "**غير مدعوم**: rowspan/colspan، الفاصلة المنقوطة، جداول متعددة."
    ),
    version="1.1.3",
)

app.add_middleware(SizeLimitMiddleware, max_size=MAX_REQUEST_SIZE)


class HTMLInput(BaseModel):
    html: str = Field(..., description="كود HTML يحتوي على جدول")


async def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if not x_api_key or not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح")


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


def ensure_unique_columns(columns: List[str]) -> List[str]:
    seen: Dict[str, int] = {}
    result: List[str] = []
    for c in columns:
        if c in seen:
            seen[c] += 1
            result.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 0
            result.append(c)
    return result


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
        if len(value) > 1 and value.startswith("0") and not value.startswith("0."):
            return value
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
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe"]):
        tag.decompose()
    return str(soup)


def _safe_span(cell, attr: str, cap: int = 100) -> int:
    """قراءة آمنة لـ colspan/rowspan مع حد أعلى لمنع DoS."""
    try:
        n = int(cell.get(attr, "1"))
        return max(1, min(n, cap))
    except (ValueError, TypeError):
        return 1


def _strip_nested_tables(table) -> int:
    """يزيل الجداول المتداخلة. يعيد عدد الجداول التي أُزيلت."""
    nested = table.find_all("table")
    for n in nested:
        if n is not table:
            n.decompose()
    return len(nested)


def parse_html_table(html: str) -> List[Dict[str, Any]]:
    """يحوّل أول جدول HTML إلى JSON مع دعم rowspan و colspan."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        raise HTTPException(status_code=400, detail="لم يتم العثور على جدول في HTML")

    # إزالة الجداول المتداخلة لمنع خلط البيانات
    _strip_nested_tables(table)

    rows = table.find_all("tr")
    if len(rows) < 2:
        raise HTTPException(status_code=400, detail="الجدول لا يحتوي على بيانات كافية")

    grid: List[List[str]] = []
    active_spans: Dict[int, List[Any]] = {}

    for row in rows:
        cells = row.find_all(["td", "th"])
        current: List[str] = []
        col = 0

        for cell in cells:
            # إدراج خلايا rowspan النشطة
            while col in active_spans:
                text, remaining = active_spans[col]
                current.append(text)
                if remaining <= 1:
                    del active_spans[col]
                else:
                    active_spans[col] = [text, remaining - 1]
                col += 1

            text = cell.get_text()
            colspan = _safe_span(cell, "colspan")
            rowspan = _safe_span(cell, "rowspan")

            for k in range(colspan):
                current.append(text)
                if rowspan > 1:
                    active_spans[col + k] = [text, rowspan - 1]
            col += colspan

        # إدراج rowspan المتبقية في نهاية الصف
        while col in active_spans:
            text, remaining = active_spans[col]
            current.append(text)
            if remaining <= 1:
                del active_spans[col]
            else:
                active_spans[col] = [text, remaining - 1]
            col += 1

        grid.append(current)

    if not grid or not grid[0]:
        raise HTTPException(status_code=400, detail="الجدول لا يحتوي على بيانات كافية")

    headers = ensure_unique_columns([normalize_field_name(h) for h in grid[0]])

    data: List[Dict[str, Any]] = []
    for raw_row in grid[1:]:
        if not raw_row:
            continue
        record: Dict[str, Any] = {}
        for i, val in enumerate(raw_row):
            key = headers[i] if i < len(headers) else f"field_{i}"
            record[key] = clean_value(val)
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


@app.get("/", summary="معلومات API")
@app.get("/v1", include_in_schema=False)
@app.get("/v1/", summary="معلومات API (v1)")
def root():
    return {
        "name": "Smart Data Converter & Cleaner API",
        "version": "1.1.3",
        "auth": "required (X-API-Key)",
        "limits": {"max_file_bytes": MAX_FILE_SIZE, "max_html_bytes": MAX_HTML_SIZE},
        "endpoints": {
            "/convert/csv": "POST",
            "/convert/html": "POST",
            "/health": "GET",
        },
    }


@app.get("/health", summary="فحص الحالة")
@app.get("/v1/health", summary="فحص الحالة (v1)")
def health():
    return {"status": "ok"}


@app.post("/convert/csv", summary="تحويل CSV إلى JSON")
@app.post("/v1/convert/csv", summary="تحويل CSV إلى JSON (v1)")
async def convert_csv(
    file: UploadFile = File(...),
    x_api_key: Optional[str] = Header(None),
):
    await verify_api_key(x_api_key)

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="الملف يجب أن يكون بصيغة CSV")

    try:
        content = await file.read()
    except Exception:
        logger.exception("Failed to read uploaded file")
        raise HTTPException(status_code=400, detail="تعذر قراءة الملف المرفوع")

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"حجم الملف يتجاوز الحد الأقصى ({MAX_FILE_SIZE // 1024} KB)",
        )

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="ترميز الملف غير مدعوم. استخدم UTF-8.",
        )

    if "\x00" in text:
        raise HTTPException(
            status_code=400,
            detail="الملف يحتوي على ترميز غير مدعوم.",
        )

    try:
        reader = csv.reader(io.StringIO(text), strict=True)
        raw_rows = list(reader)
    except csv.Error:
        raise HTTPException(
            status_code=400,
            detail="تعذر قراءة ملف CSV. تأكد من صحة صيغة الملف.",
        )
    except Exception:
        logger.exception("CSV parsing failed")
        raise HTTPException(
            status_code=400,
            detail="تعذر قراءة ملف CSV. تأكد من صحة صيغة الملف.",
        )

    if not raw_rows or not raw_rows[0]:
        raise HTTPException(status_code=400, detail="لا توجد رؤوس أعمدة")

    normalized_headers = ensure_unique_columns(
        [normalize_field_name(h) for h in raw_rows[0]]
    )

    records = []
    for raw in raw_rows[1:]:
        if not raw:
            continue
        record = {}
        for i, val in enumerate(raw):
            key = normalized_headers[i] if i < len(normalized_headers) else f"field_{i}"
            record[key] = clean_value(val)
        records.append(record)

    cleaned = remove_duplicates(records)

    return JSONResponse({
        "success": True,
        "original_rows": len(records),
        "cleaned_rows": len(cleaned),
        "duplicates_removed": len(records) - len(cleaned),
        "columns": list(cleaned[0].keys()) if cleaned else [],
        "data": cleaned,
    })


@app.post("/convert/html", summary="تحويل HTML إلى JSON")
@app.post("/v1/convert/html", summary="تحويل HTML إلى JSON (v1)")
async def convert_html(
    payload: HTMLInput,
    x_api_key: Optional[str] = Header(None),
):
    await verify_api_key(x_api_key)

    if not payload.html or not payload.html.strip():
        raise HTTPException(status_code=400, detail="HTML فارغ")

    html_bytes = payload.html.encode("utf-8")
    if len(html_bytes) > MAX_HTML_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"حجم HTML يتجاوز الحد الأقصى ({MAX_HTML_SIZE // 1024} KB)",
        )

    try:
        cleaned_html = clean_html(payload.html)
        records = parse_html_table(cleaned_html)
    except HTTPException:
        raise
    except Exception:
        logger.exception("HTML parsing failed")
        raise HTTPException(
            status_code=400,
            detail="تعذر تحليل HTML. تأكد من صحة الصيغة.",
        )

    cleaned = remove_duplicates(records)

    return JSONResponse({
        "success": True,
        "original_rows": len(records),
        "cleaned_rows": len(cleaned),
        "duplicates_removed": len(records) - len(cleaned),
        "columns": list(cleaned[0].keys()) if cleaned else [],
        "data": cleaned,
    })
