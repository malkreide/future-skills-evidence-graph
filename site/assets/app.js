const DATA_INDEX_PATHS = ["./data/index.json", "../data/index.json"];

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
  audienceFilter: document.querySelector("#audienceFilter"),
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
  resetFilters: document.querySelector("#resetFilters"),
  filterSummary: document.querySelector("#filterSummary"),
  themeToggle: document.querySelector("#themeToggle"),
  metricFilters: [...document.querySelectorAll(".metric-filter")],
};

// When keyboard navigation moves the selection, the list is re-rendered, so we
// remember to move focus onto the freshly built selected card afterwards.
let focusSelectedCard = false;

// Default values for every filter control. Used to detect whether any filter is
// active (to enable the reset button) and to restore the pristine view.
const FILTER_DEFAULTS = {
  search: "",
  status: "all",
  audience: "all",
  age: "all",
  score: "0",
  cycle: "all",
};

// Lehrplan-21-Zyklen als Altersspannen (Kindergarten–Sek I). Ein Skill zählt zu
// einem Zyklus, wenn seine age_range-Spanne die Zyklus-Spanne überlappt.
const LP21_CYCLE_AGES = { z1: [4, 8], z2: [8, 12], z3: [12, 15] };

// Maps URL query parameters to their controls so filter state is shareable and
// survives a page reload.
const URL_PARAM_MAP = {
  q: "searchInput",
  status: "statusFilter",
  audience: "audienceFilter",
  age: "ageFilter",
  score: "scoreFilter",
  cycle: "lp21CycleFilter",
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
      // Try the next location. Pages serves index.json next to the page,
      // a local repository checkout serves it one level up.
    }
  }
  throw new Error("data/index.json fehlt. Erst `python scripts/build_site.py` ausführen und `public/` serven.");
}

function byId(records) {
  return new Map(records.map((record) => [record.id, record]));
}

function normalize(value) {
  return String(value || "").toLowerCase();
}

function statusLabel(status) {
  return status === "active" ? "Aktiv" : status === "candidate" ? "Kandidat" : "Veraltet";
}

function parseAgeRange(value) {
  const match = String(value || "").match(/^(\d+)\s*-\s*(\d+)$/);
  return match ? [Number(match[1]), Number(match[2])] : null;
}

// True when the skill's age band overlaps the selected Lehrplan-21 cycle.
function ageMatchesCycle(ageRange, cycleKey) {
  if (cycleKey === "all") return true;
  const span = LP21_CYCLE_AGES[cycleKey];
  const range = parseAgeRange(ageRange);
  if (!span || !range) return false;
  return range[0] <= span[1] && range[1] >= span[0];
}

function scoreLabel(score) {
  return Number(score || 0).toFixed(2);
}

const prefersReducedMotion =
  window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function themeColors() {
  const styles = getComputedStyle(document.documentElement);
  const read = (name, fallback) => (styles.getPropertyValue(name).trim() || fallback);
  return {
    line: read("--line", "#d8e0dc"),
    blue: read("--blue", "#315f9f"),
    green: read("--green", "#1f7a5d"),
    text: read("--text", "#1e2524"),
    muted: read("--muted", "#65706d"),
  };
}

// Turns a #rrggbb value into an rgba() string so the radar fills stay legible in
// both the light and dark themes.
function withAlpha(color, alpha) {
  const hex = color.replace("#", "");
  if (hex.length !== 6) return color;
  const r = parseInt(hex.slice(0, 2), 16);
  const g = parseInt(hex.slice(2, 4), 16);
  const b = parseInt(hex.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

const MOON_SVG =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>';
const SUN_SVG =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';

function setTheme(theme) {
  const dark = theme === "dark";
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  try {
    localStorage.setItem("fseg-theme", dark ? "dark" : "light");
  } catch (_) {
    // Storage may be unavailable (private mode); the toggle still works per session.
  }
  if (els.themeToggle) {
    els.themeToggle.setAttribute("aria-pressed", String(dark));
    els.themeToggle.setAttribute("aria-label", dark ? "Helles Design einschalten" : "Dunkles Design einschalten");
    const icon = els.themeToggle.querySelector(".theme-toggle-icon");
    const text = els.themeToggle.querySelector(".theme-toggle-text");
    // Show the icon of the mode you would switch *to*.
    if (icon) icon.innerHTML = dark ? SUN_SVG : MOON_SVG;
    if (text) text.textContent = dark ? "Hell" : "Dunkel";
  }
}

function currentControlValues() {
  return {
    search: els.searchInput.value.trim(),
    status: els.statusFilter.value,
    audience: currentAudience(),
    age: els.ageFilter.value,
    score: els.scoreFilter.value,
    cycle: els.lp21CycleFilter ? els.lp21CycleFilter.value : "all",
  };
}

function activeFilterCount() {
  const values = currentControlValues();
  return Object.keys(FILTER_DEFAULTS).filter((key) => String(values[key]) !== FILTER_DEFAULTS[key]).length;
}

function updateFilterControls() {
  const active = activeFilterCount();
  if (els.resetFilters) els.resetFilters.disabled = active === 0;
}

function resetFilters() {
  els.searchInput.value = FILTER_DEFAULTS.search;
  els.statusFilter.value = FILTER_DEFAULTS.status;
  els.audienceFilter.value = FILTER_DEFAULTS.audience;
  els.ageFilter.value = FILTER_DEFAULTS.age;
  els.scoreFilter.value = FILTER_DEFAULTS.score;
  if (els.lp21CycleFilter) els.lp21CycleFilter.value = FILTER_DEFAULTS.cycle;
  render();
}

// Reads filter + selection state from the URL so a shared link reopens the same
// view. Unknown or malformed values fall back to the control defaults.
function applyStateFromUrl() {
  const params = new URLSearchParams(location.search);
  for (const [param, elKey] of Object.entries(URL_PARAM_MAP)) {
    const control = els[elKey];
    if (!control || !params.has(param)) continue;
    const value = params.get(param);
    if (control.tagName === "SELECT") {
      if ([...control.options].some((option) => option.value === value)) control.value = value;
    } else {
      control.value = value;
    }
  }
  const skill = params.get("skill");
  if (skill) state.selectedSkillId = skill;
}

function syncStateToUrl() {
  const values = currentControlValues();
  const params = new URLSearchParams();
  if (values.search) params.set("q", values.search);
  if (values.status !== FILTER_DEFAULTS.status) params.set("status", values.status);
  if (values.audience !== FILTER_DEFAULTS.audience) params.set("audience", values.audience);
  if (values.age !== FILTER_DEFAULTS.age) params.set("age", values.age);
  if (String(values.score) !== FILTER_DEFAULTS.score) params.set("score", values.score);
  if (values.cycle !== FILTER_DEFAULTS.cycle) params.set("cycle", values.cycle);
  if (state.selectedSkillId) params.set("skill", state.selectedSkillId);
  const query = params.toString();
  const next = query ? `${location.pathname}?${query}` : location.pathname;
  window.history.replaceState(null, "", next);
}

function lp21Mappings() {
  return state.frameworks.filter((mapping) => mapping.framework_group === "Lehrplan 21");
}

function cycleMatches(mapping) {
  return state.selectedCycle === "all" || (mapping.cycles || []).includes(state.selectedCycle);
}

function gapClass(label) {
  if (label === "gut abgedeckt") return "gap-good";
  if (label === "teilweise") return "gap-partial";
  return "gap-high";
}

function radarLabel(skill) {
  return skill.short_label || skill.name.slice(0, 12);
}

function currentAudience() {
  return els.audienceFilter ? els.audienceFilter.value : "all";
}

function skillAudience(skill) {
  return skill.audience || "learner";
}

function filteredSkills() {
  const query = normalize(els.searchInput.value);
  const status = els.statusFilter.value;
  const audience = currentAudience();
  // The age bands describe learners; they never apply when viewing educators.
  const age = audience === "educator" ? "all" : els.ageFilter.value;
  const score = Number(els.scoreFilter.value);

  return state.skills
    .filter((skill) => audience === "all" || skillAudience(skill) === audience)
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
    .filter((skill) => ageMatchesCycle(skill.age_range, age))
    .filter((skill) => Number(skill.evidence_score || 0) >= score)
    .sort((a, b) => Number(b.evidence_score || 0) - Number(a.evidence_score || 0));
}

function statusCount(status) {
  return status === "all" ? state.skills.length : state.skills.filter((skill) => skill.status === status).length;
}

function renderMetrics() {
  els.metricSkills.textContent = state.skills.length;
  els.metricClaims.textContent = state.claims.length;
  els.metricSources.textContent = state.sources.length;
  els.metricCandidate.textContent = statusCount("candidate");
  for (const button of els.metricFilters) {
    const target = button.dataset.status;
    // "all" is the default, not a narrowing filter, so its tile never reads as
    // active; a shortcut that would yield zero results is disabled instead of
    // sending the user to an empty list.
    const active = target !== "all" && els.statusFilter.value === target;
    button.setAttribute("aria-pressed", String(active));
    button.disabled = statusCount(target) === 0;
  }
}

function updateFilterSummary(shown) {
  if (!els.filterSummary) return;
  const total = state.skills.length;
  const active = activeFilterCount();
  if (!active) {
    els.filterSummary.textContent = `${total} Skills`;
    return;
  }
  const filterWord = active === 1 ? "Filter" : "Filter";
  els.filterSummary.textContent = `${shown} von ${total} Skills · ${active} ${filterWord} aktiv`;
}

function selectSkill(id, { scroll = true } = {}) {
  state.selectedSkillId = id;
  render();
  // On narrow screens the detail sits far below the list; bring it into view so
  // the tap has a visible effect. Skipped for keyboard navigation, which keeps
  // focus (and the viewport) on the list.
  if (scroll && window.matchMedia("(max-width: 920px)").matches && els.detailPane) {
    els.detailPane.scrollIntoView({ behavior: prefersReducedMotion ? "auto" : "smooth", block: "start" });
  }
}

// Arrow / Home / End move the selection through the visible skill cards, so the
// list is operable without a pointer.
function handleSkillListKeydown(event) {
  const keys = ["ArrowDown", "ArrowUp", "Home", "End"];
  if (!keys.includes(event.key)) return;
  const cards = [...els.skillList.querySelectorAll(".skill-card")];
  if (!cards.length) return;
  const current = cards.indexOf(document.activeElement);
  let next;
  if (event.key === "Home") next = 0;
  else if (event.key === "End") next = cards.length - 1;
  else if (current === -1) next = 0;
  else next = current + (event.key === "ArrowDown" ? 1 : -1);
  if (next < 0 || next >= cards.length) return;
  event.preventDefault();
  focusSelectedCard = true;
  selectSkill(cards[next].dataset.skillId, { scroll: false });
}

function renderSkillList() {
  const skills = filteredSkills();
  els.resultCount.textContent = String(skills.length);
  updateFilterSummary(skills.length);
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

  let selectedButton = null;
  for (const skill of skills) {
    const selected = skill.id === state.selectedSkillId;
    const button = document.createElement("button");
    button.className = `skill-card ${selected ? "is-selected" : ""}`;
    button.type = "button";
    button.dataset.skillId = skill.id;
    button.setAttribute("aria-pressed", String(selected));
    button.addEventListener("click", () => selectSkill(skill.id));
    if (selected) selectedButton = button;

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

  // Restore focus onto the selected card after a keyboard-driven re-render.
  if (focusSelectedCard && selectedButton) {
    selectedButton.focus();
    selectedButton.scrollIntoView({ block: "nearest" });
  }
  focusSelectedCard = false;
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

  // Lehrplan 21 is a learner curriculum; the educator perspective is anchored to
  // the UNESCO AI Competency Framework for Teachers instead, so the LP21 view does
  // not apply when only educators are shown.
  if (currentAudience() === "educator") {
    els.lp21Average.textContent = "0.00";
    els.lp21GapCount.textContent = "0";
    els.lp21MappingCount.textContent = "0";
    els.lp21TableBody.replaceChildren();
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.textContent = "Lehrplan 21 gilt für Lernende; Lehrende sind am UNESCO AI Competency Framework for Teachers verankert.";
    row.append(cell);
    els.lp21TableBody.append(row);
    drawRadar([], skillMap);
    return;
  }

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
    cell.textContent = "Keine Lehrplan-21-Mappings für diesen Filter.";
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
    const label = mapping.coverage_label;

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

function describeRadar(mappings, skillMap) {
  if (!mappings.length) {
    return "Netzdiagramm ohne Daten: keine Lehrplan-21-Mappings für den aktuellen Filter.";
  }
  const average =
    mappings.reduce((sum, mapping) => sum + Number(mapping.coverage_score || 0), 0) / mappings.length;
  const names = mappings
    .map((mapping) => (skillMap.get(mapping.skill_id) || {}).name)
    .filter(Boolean)
    .join(", ");
  return `Netzdiagramm: Future Evidence gegen LP21-Abdeckung für ${mappings.length} Future Skills (${names}). Durchschnittliche LP21-Abdeckung ${average.toFixed(1)} von 3. Detaildaten in der Tabelle darunter.`;
}

function drawRadar(mappings, skillMap) {
  const canvas = els.lp21Radar;
  const colors = themeColors();
  canvas.setAttribute("aria-label", describeRadar(mappings, skillMap));
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
    context.fillStyle = colors.muted;
    context.font = "14px sans-serif";
    context.textAlign = "center";
    context.fillText("Keine Daten für diesen Zyklus", width / 2, height / 2);
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
      colors.line,
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
    context.strokeStyle = colors.line;
    context.stroke();

    context.fillStyle = colors.text;
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
    colors.blue,
    withAlpha(colors.blue, 0.16)
  );
  drawRadarPolygon(
    context,
    entries.map((entry) => entry.lp21),
    entries,
    centerX,
    centerY,
    radius,
    maxValue,
    colors.green,
    withAlpha(colors.green, 0.18)
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
    els.detailPane.innerHTML = "<div class=\"empty-state\"><h2>Kein Skill ausgewählt</h2></div>";
    return;
  }

  const claims = (skill.supporting_claim_ids || []).map((id) => claimMap.get(id)).filter(Boolean);
  const contradictingClaims = (skill.contradicting_claim_ids || []).map((id) => claimMap.get(id)).filter(Boolean);
  const mappingIds = new Set(skill.framework_mapping_ids || []);
  const mappings = state.frameworks.filter((mapping) => mapping.skill_id === skill.id || mappingIds.has(mapping.id));
  const sources = [
    ...new Map(
      [...claims, ...contradictingClaims]
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
  if (contradictingClaims.length) {
    const heading = document.createElement("h3");
    heading.textContent = "Gegenbelege";
    evidencePanel.append(heading);
    for (const claim of contradictingClaims) {
      const claimEl = document.createElement("div");
      claimEl.className = "claim claim-contradicting";
      const statement = document.createElement("p");
      statement.textContent = claim.statement;
      const meta = document.createElement("small");
      meta.textContent = `${claim.evidence_strength} - ${claim.evidence_type} - ${claim.text_anchor}`;
      claimEl.append(statement, meta);
      evidencePanel.append(claimEl);
    }
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
  changePanel.innerHTML = "<h3>Änderungen</h3>";
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
  const score = scoreLabel(els.scoreFilter.value);
  els.scoreValue.textContent = score;
  els.scoreFilter.setAttribute("aria-valuetext", `Mindestens ${score} Evidenz`);
  state.selectedCycle = els.lp21CycleFilter ? els.lp21CycleFilter.value : "all";
  if (els.ageFilter) {
    // Age bands describe learners, so the control is inert for the educator view.
    els.ageFilter.disabled = currentAudience() === "educator";
  }
  updateFilterControls();
  renderMetrics();
  renderLp21Comparison();
  renderSkillList();
  renderDetail();
  syncStateToUrl();
}

function debounce(fn, delay) {
  let handle;
  return (...args) => {
    clearTimeout(handle);
    handle = setTimeout(() => fn(...args), delay);
  };
}

// Typing filters the whole list, so debounce it to avoid re-rendering on every
// keystroke; the other controls fire discrete changes and update immediately.
const debouncedRender = debounce(render, 200);
els.searchInput.addEventListener("input", debouncedRender);
for (const control of [
  els.statusFilter,
  els.audienceFilter,
  els.ageFilter,
  els.scoreFilter,
  els.lp21CycleFilter,
]) {
  if (control) control.addEventListener("input", render);
}

if (els.resetFilters) els.resetFilters.addEventListener("click", resetFilters);

els.skillList.addEventListener("keydown", handleSkillListKeydown);

// Metric shortcuts jump the status filter. Clicking an already-active shortcut
// clears it back to "all", so the tiles toggle.
for (const button of els.metricFilters) {
  button.addEventListener("click", () => {
    const target = button.dataset.status;
    els.statusFilter.value = els.statusFilter.value === target ? "all" : target;
    render();
  });
}

if (els.themeToggle) {
  // Reflect the theme applied by the pre-paint script, then toggle on click.
  setTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light");
  els.themeToggle.addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    setTheme(next);
    renderLp21Comparison();
  });
}

window.addEventListener("resize", () => renderLp21Comparison());

applyStateFromUrl();

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
