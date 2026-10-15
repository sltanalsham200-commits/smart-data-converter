/**
 * Tools Forge — Convert Worker
 * CSV/HTML → JSON at Cloudflare edge
 */
const MAX_FILE_SIZE = 500 * 1024;
const MAX_HTML_SIZE = 500 * 1024;
const MAX_REQUEST_SIZE = 1024 * 1024;
const TOOL_NAME = "smart-data-converter";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, X-API-Key",
  "Access-Control-Max-Age": "3600",
};

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...CORS_HEADERS },
  });
}

function errorResponse(status, detail) {
  return jsonResponse({ detail }, status);
}

function corsPreflight() {
  return new Response(null, { status: 204, headers: CORS_HEADERS });
}

async function sha256Hex(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
}

async function authenticate(request, env) {
  const apiKey = request.headers.get("X-API-Key");
  if (!apiKey) return { ok: false, response: errorResponse(401, "مفتاح API مطلوب") };
  if (env.LEGACY_API_KEY && apiKey === env.LEGACY_API_KEY) {
    return { ok: true, legacy: true };
  }
  if (apiKey.startsWith("tf_live_")) {
    const keyHash = await sha256Hex(apiKey);
    return verifyViaSupabase(keyHash, env);
  }
  return { ok: false, response: errorResponse(401, "مفتاح API غير صالح") };
}

async function verifyViaSupabase(keyHash, env) {
  const url = `${env.SUPABASE_URL}/rest/v1/rpc/verify_and_increment`;
  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: {
        "apikey": env.SUPABASE_SERVICE_KEY,
        "Authorization": `Bearer ${env.SUPABASE_SERVICE_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ p_key_hash: keyHash, p_tool: TOOL_NAME }),
    });
    if (!resp.ok) return { ok: false, response: errorResponse(503, "خدمة التحقق غير متاحة") };
    const rows = await resp.json();
    const row = Array.isArray(rows) ? rows[0] : rows;
    if (!row || !row.key_valid) return { ok: false, response: errorResponse(401, "مفتاح API غير صالح") };
    if (row.rate_allowed === false) { return { ok: false, response: errorResponse(429, `rate limit exceeded (${row.rate_current}/${row.rate_limit_per_min} per minute)`) }; }
    if (!row.quota_allowed) {
      return { ok: false, response: errorResponse(429, `تم استنفاد الحصة الشهرية (${row.current_usage}/${row.max_requests})`) };
    }
    return { ok: true, legacy: false, row };
  } catch (e) {
    return { ok: false, response: errorResponse(503, "خدمة التحقق غير متاحة") };
  }
}

function normalizeFieldName(name) {
  if (!name) return "field";
  name = name.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  name = name.trim().replace(/[\s\-.]+/g, "_");
  name = name.replace(/[^\w\u0600-\u06FF]/g, "");
  name = name.replace(/^_+|_+$/g, "").toLowerCase();
  if (name && /^\d/.test(name)) name = "field_" + name;
  return name || "field";
}

function ensureUniqueColumns(columns) {
  const seen = {};
  return columns.map(c => {
    if (seen[c] !== undefined) { seen[c]++; return `${c}_${seen[c]}`; }
    seen[c] = 0;
    return c;
  });
}

const ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩";
function cleanValue(v) {
  if (v === null || v === undefined) return null;
  if (typeof v !== "string") return v;
  let s = v.trim();
  if (["", "-", "N/A", "n/a", "null", "NULL", "None"].includes(s)) return null;
  for (let i = 0; i < ARABIC_DIGITS.length; i++) s = s.split(ARABIC_DIGITS[i]).join(String(i));
  if (s.length > 1 && s.startsWith("0") && !s.startsWith("0.")) return s;
  if (s.length > 10 && /^\d+$/.test(s)) return s;
  if (/^-?\d+$/.test(s)) { const n = parseInt(s, 10); return Number.isSafeInteger(n) ? n : s; }
  if (/^-?\d+\.\d+$/.test(s)) { const f = parseFloat(s); return isFinite(f) ? f : s; }
  return s;
}

function removeDuplicates(records) {
  const seen = new Set();
  const unique = [];
  for (const rec of records) {
    const sig = JSON.stringify(Object.keys(rec).sort().map(k => [k, String(rec[k])]));
    if (!seen.has(sig)) { seen.add(sig); unique.push(rec); }
  }
  return unique;
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let inQuotes = false;
  let i = 0;
  const n = text.length;

  while (i < n) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (i + 1 < n && text[i + 1] === '"') { cell += '"'; i += 2; }
        else { inQuotes = false; i++; }
      } else { cell += ch; i++; }
    } else {
      if (ch === '"') { inQuotes = true; i++; }
      else if (ch === ",") { row.push(cell); cell = ""; i++; }
      else if (ch === "\n") { row.push(cell); rows.push(row); row = []; cell = ""; i++; }
      else if (ch === "\r") {
        if (i + 1 < n && text[i + 1] === "\n") i += 2; else i++;
        row.push(cell); rows.push(row); row = []; cell = "";
      } else { cell += ch; i++; }
    }
  }
  if (inQuotes) throw new Error("Unterminated quoted field");
  if (cell.length > 0 || row.length > 0) { row.push(cell); rows.push(row); }
  return rows;
}

function stripTags(html) {
  return html.replace(/<[^>]*>/g, "").replace(/&nbsp;/g, " ").trim();
}

function decodeEntities(text) {
  return text
    .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&apos;/g, "'");
}

function extractOutermostTable(html) {
  const lower = html.toLowerCase();
  const openTag = "<table";
  const closeTag = "</table>";
  let depth = 0, start = -1, i = 0;
  while (i < lower.length) {
    const oi = lower.indexOf(openTag, i);
    const ci = lower.indexOf(closeTag, i);
    if (oi === -1 && ci === -1) break;
    const nextO = oi === -1 ? Infinity : oi;
    const nextC = ci === -1 ? Infinity : ci;
    if (nextO < nextC) {
      const after = lower[nextO + openTag.length];
      if (after === ">" || after === " " || after === "\t" || after === "\n") {
        if (depth === 0) start = nextO;
        depth++;
      }
      i = nextO + openTag.length;
    } else {
      depth--;
      if (depth === 0 && start >= 0) {
        return html.slice(start, nextC + closeTag.length);
      }
      i = nextC + closeTag.length;
    }
  }
  return null;
}

function stripNestedTables(outerTableHtml) {
  const openEnd = outerTableHtml.indexOf(">");
  if (openEnd === -1) return outerTableHtml;
  const innerContent = outerTableHtml.slice(openEnd + 1, -"</table>".length);
  let cleaned = innerContent;
  let prev = "";
  while (prev !== cleaned) {
    prev = cleaned;
    cleaned = cleaned.replace(/<table[^>]*>[\s\S]*?<\/table>/gi, "");
  }
  return outerTableHtml.slice(0, openEnd + 1) + cleaned + "</table>";
}

function parseHtmlTable(html) {
  html = html.replace(/<(script|style|noscript|iframe)[^>]*>[\s\S]*?<\/\1>/gi, "");
  const outer = extractOutermostTable(html);
  if (!outer) throw new Error("لم يتم العثور على جدول في HTML");
  let tableHtml = outer;
  tableHtml = stripNestedTables(tableHtml).replace(/^<table[^>]*>/i, "").replace(/<\/table>$/i, "");

  const rows = [];
  const rowMatches = tableHtml.match(/<tr[^>]*>([\s\S]*?)<\/tr>/gi) || [];
  for (const rowHtml of rowMatches) {
    const cells = [];
    const cellMatches = rowHtml.match(/<(td|th)[^>]*>([\s\S]*?)<\/\1>/gi) || [];
    for (const cellHtml of cellMatches) {
      const inner = cellHtml.replace(/^<(td|th)[^>]*>/i, "").replace(/<\/(td|th)>$/i, "");
      cells.push(decodeEntities(stripTags(inner)));
    }
    if (cells.length) rows.push(cells);
  }
  if (rows.length < 2) throw new Error("الجدول لا يحتوي على بيانات كافية");
  return rows;
}

async function handleCsv(request, env) {
  const cl = request.headers.get("Content-Length");
  if (cl && parseInt(cl, 10) > MAX_REQUEST_SIZE) {
    return errorResponse(413, "حجم الطلب يتجاوز الحد الأقصى (1 MB)");
  }

  const auth = await authenticate(request, env);
  if (!auth.ok) return auth.response;

  let formData;
  try { formData = await request.formData(); }
  catch { return errorResponse(400, "تعذر قراءة الطلب"); }

  const file = formData.get("file");
  if (!file || typeof file === "string") return errorResponse(400, "الملف مطلوب");
  if (!file.name || !file.name.toLowerCase().endsWith(".csv")) {
    return errorResponse(400, "الملف يجب أن يكون بصيغة CSV");
  }

  const buf = await file.arrayBuffer();
  if (buf.byteLength > MAX_FILE_SIZE) {
    return errorResponse(413, `حجم الملف يتجاوز الحد الأقصى (${MAX_FILE_SIZE / 1024} KB)`);
  }

  let text;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(buf);
    if (text.charCodeAt(0) === 0xFEFF) text = text.slice(1);
  } catch {
    return errorResponse(400, "ترميز الملف غير مدعوم. استخدم UTF-8.");
  }

  if (text.includes("\x00")) return errorResponse(400, "الملف يحتوي على ترميز غير مدعوم.");

  let rawRows;
  try { rawRows = parseCsv(text); }
  catch { return errorResponse(400, "تعذر قراءة ملف CSV. تأكد من صحة صيغة الملف."); }

  if (!rawRows.length || !rawRows[0].length) {
    return errorResponse(400, "لا توجد رؤوس أعمدة");
  }

  // Reject if all headers are empty/whitespace
  if (rawRows[0].every(c => !c || String(c).trim() === "")) {
    return errorResponse(400, "لا توجد رؤوس أعمدة");
  }

  const headers = ensureUniqueColumns(rawRows[0].map(normalizeFieldName));
  const records = [];
  for (let r = 1; r < rawRows.length; r++) {
    const raw = rawRows[r];
    if (!raw || raw.every(c => c === "")) continue;
    const record = {};
    for (let i = 0; i < raw.length; i++) {
      const key = i < headers.length ? headers[i] : `field_${i}`;
      record[key] = cleanValue(raw[i]);
    }
    records.push(record);
  }

  const cleaned = removeDuplicates(records);
  return jsonResponse({
    success: true,
    original_rows: records.length,
    cleaned_rows: cleaned.length,
    duplicates_removed: records.length - cleaned.length,
    columns: cleaned.length ? Object.keys(cleaned[0]) : [],
    data: cleaned,
  });
}

async function handleHtml(request, env) {
  const cl = request.headers.get("Content-Length");
  if (cl && parseInt(cl, 10) > MAX_REQUEST_SIZE) {
    return errorResponse(413, "حجم الطلب يتجاوز الحد الأقصى (1 MB)");
  }

  const auth = await authenticate(request, env);
  if (!auth.ok) return auth.response;

  let body;
  try { body = await request.json(); }
  catch { return errorResponse(400, "تعذر قراءة الطلب"); }

  const html = body && body.html;
  if (!html || typeof html !== "string" || !html.trim()) {
    return errorResponse(400, "HTML فارغ");
  }

  const bytes = new TextEncoder().encode(html).byteLength;
  if (bytes > MAX_HTML_SIZE) {
    return errorResponse(413, `حجم HTML يتجاوز الحد الأقصى (${MAX_HTML_SIZE / 1024} KB)`);
  }

  let grid;
  try { grid = parseHtmlTable(html); }
  catch (e) { return errorResponse(400, e.message || "تعذر قراءة الجدول"); }

  const headers = ensureUniqueColumns(grid[0].map(normalizeFieldName));
  const data = [];
  for (let r = 1; r < grid.length; r++) {
    const raw = grid[r];
    if (!raw || !raw.length) continue;
    const record = {};
    for (let i = 0; i < raw.length; i++) {
      const key = i < headers.length ? headers[i] : `field_${i}`;
      record[key] = cleanValue(raw[i]);
    }
    data.push(record);
  }

  const cleaned = removeDuplicates(data);
  return jsonResponse({
    success: true,
    original_rows: data.length,
    cleaned_rows: cleaned.length,
    duplicates_removed: data.length - cleaned.length,
    columns: cleaned.length ? Object.keys(cleaned[0]) : [],
    data: cleaned,
  });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;

    if (method === "OPTIONS") return corsPreflight();

    if (path === "/health" && method === "GET") {
      return jsonResponse({ status: "ok", worker: "convert" });
    }

    if ((path === "/v1/convert/csv" || path === "/convert/csv") && method === "POST") {
      return handleCsv(request, env);
    }

    if ((path === "/v1/convert/html" || path === "/convert/html") && method === "POST") {
      return handleHtml(request, env);
    }

    return errorResponse(404, "Not Found");
  },
};
