#!/usr/bin/env bash
# ============================================================
# Tools Forge — Database Backup Script
# Runs in GitHub Actions. Outputs encrypted backup.
# ============================================================
set -euo pipefail
# ---- Failure reporter: send tail to Telegram ----
LOG_FILE="$(mktemp)"
exec > >(tee -a "${LOG_FILE}") 2>&1

on_fail() {
  local code=$?
  if [ $code -ne 0 ]; then
    local tail_text
    tail_text="$(tail -15 "${LOG_FILE}" | sed 's|postgresql://[^ ]*|[REDACTED]|g' | tr '\n' '|')"
    if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
      curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        --data-urlencode "text=Backup FAILED exit ${code}

${tail_text}" > /dev/null || true
    fi
  fi
}
trap on_fail EXIT
# ---- Validate required env vars ----
: "${SUPABASE_DB_URL:?missing SUPABASE_DB_URL}"
: "${AGE_PUBLIC_KEY:?missing AGE_PUBLIC_KEY}"
: "${TELEGRAM_BOT_TOKEN:?missing TELEGRAM_BOT_TOKEN}"
: "${TELEGRAM_CHAT_ID:?missing TELEGRAM_CHAT_ID}"

# ---- Paths ----
TS=$(date -u +'%Y-%m-%d-%H%M')
OUT_DIR="backup_out"
mkdir -p "${OUT_DIR}"
PLAIN="${OUT_DIR}/db-${TS}.sql"
GZ="${PLAIN}.gz"
ENC="${GZ}.age"

echo "==> Starting backup at ${TS}"

# ---- 1. Dump ----
echo "==> pg_dump..."
pg_dump \
  --no-owner \
  --no-privileges \
  --clean \
  --if-exists \
  "${SUPABASE_DB_URL}" > "${PLAIN}"

# ---- 2. Sanity check ----
echo "==> Verifying dump..."
SIZE=$(wc -c < "${PLAIN}")
if [ "${SIZE}" -lt 5000 ]; then
  echo "ERROR: dump too small (${SIZE} bytes) — aborting"
  exit 1
fi
if ! grep -q "CREATE TABLE" "${PLAIN}"; then
  echo "ERROR: dump has no CREATE TABLE — aborting"
  exit 1
fi
TABLE_COUNT=$(grep -c "^CREATE TABLE" "${PLAIN}" || true)
echo "    size=${SIZE} bytes, tables=${TABLE_COUNT}"

# ---- 3. Compress ----
echo "==> gzip..."
gzip -9 "${PLAIN}"
if ! gzip -t "${GZ}"; then
  echo "ERROR: gzip integrity check failed"
  exit 1
fi

# ---- 4. Encrypt with age ----
echo "==> age encrypt..."
age --encrypt --recipient "${AGE_PUBLIC_KEY}" --output "${ENC}" "${GZ}"

# ---- 5. Final check ----
ENC_SIZE=$(wc -c < "${ENC}")
if [ "${ENC_SIZE}" -lt 1000 ]; then
  echo "ERROR: encrypted file too small (${ENC_SIZE} bytes)"
  exit 1
fi
echo "==> Encrypted backup: ${ENC} (${ENC_SIZE} bytes)"

# ---- 6. Send to Telegram ----
echo "==> Sending to Telegram..."
HTTP=$(curl -s -o /tmp/tg_resp.json -w "%{http_code}" \
  -F "chat_id=${TELEGRAM_CHAT_ID}" \
  -F "document=@${ENC}" \
  -F "caption=Tools Forge DB Backup ${TS} | ${TABLE_COUNT} tables | ${ENC_SIZE} bytes" \
  "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendDocument")

if [ "${HTTP}" != "200" ]; then
  echo "ERROR: Telegram upload failed (HTTP ${HTTP})"
  cat /tmp/tg_resp.json || true
  exit 1
fi

if ! grep -q '"ok":true' /tmp/tg_resp.json; then
  echo "ERROR: Telegram response not ok"
  cat /tmp/tg_resp.json || true
  exit 1
fi

echo "==> Telegram delivery OK (HTTP ${HTTP})"
echo "==> Backup complete: ${ENC}"

# ---- 7. Expose filename for workflow ----
echo "BACKUP_FILE=${ENC}" >> "${GITHUB_OUTPUT:-/dev/null}"
echo "BACKUP_TS=${TS}" >> "${GITHUB_OUTPUT:-/dev/null}"
echo "TABLE_COUNT=${TABLE_COUNT}" >> "${GITHUB_OUTPUT:-/dev/null}"
