/**
 * Tools Forge — DB Keepalive Worker
 * Purpose: prevent Supabase Free auto-pause (7-day inactivity)
 * Cron: every 6 hours
 * Alert: Telegram on failure
 */

const KEEPALIVE_PATH = "/rest/v1/rpc/keepalive_ping";

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(runKeepalive(env));
  },

  async fetch(request, env) {
    // Manual test endpoint
    const result = await runKeepalive(env);
    return new Response(JSON.stringify(result, null, 2), {
      status: result.ok ? 200 : 500,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  },
};

async function runKeepalive(env) {
  const start = Date.now();
  const url = `${env.SUPABASE_URL}${KEEPALIVE_PATH}`;

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "apikey": env.SUPABASE_ANON_KEY,
        "Authorization": `Bearer ${env.SUPABASE_ANON_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ p_secret: env.KEEPALIVE_SECRET }),
    });

    const ms = Date.now() - start;
    let data = null;
    try { data = await res.json(); } catch (_) { /* ignore */ }

    const ok =
      res.ok &&
      Array.isArray(data) &&
      data[0] &&
      data[0].ok === true;

    if (!ok) {
      const reason = !res.ok
        ? `HTTP ${res.status}`
        : `rpc ok=false (${JSON.stringify(data)})`;
      await notifyTelegram(env, `Keepalive FAILED: ${reason} (${ms}ms)`);
      return { ok: false, ms, status: res.status, reason };
    }

    return {
      ok: true,
      ms,
      status: res.status,
      checked_at: data[0].checked_at,
    };
  } catch (e) {
    const ms = Date.now() - start;
    await notifyTelegram(env, `Keepalive ERROR: ${e.message} (${ms}ms)`);
    return { ok: false, ms, error: e.message };
  }
}

async function notifyTelegram(env, text) {
  if (!env.TELEGRAM_BOT_TOKEN || !env.TELEGRAM_CHAT_ID) return;
  try {
    await fetch(
      `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_id: env.TELEGRAM_CHAT_ID,
          text: `⚠️ Tools Forge Keepalive\n${text}`,
        }),
      }
    );
  } catch (_) {
    // Silent — no recursion
  }
}
