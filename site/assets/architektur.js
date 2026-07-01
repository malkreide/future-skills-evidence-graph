const SVG_NS = "http://www.w3.org/2000/svg";
const DATA_INDEX_PATHS = ["./data/index.json", "../data/index.json"];

// ---------------------------------------------------------------------------
// View definitions. Each node is a box with absolute coordinates inside the
// view's viewBox. Edges connect node ids; anchor points are derived from the
// boxes so the diagram stays consistent if a box is moved.
// ---------------------------------------------------------------------------

const VIEWS = {
  flow: {
    viewBox: [0, 0, 1000, 1140],
    intro: {
      eyebrow: "Systemfluss",
      title: "Von der Quelle zur Empfehlung",
      body:
        "Maschinen schlagen vor, Menschen entscheiden. Externe Quellen werden " +
        "importiert, gefiltert und zu Kandidaten verdichtet; erst eine " +
        "menschliche Freigabe macht etwas aktiv. Danach wird alles geprüft, " +
        "bewertet und als statische Seite veröffentlicht.",
      sections: [
        {
          h: "Klick auf einen Baustein",
          list: ["zeigt seine Rolle, die zuständigen Dateien und die Regeln dahinter."],
        },
      ],
    },
    nodes: [
      {
        id: "apis", type: "external", x: 380, y: 24, w: 240, h: 72,
        title: "Externe Quellen-APIs", sub: "OpenAlex · Crossref · S2 · arXiv · ERIC",
        detail: {
          body:
            "Fünf wissenschaftliche Datenbanken werden wöchentlich für kuratierte " +
            "Suchanfragen abgefragt. OECD, WEF und UNESCO haben keine öffentliche " +
            "Such-API und kommen manuell über Governance-Templates herein.",
          files: ["scripts/ingest_openalex.py", "scripts/ingest_crossref.py", "scripts/ingest_semantic_scholar.py", "scripts/ingest_arxiv.py", "scripts/ingest_eric.py"],
          rules: ["Jeder Importer degradiert sanft: fällt eine Quelle aus, laufen die anderen weiter."],
        },
      },
      {
        id: "websearch", type: "external", x: 30, y: 24, w: 300, h: 72,
        title: "Web-Suche (grau, manuell)", sub: "SearXNG · DuckDuckGo · opt. Google",
        detail: {
          body:
            "Eine separate, nur manuell ausgelöste Grau-Literatur-Lane: eine " +
            "Topic-Suchanfrage findet neue Kandidaten-Quellen, welche die " +
            "schlüssellosen Kataloge nie zeigen. Strategie ist offene Suche mit " +
            "gestuftem Trust – die Trust-Stufe (trusted/watch/open) ist ein Label " +
            "für die Triage-Reihenfolge, kein Filter, und fließt NICHT in den " +
            "evidence_score. audit_domains.py leitet die Stufen evidenzbasiert " +
            "aus den Review-Entscheidungen ab.",
          files: [
            "scripts/ingest_websearch.py",
            "scripts/resolve_source_url.py",
            "scripts/audit_domains.py",
            "data/source_domains.json",
            ".github/workflows/ingest-websearch.yml",
          ],
          rules: [
            "Nur workflow_dispatch (kein Wochenlauf); jede Fundstelle bleibt Kandidat, source_type web_resource (niedrigstes Gewicht).",
            "Mintet keine Claims – die entstehen weiter verbatim über extract_claims.py / ingest_reports.py.",
          ],
        },
      },
      {
        id: "ingest", type: "process", x: 24, y: 168, w: 168, h: 64,
        title: "Import", sub: "ingest_*.py",
        detail: {
          body: "Holt Treffer der APIs und normalisiert sie zu Source-Datensätzen.",
          files: ["scripts/ingest_*.py", "scripts/common.py"],
          rules: ["Nur Standardbibliothek – die Importer bleiben abhängigkeitsfrei und robust."],
        },
      },
      {
        id: "dedupe", type: "process", x: 224, y: 168, w: 168, h: 64,
        title: "Deduplizieren", sub: "deduplicate_sources.py",
        detail: {
          body: "Entfernt Dubletten über DOI/Titel, damit dieselbe Studie nicht mehrfach erscheint.",
          files: ["scripts/deduplicate_sources.py"],
        },
      },
      {
        id: "filter", type: "process", x: 424, y: 168, w: 168, h: 64,
        title: "Relevanzfilter", sub: "Topic · Zielgruppe · Off-Scope",
        detail: {
          body:
            "Das wichtigste Präzisions-Werkzeug. Standard ist eine transparente " +
            "Keyword-/Topic-Heuristik (deterministisch, immer der Fallback). " +
            "Off-Scope-Begriffe und ein Zielgruppen-Tor (Alter 0–18) schärfen " +
            "die Treffer. Ein optionales TF-IDF-Modell ist einbaubar, aber " +
            "deaktiviert, weil es die Heuristik im fairen Vergleich nicht schlägt.",
          files: ["scripts/common.py", "scripts/eval_relevance.py", "scripts/train_relevance.py"],
          rules: [
            "Mindestens ein Topic-Match nötig – Zielgruppenwörter allein genügen nicht.",
            "Messbar gehalten: gegen ein gelabeltes Set evaluiert (Regressionstest schützt den Floor).",
          ],
        },
      },
      {
        id: "extract", type: "process", x: 624, y: 168, w: 168, h: 64,
        title: "Claims extrahieren", sub: "extract_claims.py",
        detail: {
          body:
            "Zieht einen wörtlichen Befund-Satz aus dem Abstract als Kandidaten-Claim " +
            "samt exaktem Text-Anker. Methoden-/Struktursätze werden übersprungen.",
          files: ["scripts/extract_claims.py"],
          rules: ["Konservativ: ohne Befundsatz entsteht kein Auto-Claim. Kontext, Alter, Outcome bleiben Menschenarbeit."],
        },
      },
      {
        id: "cluster", type: "process", x: 824, y: 168, w: 152, h: 64,
        title: "Clustern", sub: "cluster_claims.py",
        detail: {
          body: "Gruppiert Claims über die Topic-Vokabular und schlägt Kandidaten-Skills für unabgedeckte Themen vor.",
          files: ["scripts/cluster_claims.py"],
          rules: ["Kandidaten-Skills starten bei evidence_score 0.0 – nichts wird automatisch aktiv."],
        },
      },
      {
        id: "pr", type: "process", x: 410, y: 296, w: 180, h: 64,
        title: "Pull Request", sub: "research/candidates",
        detail: {
          body:
            "Der wöchentliche Workflow öffnet einen PR mit den Kandidaten. Solange " +
            "er offen ist, hängen spätere Läufe an denselben Branch an, statt Duplikate zu öffnen.",
          files: [".github/workflows/research-pipeline.yml"],
          rules: ["Der automatische Pfad veröffentlicht nie aktive Skills."],
        },
      },
      {
        id: "triage", type: "process", x: 640, y: 300, w: 210, h: 60,
        title: "Kandidaten-Triage", sub: "triage_candidates.py",
        detail: {
          body:
            "Bündelt den offenen Kandidaten-Rückstand zu einem einzigen, " +
            "geordneten Review-Arbeitsblatt (verbatim-Aussage, Topics, " +
            "Quelle(n), optionale LLM-assist-Vorschläge) samt den exakten " +
            "promote_candidate.py-Befehlen. Schreibt nichts nach data/ und " +
            "promotet nichts.",
          files: ["scripts/triage_candidates.py"],
          rules: ["Nur eine Lesehilfe – die Entscheidung bleibt vollständig beim Menschen."],
        },
      },
      {
        id: "review", type: "human", x: 360, y: 420, w: 280, h: 72,
        title: "Menschliche Review", sub: "promote_candidate.py",
        detail: {
          body:
            "Die einzige Stelle, an der etwas aktiv wird. Das Tool wendet die " +
            "Feldwerte des Reviewers an, verweigert die Freigabe bei verbliebenen " +
            "Platzhaltern, erzwingt, dass aktive Skills nur auf geprüften Claims " +
            "ruhen, rechnet Scores neu und re-validiert – und schreibt nichts, " +
            "falls eine Prüfung fehlschlägt.",
          files: ["scripts/promote_candidate.py"],
          rules: [
            "Jede Review-Entscheidung wird zugleich als Relevanz-Label der Quelle geerntet.",
            "Die Maschine ist Rechercheassistent, der Mensch ist Chefredakteur.",
          ],
        },
      },
      {
        id: "sources", type: "source", x: 30, y: 560, w: 180, h: 76,
        title: "Sources", sub: "data/sources/", countKey: "sources",
        detail: {
          body: "Bibliografische oder politische Quellen-Metadaten – das Fundament jedes Beweis-Pfads.",
          files: ["data/sources/", "schemas/source.schema.json"],
        },
      },
      {
        id: "claims", type: "claim", x: 275, y: 560, w: 180, h: 76,
        title: "Claims", sub: "data/claims/", countKey: "claims",
        detail: {
          body: "Strukturierte Evidenz-Aussagen, jede mit Text-Anker auf ihre Quelle(n).",
          files: ["data/claims/", "schemas/claim.schema.json"],
          rules: ["Jeder Claim verweist auf ≥ 1 Quelle."],
        },
      },
      {
        id: "skills", type: "skill", x: 520, y: 560, w: 180, h: 76,
        title: "Skills", sub: "data/skills/", countKey: "skills",
        detail: {
          body: "Zukunftskompetenz-Profile (aktiv oder Kandidat) mit abgeleitetem evidence_score.",
          files: ["data/skills/", "schemas/skill.schema.json"],
          rules: ["Jeder aktive Skill ruht auf ≥ 1 stützenden, geprüften Claim."],
        },
      },
      {
        id: "frameworks", type: "framework", x: 765, y: 560, w: 205, h: 76,
        title: "Frameworks", sub: "data/frameworks/",
        detail: {
          body: "Mappings auf externe Rahmenwerke: UNESCO, EU DigComp und der Lehrplan 21.",
          files: ["data/frameworks/", "schemas/framework_mapping.schema.json"],
          rules: ["Lehrplan-21-Mappings tragen coverage_score (0–3), Zyklen und einen kurzen Evidenzpfad."],
        },
      },
      {
        id: "validate", type: "qa", x: 170, y: 716, w: 200, h: 64,
        title: "Validierung", sub: "validate_data.py",
        detail: {
          body:
            "Erzwingt Schemas, vollständige Beweis-Pfade und – entscheidend – " +
            "rechnet jeden evidence_score nach. Weicht ein gespeicherter Wert von " +
            "der Formel ab, schlägt der Build fehl.",
          files: ["scripts/validate_data.py", "schemas/"],
          rules: ["Das Vertrauenssignal des Dashboards bleibt so immer reproduzierbar."],
        },
      },
      {
        id: "score", type: "qa", x: 560, y: 716, w: 200, h: 64,
        title: "Evidenz-Score", sub: "score_evidence.py",
        detail: {
          body:
            "Berechnet Scores statt sie von Hand zu setzen: Quellenqualität (60 %) " +
            "und Evidenzstärke (40 %) ergeben den Claim-Score; pro Skill aggregiert " +
            "ein Breitenfaktor (mehr unabhängige Belege = besser) minus Abzug für Widersprüche.",
          files: ["scripts/score_evidence.py"],
          rules: ["Niemand kann eine Lieblingskompetenz einfach hochstufen."],
        },
      },
      {
        id: "build", type: "qa", x: 400, y: 840, w: 200, h: 64,
        title: "Build", sub: "build_site.py",
        detail: {
          body: "Validiert erst, erzeugt dann die einzige data/index.json und kopiert die statische Seite.",
          files: ["scripts/build_site.py", ".github/workflows/deploy-pages.yml"],
          rules: ["Schlägt die Validierung fehl, wird gar nicht erst gebaut."],
        },
      },
      {
        id: "dashboard", type: "output", x: 380, y: 964, w: 240, h: 72,
        title: "Statisches Dashboard", sub: "GitHub Pages",
        detail: {
          body:
            "Rein statisch: app.js liest data/index.json und rendert Skills, " +
            "Beweis-Pfade und den Lehrplan-21-Vergleich (Radar, Zyklus-Filter, " +
            "Abdeckungstabelle). Diese Architektur-Seite gehört dazu.",
          files: ["site/index.html", "site/assets/app.js", "site/architektur.html"],
        },
      },
    ],
    edges: [
      { from: "apis", to: "ingest" },
      { from: "websearch", to: "dedupe", label: "graue Lit." },
      { from: "ingest", to: "dedupe" },
      { from: "dedupe", to: "filter" },
      { from: "filter", to: "extract" },
      { from: "extract", to: "cluster" },
      { from: "cluster", to: "pr" },
      { from: "pr", to: "triage" },
      { from: "triage", to: "review" },
      { from: "review", to: "sources", label: "promote-source" },
      { from: "review", to: "claims", label: "reviewed" },
      { from: "review", to: "skills", label: "active" },
      { from: "claims", to: "sources", label: "references" },
      { from: "skills", to: "claims", label: "supports" },
      { from: "skills", to: "frameworks", label: "mappt auf" },
      { from: "claims", to: "validate" },
      { from: "skills", to: "validate" },
      { from: "skills", to: "score" },
      { from: "validate", to: "build" },
      { from: "score", to: "build" },
      { from: "build", to: "dashboard" },
    ],
  },

  model: {
    viewBox: [0, 0, 1000, 720],
    intro: {
      eyebrow: "Datenmodell",
      title: "Die Beweiskette als Graph",
      body:
        "Vier Datentypen hängen wie eine Kette zusammen. Jeder Pfeil ist eine " +
        "erzwungene Referenz. So entsteht ein lückenloser Pfad " +
        "Kompetenz → Aussage → Quelle, der jede Empfehlung belegt.",
      sections: [
        {
          h: "Die eiserne Regel",
          list: [
            "Jeder aktive Skill braucht ≥ 1 stützenden Claim.",
            "Jeder Claim braucht ≥ 1 Quelle mit Text-Anker.",
          ],
        },
      ],
    },
    nodes: [
      {
        id: "skills", type: "skill", x: 230, y: 70, w: 250, h: 92,
        title: "Skill", sub: "Zukunftskompetenz", countKey: "skills",
        detail: {
          body:
            "Eine Zukunftsfähigkeit, z. B. „KI-Kompetenz“. Trägt Status " +
            "(aktiv/Kandidat/deprecated), einen abgeleiteten evidence_score, " +
            "Trend, Topics und Verweise auf stützende und widersprechende Claims.",
          files: ["data/skills/", "schemas/skill.schema.json"],
          rules: [
            "Wird erst active, wenn die Definition echt ist und alle verknüpften Claims reviewed sind.",
            "supporting_claim_ids (≥ 1) · contradicting_claim_ids · framework_mapping_ids",
          ],
        },
      },
      {
        id: "frameworks", type: "framework", x: 600, y: 70, w: 250, h: 92,
        title: "FrameworkMapping", sub: "externe Rahmenwerke",
        detail: {
          body:
            "Bildet lokale Skills auf externe Rahmenwerke ab: UNESCO, EU DigComp " +
            "und den Schweizer Lehrplan 21.",
          files: ["data/frameworks/", "schemas/framework_mapping.schema.json"],
          rules: ["Lehrplan-21-Mappings: coverage_score (0–3), cycles, curriculum_area, coverage_label, evidence_path."],
        },
      },
      {
        id: "claims", type: "claim", x: 230, y: 300, w: 250, h: 92,
        title: "Claim", sub: "strukturierte Aussage", countKey: "claims",
        detail: {
          body:
            "Eine konkrete Evidenz-Aussage, herausgezogen aus einer Quelle, mit " +
            "Kontext, Altersbereich, Outcome, Evidenz-Typ und -Stärke.",
          files: ["data/claims/", "schemas/claim.schema.json"],
          rules: [
            "references (≥ 1) auf Quelle(n) mit exaktem Text-Anker.",
            "Wird erst reviewed, wenn Kontext, Alter und Outcome echt sind (keine Platzhalter).",
          ],
        },
      },
      {
        id: "sources", type: "source", x: 230, y: 530, w: 250, h: 92,
        title: "Source", sub: "Quelle", countKey: "sources",
        detail: {
          body:
            "Eine Studie, ein Bericht oder ein Politik-Dokument – das " +
            "Originaldokument im Archiv. Speichert nur Metadaten, Abstracts (wo " +
            "erlaubt) und Links, keinen urheberrechtlich geschützten Volltext.",
          files: ["data/sources/", "schemas/source.schema.json"],
          rules: ["Trägt einen relevance_score und abgeleitete Topics aus dem Filter."],
        },
      },
    ],
    edges: [
      { from: "claims", to: "sources", label: "references ≥ 1" },
      { from: "skills", to: "claims", label: "supporting ≥ 1" },
      { from: "skills", to: "claims", label: "contradicting", dashed: true, offset: 70 },
      { from: "skills", to: "frameworks", label: "framework_mapping_ids" },
    ],
  },
};

// ---------------------------------------------------------------------------
// State + DOM
// ---------------------------------------------------------------------------

const state = { view: "flow", selected: null, counts: null };
const svg = document.querySelector("#archSvg");
const detail = document.querySelector("#archDetail");
const tabs = Array.from(document.querySelectorAll(".arch-tab"));

function el(tag, attrs = {}, text) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text != null) node.textContent = text;
  return node;
}

function nodeById(view, id) {
  return view.nodes.find((n) => n.id === id);
}

function anchors(a, b) {
  const ac = { x: a.x + a.w / 2, y: a.y + a.h / 2 };
  const bc = { x: b.x + b.w / 2, y: b.y + b.h / 2 };
  const dx = bc.x - ac.x;
  const dy = bc.y - ac.y;
  if (Math.abs(dx) > Math.abs(dy)) {
    return [
      { x: dx > 0 ? a.x + a.w : a.x, y: ac.y },
      { x: dx > 0 ? b.x : b.x + b.w, y: bc.y },
    ];
  }
  return [
    { x: ac.x, y: dy > 0 ? a.y + a.h : a.y },
    { x: bc.x, y: dy > 0 ? b.y : b.y + b.h },
  ];
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function render() {
  const view = VIEWS[state.view];
  svg.setAttribute("viewBox", view.viewBox.join(" "));
  while (svg.firstChild) svg.removeChild(svg.firstChild);

  // arrowhead marker
  const defs = el("defs");
  const marker = el("marker", {
    id: "arrow", viewBox: "0 0 10 10", refX: "9", refY: "5",
    markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse",
  });
  marker.appendChild(el("path", { d: "M0,0 L10,5 L0,10 z", fill: "#b8c4be" }));
  defs.appendChild(marker);
  svg.appendChild(defs);

  const neighbours = new Set();
  if (state.selected) {
    for (const e of view.edges) {
      if (e.from === state.selected) neighbours.add(e.to);
      if (e.to === state.selected) neighbours.add(e.from);
    }
  }

  // edges first (under nodes)
  for (const e of view.edges) {
    const a = nodeById(view, e.from);
    const b = nodeById(view, e.to);
    if (!a || !b) continue;
    const [p1, p2] = anchors(a, b);
    let mid1 = { x: p1.x, y: p1.y };
    if (e.offset) mid1 = { x: p1.x + e.offset, y: p1.y };
    const active = state.selected && (e.from === state.selected || e.to === state.selected);
    const dim = state.selected && !active;

    const path = el("path", {
      class: `arch-edge${e.dashed ? " is-dashed" : ""}${active ? " is-active" : ""}${dim ? " is-dim" : ""}`,
      d: e.offset
        ? `M${p1.x},${p1.y} C${p1.x + e.offset},${p1.y} ${p2.x + e.offset},${p2.y} ${p2.x},${p2.y}`
        : `M${p1.x},${p1.y} L${p2.x},${p2.y}`,
      "marker-end": "url(#arrow)",
    });
    svg.appendChild(path);

    if (e.label) {
      const lx = (p1.x + p2.x) / 2 + (e.offset ? e.offset : 0);
      const ly = (p1.y + p2.y) / 2 - 4;
      const label = el("text", {
        class: `arch-edge-label${dim ? " is-dim" : ""}`,
        x: lx, y: ly, "text-anchor": "middle",
      }, e.label);
      svg.appendChild(label);
    }
  }

  // nodes
  for (const n of view.nodes) {
    const selected = state.selected === n.id;
    const dim = state.selected && !selected && !neighbours.has(n.id);
    const g = el("g", {
      class: `arch-node type-${n.type}${selected ? " is-selected" : ""}${dim ? " is-dim" : ""}`,
      tabindex: "0", role: "button",
      "aria-label": n.title,
    });
    g.appendChild(el("rect", { x: n.x, y: n.y, width: n.w, height: n.h, rx: 8 }));
    g.appendChild(el("rect", { class: "node-stripe", x: n.x, y: n.y, width: 5, height: n.h }));

    const cx = n.x + n.w / 2;
    g.appendChild(el("text", { class: "node-title", x: cx, y: n.y + 28, "text-anchor": "middle" }, n.title));
    if (n.sub) {
      g.appendChild(el("text", { class: "node-sub", x: cx, y: n.y + 46, "text-anchor": "middle" }, n.sub));
    }
    if (n.countKey && state.counts) {
      const c = state.counts[n.countKey];
      g.appendChild(el("text", {
        class: "node-badge", x: cx, y: n.y + n.h - 10, "text-anchor": "middle",
      }, `${c} ${c === 1 ? "Eintrag" : "Einträge"}`));
    }

    g.addEventListener("click", () => select(n.id));
    g.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        select(n.id);
      }
    });
    svg.appendChild(g);
  }
}

function renderDetail() {
  const view = VIEWS[state.view];
  const node = state.selected ? nodeById(view, state.selected) : null;

  if (!node) {
    const intro = view.intro;
    let html = `<p class="eyebrow">${intro.eyebrow}</p><h2>${intro.title}</h2><p>${intro.body}</p>`;
    for (const s of intro.sections || []) {
      html += `<h3>${s.h}</h3><ul>${s.list.map((i) => `<li>${i}</li>`).join("")}</ul>`;
    }
    html += `<p class="hint">Tipp: Wechsle oben zwischen Systemfluss und Datenmodell.</p>`;
    detail.innerHTML = html;
    return;
  }

  const d = node.detail || {};
  let html = `<p class="eyebrow">${node.sub || ""}</p><h2>${node.title}</h2>`;
  if (d.body) html += `<p>${d.body}</p>`;
  if (node.countKey && state.counts) {
    html += `<p class="hint">Aktuell <strong>${state.counts[node.countKey]}</strong> im Graphen.</p>`;
  }
  if (d.rules && d.rules.length) {
    html += `<h3>Regeln</h3><ul>${d.rules.map((r) => `<li>${r}</li>`).join("")}</ul>`;
  }
  if (d.files && d.files.length) {
    html += `<h3>Dateien</h3><ul>${d.files.map((f) => `<li><code>${f}</code></li>`).join("")}</ul>`;
  }
  detail.innerHTML = html;
}

function select(id) {
  state.selected = state.selected === id ? null : id;
  render();
  renderDetail();
}

function setView(view) {
  state.view = view;
  state.selected = null;
  for (const t of tabs) {
    const active = t.dataset.view === view;
    t.classList.toggle("is-active", active);
    t.setAttribute("aria-selected", active ? "true" : "false");
  }
  render();
  renderDetail();
}

for (const t of tabs) {
  t.addEventListener("click", () => setView(t.dataset.view));
}

// ---------------------------------------------------------------------------
// Live counts from the generated index.json (graceful if unavailable)
// ---------------------------------------------------------------------------

async function fetchJson(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`Could not load ${path}`);
  return response.json();
}

async function loadCounts() {
  for (const path of DATA_INDEX_PATHS) {
    try {
      return await fetchJson(path);
    } catch (_e) {
      /* try next */
    }
  }
  return null;
}

function applyCounts(payload) {
  const ids = {
    metricSkills: (payload.skills || []).length,
    metricClaims: (payload.claims || []).length,
    metricSources: (payload.sources || []).length,
    metricCandidate: [...(payload.skills || []), ...(payload.claims || []), ...(payload.sources || [])]
      .filter((r) => r.status === "candidate").length,
  };
  for (const [id, value] of Object.entries(ids)) {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  }
  state.counts = {
    sources: (payload.sources || []).length,
    claims: (payload.claims || []).length,
    skills: (payload.skills || []).length,
  };
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

render();
renderDetail();

loadCounts().then((payload) => {
  if (!payload) return;
  applyCounts(payload);
  render();
  renderDetail();
});
