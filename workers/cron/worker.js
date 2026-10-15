/**
 * Tools Forge — Cron Worker
 * Runs hourly to trigger /v1/cron/tick
 * Alert on failure via Telegram
 */

const CRON_PATH = "/v1/cron/tick";

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(runTick(env));
  },
  async fetch(request, env) {
    const result = await runTick(env);
    return new Response(JSON.stringify(result, null, 2), {
      status: result.ok ? 200 : 500,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  },
};

async function runTick(env) {
  const start = Date.now();
  try {
    const res = await fetch(`${env.API_BASE}${CRON_PATH}`, {
      method: "POST",
      headers: {
        "X-Cron-Secret": env.CRON_SECRET,
        "Content-Type": "application/json",
      },
    });
    const ms = Date.now() - start;
    let data = null;
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) {
      const reason = `HTTP ${res.status}`;
      await notify(env, `Cron FAILED: ${reason} (${ms}ms)\n${JSON.stringify(data).slice(0, 200)}`);
      return { ok: false, ms, status: res.status };
    }
    return { ok: true, ms, data };
  } catch (e) {
    const ms = Date.now() - start;
    await notify(env, `Cron ERROR: ${e.message} (${ms}ms)`);
    return { ok: false, ms, error: e.message };
  }
}

async function notify(env, text) {
  if (!env.TELEGRAM_BOT_TOKEN || !env.TELEGRAM_CHAT_ID) return;
  try {
    await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: env.TELEGRAM_CHAT_ID,
        text: `⚠️ Tools Forge Cron\n${text}`,
      }),
    });
  } catch (_) {}
}
