/**
 * Telegram-Webhook-Relay für den Echtzeit-Modus (optional).
 *
 * Ein minimaler Cloudflare Worker: Telegram schickt jedes Update per Webhook
 * hierher, der Worker prüft das Webhook-Secret und löst NUR einen
 * `workflow_dispatch` auf `telegram-intake.yml` aus — das Update selbst wird
 * unverändert als Input durchgereicht. Sämtliche Logik (Allowlist, Befehle,
 * Issue-Erstellung) bleibt im Repository und läuft in GitHub Actions; dieser
 * Worker ist reine Zustellung und hält keinerlei Zustand.
 *
 * Warum überhaupt ein Relay: GitHub Actions kann keine Webhooks von Telegram
 * empfangen, und sobald ein Webhook gesetzt ist, liefert Telegram Updates
 * nicht mehr über getUpdates aus (der Poll-Modus antwortet dann mit 409 und
 * überspringt sich selbst). Der Worker ist damit der bewusst kleine Schritt
 * außerhalb von GitHub, der aus dem 10-Minuten-Poll ein ~15–40-Sekunden-
 * Antwortverhalten macht.
 *
 * Worker-Secrets (Cloudflare: Settings → Variables and Secrets):
 *   WEBHOOK_SECRET    – frei gewähltes Secret; identisch als `secret_token`
 *                       beim Telegram-setWebhook-Aufruf angeben. Requests ohne
 *                       passenden Header werden abgewiesen.
 *   GITHUB_PAT        – fine-grained PAT, nur dieses Repository,
 *                       Berechtigung "Actions: Read and write".
 *   GITHUB_REPOSITORY – z. B. "malkreide/future-skills-evidence-graph".
 *   GITHUB_BRANCH     – optional; Branch für den Dispatch (Standard: main).
 *
 * Einrichtung und Rückbau (deleteWebhook): docs/telegram-integration.md.
 */

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Telegram webhook relay", { status: 200 });
    }
    const secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
    if (!env.WEBHOOK_SECRET || secret !== env.WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("bad request", { status: 400 });
    }

    const dispatch = await fetch(
      `https://api.github.com/repos/${env.GITHUB_REPOSITORY}/actions/workflows/telegram-intake.yml/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GITHUB_PAT}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
          "User-Agent": "future-skills-evidence-graph-telegram-relay",
        },
        body: JSON.stringify({
          ref: env.GITHUB_BRANCH || "main",
          inputs: {
            update: JSON.stringify(update),
            update_id: String(update.update_id ?? ""),
          },
        }),
      },
    );

    // Ein Nicht-2xx lässt Telegram die Zustellung wiederholen, statt das
    // Update zu verlieren (z. B. bei GitHub-Ausfall oder abgelaufenem PAT).
    if (!dispatch.ok) {
      return new Response("dispatch failed", { status: 502 });
    }
    return new Response("OK", { status: 200 });
  },
};
