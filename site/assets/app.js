const DATA_INDEX_PATHS = ["./data/index.json", "../data/index.json"];
const COLLECTION_PATHS = {
  sources: ["../data/sources/seed.json", "../data/sources/lehrplan21.json"],
  claims: ["../data/claims/seed.json"],
  skills: ["../data/skills/seed.json"],
  frameworks: ["../data/frameworks/seed.json", "../data/frameworks/lehrplan21.json"],
};

const state = {
  sources: [],
  claims: [],
  skills: [],
  frameworks: [],
  selectedSkillId: null,
  selectedCycle: "all",
};

const els = {
  searchInput: document.querySelector("#searchInput"),
  statusFilter: document.querySelector("#statusFilter"),
  ageFilter: document.querySelector("#ageFilter"),
  scoreFilter: document.querySelector("#scoreFilter"),
  scoreValue: document.querySelector("#scoreValue"),
  skillList: document.querySelector("#skillList"),
  detailPane: document.querySelector("#detailPane"),
  resultCount: document.querySelector("#resultCount"),
  metricSkills: document.querySelector("#metricSkills"),
  metricClaims: document.querySelector("#metricClaims"),
  metricSources: document.querySelector("#metricSources"),
  metricCandidate: document.querySelector("#metricCandidate"),
  lp21CycleFilter: document.querySelector("#lp21CycleFilter"),
  lp21Radar: document.querySelector("#lp21Radar"),
  lp21TableBody: document.querySelector("#lp21TableBody"),
  lp21Average: document.querySelector("#lp21Average"),
  lp21GapCount: document.querySelector("#lp21GapCount"),
  lp21MappingCount: document.querySelector("#lp21MappingCount"),
};

async function fetchJson(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Could not load ${path}`);
  }
  return response.json();
}

async function loadData() {
  for (const path of DATA_INDEX_PATHS) {
    try {
      const payload = await fetchJson(path);
      if (payload.skills && payload.claims && payload.sources && payload.frameworks) {
        return payload;
      }
    } catch (_) {
      // Try the next location. Local development and Pages builds use different paths.
    }
  }

  const [sources, claims, skills, frameworks] = await Promise.all([
    loadCollection(COLLECTION_PATHS.sources),
    loadCollection(COLLECTION_PATHS.claims),
    loadCollection(COLLECTION_PATHS.skills),
    loadCollection(COLLECTION_PATHS.frameworks),
  ]);
  return { sources, claims, skills, frameworks };
}

async function loadCollection(paths) {
  const chunks = await Promise.all(paths.map((path) => fetchJson(path)));
  return chunks.flat();
}

function byId(records) {
  return new Map(records.map((record) => [record.id, record]));
}

function normalize(value) {
  return String(value || "").toLowerCase();
}

function statusLabel(status) {
  return status === "active" ? "Aktiv" : status === "candidate" ? "Kandidat" : "Deprecated";
}

function scoreLabel(score) {
  return Number(score || 0).toFixed(2);
}

function lp21Mappings() {
  return state.frameworks.filter((mapping) => mapping.framework_group === "Lehrplan 21");
}

function cycleMatches(mapping) {
  return state.selectedCycle === "all" || (mapping.cycles || []).includes(state.selectedCycle);
}

function lp21CoverageLabel(score) {
  if (score >= 2.4) return "gut abgedeckt";
  if (score >= 1.5) return "teilweise";
  return "Zukunftsluecke";
}

function gapClass(label) {
  if (label === "gut abgedeckt") return "gap-good";
  if (label === "teilweise") return "gap-partial";
  return "gap-high";
}

function radarLabel(skill) {
  const labels = {
    "skill-ai-literacy": "AI",
    "skill-critical-thinking": "Kritik",
    "skill-data-literacy": "Daten",
    "skill-digital-media-literacy": "Medien",
    "skill-ethical-technology-judgment": "Ethik",
    "skill-self-regulated-learning": "Selbst",
    "skill-creative-problem-solving": "Kreativ",
    "skill-collaborative-problem-solving": "Koop.",
    "skill-systems-thinking": "Systeme",
    "skill-resilience-adaptability": "Resilienz",
  };
  return labels[skill.id] || skill.name.slice(0, 12);
}

function filteredSkills() {
  const query = normalize(els.searchInput.value);
  const status = els.statusFilter.value;
  const age = els.ageFilter.value;
  const score = Number(els.scoreFilter.value);

  return state.skills
    .filter((skill) => {
      const haystack = normalize([
        skill.name,
        skill.definition,
        skill.age_range,
        skill.status,
        ...(skill.topics || []),
      ].join(" "));
      return !query || haystack.includes(query);
    })
    .filter((skill) => status === "all" || skill.status === status)
    .filter((skill) => age === "all" || skill.age_range === age)
    .filter((skill) => Number(skill.evidence_score || 0) >= score)
    .sort((a, b) => Number(b.evidence_score || 0) - Number(a.evidence_score || 0));
}

function renderMetrics() {
  els.metricSkills.textContent = state.skills.length;
  els.metricClaims.textContent = state.claims.length;
  els.metricSources.textContent = state.sources.length;
  els.metricCandidate.textContent = state.skills.filter((skill) => skill.status === "candidate").length;
}

function renderSkillList() {
  const skills = filteredSkills();
  els.resultCount.textContent = String(skills.length);
  els.skillList.replaceChildren();

  if (!skills.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = "<h2>Keine Treffer</h2><p>Filter reduzieren oder Suchbegriff anpassen.</p>";
    els.skillList.append(empty);
    return;
  }

  if (!state.selectedSkillId || !skills.some((skill) => skill.id === state.selectedSkillId)) {
    state.selectedSkillId = skills[0].id;
  }

  for (const skill of skills) {
    const button = document.createElement("button");
    button.className = `skill-card ${skill.id === state.selectedSkillId ? "is-selected" : ""}`;
    button.type = "button";
    button.addEventListener("click", () => {
      state.selectedSkillId = skill.id;
      render();
    });

    const title = document.createElement("h3");
    title.textContent = skill.name;
    const description = document.createElement("p");
    description.textContent = skill.definition;
    const meta = document.createElement("div");
    meta.className = "card-meta";
    meta.append(
      pill(statusLabel(skill.status), skill.status),
      pill(`Score ${scoreLabel(skill.evidence_score)}`, "score"),
      pill(skill.age_range)
    );

    button.append(title, description, meta);
    els.skillList.append(button);
  }
}

function pill(text, className = "") {
  const span = document.createElement("span");
  span.className = `pill ${className}`.trim();
  span.textContent = text;
  return span;
}

function sourceLink(source) {
  const wrapper = document.createElement("div");
  wrapper.className = "source";
  const link = document.createElement("a");
  link.href = source.url;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = source.title;
  const meta = document.createElement("small");
  meta.textContent = `${source.publisher} - ${source.year} - ${source.source_type}`;
  wrapper.append(link, meta);
  return wrapper;
}

function renderLp21Comparison() {
  if (!els.lp21TableBody || !els.lp21Radar) return;

  const skillMap = byId(state.skills);
  const mappings = lp21Mappings()
    .filter(cycleMatches)
    .filter((mapping) => skillMap.has(mapping.skill_id))
    .sort((a, b) => Number(a.coverage_score || 0) - Number(b.coverage_score || 0));

  const average = mappings.length
    ? mappings.reduce((sum, mapping) => sum + Number(mapping.coverage_score || 0), 0) / mappings.length
    : 0;
  const gapCount = mappings.filter((mapping) => Number(mapping.coverage_score || 0) < 2).length;
  els.lp21Average.textContent = average.toFixed(2);
  els.lp21GapCount.textContent = String(gapCount);
  els.lp21MappingCount.textContent = String(mappings.length);

  els.lp21TableBody.replaceChildren();
  if (!mappings.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.textContent = "Keine Lehrplan-21-Mappings fuer diesen Filter.";
    row.append(cell);
    els.lp21TableBody.append(row);
    drawRadar([], skillMap);
    return;
  }

  for (const mapping of mappings) {
    const skill = skillMap.get(mapping.skill_id);
    const row = document.createElement("tr");
    const evidenceScore = Number(skill.evidence_score || 0);
    const coverageScore = Number(mapping.coverage_score || 0);
    const label = mapping.coverage_label || lp21CoverageLabel(coverageScore);

    const skillCell = document.createElement("td");
    skillCell.innerHTML = `<strong>${skill.name}</strong><br><small>${skill.age_range}</small>`;

    const evidenceCell = document.createElement("td");
    evidenceCell.textContent = evidenceScore.toFixed(2);

    const coverageCell = document.createElement("td");
    coverageCell.innerHTML = `<strong>${coverageScore.toFixed(1)} / 3</strong><div class="coverage-bar"><span style="width: ${(coverageScore / 3) * 100}%"></span></div>`;

    const gapCell = document.createElement("td");
    gapCell.className = gapClass(label);
    gapCell.innerHTML = `<strong>${label}</strong><br><small>${(mapping.cycles || []).join(", ")}</small>`;

    const curriculumCell = document.createElement("td");
    const link = document.createElement("a");
    link.href = mapping.framework_url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = mapping.curriculum_area || mapping.framework;
    const competency = document.createElement("small");
    competency.textContent = mapping.competency;
    curriculumCell.append(link, competency);

    const pathCell = document.createElement("td");
    pathCell.textContent = mapping.evidence_path || mapping.rationale;

    row.append(skillCell, evidenceCell, coverageCell, gapCell, curriculumCell, pathCell);
    els.lp21TableBody.append(row);
  }

  drawRadar(mappings, skillMap);
}

function drawRadar(mappings, skillMap) {
  const canvas = els.lp21Radar;
  const context = canvas.getContext("2d");
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(320, Math.floor(rect.width || canvas.width));
  const height = Math.max(320, Math.floor(rect.height || canvas.height));
  const dpr = window.devicePixelRatio || 1;

  canvas.width = width * dpr;
  canvas.height = height * dpr;
  context.setTransform(dpr, 0, 0, dpr, 0, 0);
  context.clearRect(0, 0, width, height);

  if (!mappings.length) {
    context.fillStyle = "#65706d";
    context.font = "14px sans-serif";
    context.textAlign = "center";
    context.fillText("Keine Daten fuer diesen Zyklus", width / 2, height / 2);
    return;
  }

  const centerX = width / 2;
  const centerY = height / 2 + 8;
  const radius = Math.min(width, height) * 0.33;
  const maxValue = 3;
  const entries = mappings.map((mapping) => {
    const skill = skillMap.get(mapping.skill_id);
    return {
      label: radarLabel(skill),
      evidence: Number(skill.evidence_score || 0) * 3,
      lp21: Number(mapping.coverage_score || 0),
    };
  });

  context.lineWidth = 1;
  for (let level = 1; level <= 3; level += 1) {
    drawRadarPolygon(
      context,
      entries.map(() => level),
      entries,
      centerX,
      centerY,
      radius,
      maxValue,
      "#d8e0dc",
      "transparent"
    );
  }

  entries.forEach((entry, index) => {
    const angle = (Math.PI * 2 * index) / entries.length - Math.PI / 2;
    const x = centerX + Math.cos(angle) * radius;
    const y = centerY + Math.sin(angle) * radius;
    context.beginPath();
    context.moveTo(centerX, centerY);
    context.lineTo(x, y);
    context.strokeStyle = "#d8e0dc";
    context.stroke();

    context.fillStyle = "#1e2524";
    context.font = "12px sans-serif";
    context.textAlign = x < centerX - 12 ? "right" : x > centerX + 12 ? "left" : "center";
    context.textBaseline = y < centerY ? "bottom" : "top";
    context.fillText(entry.label, x + Math.sign(x - centerX) * 8, y + Math.sign(y - centerY) * 8);
  });

  drawRadarPolygon(
    context,
    entries.map((entry) => entry.evidence),
    entries,
    centerX,
    centerY,
    radius,
    maxValue,
    "#315f9f",
    "rgba(49, 95, 159, 0.16)"
  );
  drawRadarPolygon(
    context,
    entries.map((entry) => entry.lp21),
    entries,
    centerX,
    centerY,
    radius,
    maxValue,
    "#1f7a5d",
    "rgba(31, 122, 93, 0.18)"
  );
}

function drawRadarPolygon(context, values, entries, centerX, centerY, radius, maxValue, stroke, fill) {
  context.beginPath();
  values.forEach((value, index) => {
    const angle = (Math.PI * 2 * index) / entries.length - Math.PI / 2;
    const pointRadius = (Math.min(value, maxValue) / maxValue) * radius;
    const x = centerX + Math.cos(angle) * pointRadius;
    const y = centerY + Math.sin(angle) * pointRadius;
    if (index === 0) {
      context.moveTo(x, y);
    } else {
      context.lineTo(x, y);
    }
  });
  context.closePath();
  context.fillStyle = fill;
  context.strokeStyle = stroke;
  context.lineWidth = 2;
  context.fill();
  context.stroke();
}

function renderDetail() {
  const sourceMap = byId(state.sources);
  const claimMap = byId(state.claims);
  const skill = state.skills.find((item) => item.id === state.selectedSkillId);

  if (!skill) {
    els.detailPane.innerHTML = "<div class=\"empty-state\"><h2>Kein Skill ausgewaehlt</h2></div>";
    return;
  }

  const claims = (skill.supporting_claim_ids || []).map((id) => claimMap.get(id)).filter(Boolean);
  const mappingIds = new Set(skill.framework_mapping_ids || []);
  const mappings = state.frameworks.filter((mapping) => mapping.skill_id === skill.id || mappingIds.has(mapping.id));
  const sources = [
    ...new Map(
      claims
        .flatMap((claim) => claim.source_ids || [])
        .map((id) => sourceMap.get(id))
        .filter(Boolean)
        .map((source) => [source.id, source])
    ).values(),
  ];

  els.detailPane.replaceChildren();

  const header = document.createElement("header");
  header.className = "detail-header";
  const title = document.createElement("h2");
  title.textContent = skill.name;
  const definition = document.createElement("p");
  definition.className = "definition";
  definition.textContent = skill.definition;
  const tags = document.createElement("div");
  tags.className = "tag-row";
  tags.append(
    pill(statusLabel(skill.status), skill.status),
    pill(`Evidenz ${scoreLabel(skill.evidence_score)}`, "score"),
    pill(`Alter ${skill.age_range}`),
    pill(`Trend ${skill.trend}`)
  );
  header.append(title, definition, tags);

  const grid = document.createElement("div");
  grid.className = "detail-grid";

  const evidencePanel = document.createElement("section");
  evidencePanel.className = "panel";
  evidencePanel.innerHTML = "<h3>Evidenzpfad</h3>";
  for (const claim of claims) {
    const claimEl = document.createElement("div");
    claimEl.className = "claim";
    const statement = document.createElement("p");
    statement.textContent = claim.statement;
    const meta = document.createElement("small");
    meta.textContent = `${claim.evidence_strength} - ${claim.evidence_type} - ${claim.text_anchor}`;
    claimEl.append(statement, meta);
    evidencePanel.append(claimEl);
  }

  const side = document.createElement("div");
  const uncertainty = document.createElement("section");
  uncertainty.className = "panel";
  uncertainty.innerHTML = "<h3>Unsicherheit</h3>";
  const uncertaintyText = document.createElement("p");
  uncertaintyText.textContent = skill.uncertainty || "Keine Unsicherheit dokumentiert.";
  uncertainty.append(uncertaintyText);

  const mappingPanel = document.createElement("section");
  mappingPanel.className = "panel";
  mappingPanel.innerHTML = "<h3>Framework-Mappings</h3>";
  for (const mapping of mappings) {
    const item = document.createElement("div");
    item.className = "source";
    const name = document.createElement("a");
    name.href = mapping.framework_url;
    name.target = "_blank";
    name.rel = "noreferrer";
    name.textContent = mapping.framework;
    const meta = document.createElement("small");
    meta.textContent = `${mapping.mapping_strength} - ${mapping.competency}${
      mapping.coverage_score ? ` - LP21 ${Number(mapping.coverage_score).toFixed(1)} / 3` : ""
    }`;
    item.append(name, meta);
    mappingPanel.append(item);
  }

  const sourcePanel = document.createElement("section");
  sourcePanel.className = "panel";
  sourcePanel.innerHTML = "<h3>Quellen</h3>";
  for (const source of sources) {
    sourcePanel.append(sourceLink(source));
  }

  const changePanel = document.createElement("section");
  changePanel.className = "panel";
  changePanel.innerHTML = "<h3>Aenderungen</h3>";
  for (const change of skill.change_log || []) {
    const item = document.createElement("div");
    item.className = "change";
    const text = document.createElement("p");
    text.textContent = change.change;
    const meta = document.createElement("small");
    meta.textContent = `${change.date} - ${change.reason}`;
    item.append(text, meta);
    changePanel.append(item);
  }

  side.append(uncertainty, mappingPanel, sourcePanel, changePanel);
  grid.append(evidencePanel, side);
  els.detailPane.append(header, grid);
}

function render() {
  els.scoreValue.textContent = scoreLabel(els.scoreFilter.value);
  state.selectedCycle = els.lp21CycleFilter ? els.lp21CycleFilter.value : "all";
  renderMetrics();
  renderLp21Comparison();
  renderSkillList();
  renderDetail();
}

for (const control of [els.searchInput, els.statusFilter, els.ageFilter, els.scoreFilter, els.lp21CycleFilter]) {
  control.addEventListener("input", render);
}

window.addEventListener("resize", () => renderLp21Comparison());

loadData()
  .then((payload) => {
    state.sources = payload.sources || [];
    state.claims = payload.claims || [];
    state.skills = payload.skills || [];
    state.frameworks = payload.frameworks || [];
    render();
  })
  .catch((error) => {
    els.detailPane.innerHTML = `<div class="empty-state"><h2>Daten konnten nicht geladen werden</h2><p>${error.message}</p></div>`;
  });
