// Live-Status der Pipeline: letzte GitHub-Actions-Laeufe und offene Pull
// Requests. Liest direkt von der oeffentlichen GitHub-API, damit das
// statische Dashboard ohne Backend auskommt. Laeuft als eigenes Modul,
// damit ein API-Fehler den restlichen Aufbau (app.js) nicht beeintraechtigt.
(() => {
  const FALLBACK_OWNER = "malkreide";
  const FALLBACK_REPO = "future-skills-evidence-graph";
  const DATA_INDEX_PATHS = ["./data/index.json", "../data/index.json"];

  const els = {
    jobList: document.querySelector("#jobList"),
    prList: document.querySelector("#prList"),
    jobCount: document.querySelector("#jobCount"),
    prCount: document.querySelector("#prCount"),
    updated: document.querySelector("#pipelineUpdated"),
    refresh: document.querySelector("#pipelineRefresh"),
    generatedAt: document.querySelector("#dataGeneratedAt"),
  };

  if (!els.jobList || !els.prList) return;

  function repoSlug() {
    // Auf GitHub Pages laesst sich owner/repo aus der URL ableiten:
    // https://<owner>.github.io/<repo>/ . Lokal greift der Fallback.
    const host = location.hostname;
    if (host.endsWith(".github.io")) {
      const owner = host.slice(0, -".github.io".length);
      const repo = location.pathname.split("/").filter(Boolean)[0];
      if (owner && repo) return { owner, repo };
    }
    return { owner: FALLBACK_OWNER, repo: FALLBACK_REPO };
  }

  const { owner, repo } = repoSlug();
  const API = `https://api.github.com/repos/${owner}/${repo}`;

  function relativeTime(iso) {
    if (!iso) return "";
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return "";
    const diff = Date.now() - then;
    const minutes = Math.round(diff / 60000);
    if (minutes < 1) return "gerade eben";
    if (minutes < 60) return `vor ${minutes} min`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `vor ${hours} h`;
    const days = Math.round(hours / 24);
    if (days < 30) return `vor ${days} d`;
    return new Date(iso).toLocaleDateString("de-CH");
  }

  function jobStatus(run) {
    // Liefert Label + CSS-Klasse fuer den Zustand eines Workflow-Laufs.
    if (run.status !== "completed") {
      const running = run.status === "in_progress";
      return { label: running ? "läuft" : "wartet", cls: running ? "running" : "pending" };
    }
    const map = {
      success: { label: "erfolgreich", cls: "success" },
      failure: { label: "fehlgeschlagen", cls: "failure" },
      cancelled: { label: "abgebrochen", cls: "neutral" },
      skipped: { label: "übersprungen", cls: "neutral" },
      timed_out: { label: "Timeout", cls: "failure" },
    };
    return map[run.conclusion] || { label: run.conclusion || "fertig", cls: "neutral" };
  }

  function badge(label, cls) {
    const span = document.createElement("span");
    span.className = `status-badge status-${cls}`;
    span.textContent = label;
    return span;
  }

  function emptyHint(container, text) {
    container.replaceChildren();
    const p = document.createElement("p");
    p.className = "pipeline-hint";
    p.textContent = text;
    container.append(p);
  }

  function renderJobs(runs) {
    els.jobCount.textContent = String(runs.length);
    if (!runs.length) {
      emptyHint(els.jobList, "Keine Job-Läufe gefunden.");
      return;
    }
    els.jobList.replaceChildren();
    for (const run of runs) {
      const status = jobStatus(run);
      const item = document.createElement("a");
      item.className = "pipeline-item";
      item.href = run.html_url;
      item.target = "_blank";
      item.rel = "noreferrer";

      const top = document.createElement("div");
      top.className = "pipeline-item-top";
      const name = document.createElement("strong");
      name.textContent = run.name || run.display_title || "Workflow";
      top.append(name, badge(status.label, status.cls));

      const meta = document.createElement("small");
      const branch = run.head_branch ? `${run.head_branch} · ` : "";
      meta.textContent = `${branch}${relativeTime(run.run_started_at || run.created_at)}`;

      item.append(top, meta);
      els.jobList.append(item);
    }
  }

  function renderPullRequests(prs) {
    els.prCount.textContent = String(prs.length);
    if (!prs.length) {
      emptyHint(els.prList, "Keine offenen Pull Requests – nichts steht zur Review an.");
      return;
    }
    els.prList.replaceChildren();
    for (const pr of prs) {
      const item = document.createElement("a");
      item.className = "pipeline-item";
      item.href = pr.html_url;
      item.target = "_blank";
      item.rel = "noreferrer";

      const top = document.createElement("div");
      top.className = "pipeline-item-top";
      const name = document.createElement("strong");
      name.textContent = `#${pr.number} ${pr.title}`;
      const cls = pr.draft ? "neutral" : "pending";
      top.append(name, badge(pr.draft ? "Entwurf" : "offen", cls));

      const meta = document.createElement("small");
      meta.textContent = `${pr.head?.ref || ""} · aktualisiert ${relativeTime(pr.updated_at)}`;

      item.append(top, meta);
      els.prList.append(item);
    }
  }

  async function fetchJson(url) {
    const response = await fetch(url, { headers: { Accept: "application/vnd.github+json" } });
    if (!response.ok) {
      const err = new Error(`GitHub-API ${response.status}`);
      err.status = response.status;
      throw err;
    }
    return response.json();
  }

  async function loadGenerated() {
    for (const path of DATA_INDEX_PATHS) {
      try {
        const payload = await fetch(path, { cache: "no-store" }).then((r) => (r.ok ? r.json() : null));
        if (payload?.generated_at) {
          els.generatedAt.textContent = new Date(payload.generated_at).toLocaleString("de-CH");
          return;
        }
      } catch (_) {
        // naechsten Pfad versuchen
      }
    }
    els.generatedAt.textContent = "unbekannt";
  }

  async function loadPipeline() {
    els.refresh.disabled = true;
    try {
      const [runsPayload, prs] = await Promise.all([
        fetchJson(`${API}/actions/runs?per_page=8`),
        fetchJson(`${API}/pulls?state=open&per_page=10`),
      ]);
      renderJobs(runsPayload.workflow_runs || []);
      renderPullRequests(prs || []);
      els.updated.textContent = `Stand: ${new Date().toLocaleTimeString("de-CH")}`;
    } catch (error) {
      const rateLimited = error.status === 403;
      const text = rateLimited
        ? "GitHub-API-Limit erreicht. Bitte später erneut aktualisieren."
        : `Live-Status nicht verfügbar (${error.message}).`;
      emptyHint(els.jobList, text);
      emptyHint(els.prList, `Status direkt auf GitHub ansehen: github.com/${owner}/${repo}/actions`);
      els.jobCount.textContent = "–";
      els.prCount.textContent = "–";
    } finally {
      els.refresh.disabled = false;
    }
  }

  els.refresh.addEventListener("click", loadPipeline);
  loadGenerated();

  // The operational panel is collapsed by default, so defer the GitHub API
  // calls until an operator actually opens it. This keeps the page quiet for
  // catalog users and avoids burning the anonymous API rate limit on load.
  const panel = document.querySelector("#pipelinePanel");
  if (panel) {
    let loaded = false;
    panel.addEventListener("toggle", () => {
      if (panel.open && !loaded) {
        loaded = true;
        loadPipeline();
      }
    });
  } else {
    loadPipeline();
  }
})();
