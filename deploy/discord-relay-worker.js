// Cloudflare Worker: forwards Extracto's Discord webhook calls to Discord.
// Needed when Discord blocks the app host's shared IP (HTTP 429 on the first message).
// Set WEBHOOK_ID below to the number in your webhook URL (/api/webhooks/<WEBHOOK_ID>/<token>)
// so the relay can't be used for anyone else's webhooks.
const WEBHOOK_ID = "PASTE_WEBHOOK_ID";

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (request.method !== "POST" || !url.pathname.startsWith(`/api/webhooks/${WEBHOOK_ID}/`)) {
      return new Response("not found", { status: 404 });
    }
    return fetch("https://discord.com" + url.pathname + url.search, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: await request.text(),
    });
  },
};
