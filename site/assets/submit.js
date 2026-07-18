// Dropzone-Einreichung: liest eine PDF/Textdatei (oder eingefuegten Text) im
// Browser ein und oeffnet ein VORAUSGEFUELLTES GitHub-Issue-Formular
// (.github/ISSUE_TEMPLATE/ingest-report.yml). Bewusst ohne Token/Secret: die
// statische Pages-Seite kann keins sicher halten, also uebernimmt GitHub die
// Anmeldung und der Mensch bestaetigt das Issue mit einem Klick. Der Server-Pfad
// (parse_ingest_issue.py + ingest-from-issue.yml) verarbeitet es dann wie jede
// andere manuelle Einreichung.
(() => {
  const FALLBACK_OWNER = "malkreide";
  const FALLBACK_REPO = "future-skills-evidence-graph";

  // pdf.js wird nur bei Bedarf (PDF abgelegt) per dynamischem Import geladen.
  // Exakte Version gepinnt – das ist die praktische Lieferketten-Absicherung,
  // da dynamische Importe kein SRI unterstuetzen.
  const PDFJS_VERSION = "4.7.76";
  const PDFJS_BASE = `https://cdn.jsdelivr.net/npm/pdfjs-dist@${PDFJS_VERSION}/build`;
  const PDFJS_MODULE = `${PDFJS_BASE}/pdf.min.mjs`;
  const PDFJS_WORKER = `${PDFJS_BASE}/pdf.worker.min.mjs`;

  // Maximale Dateigroesse, die wir im Browser einlesen (Schutz vor Versehen).
  const MAX_FILE_BYTES = 25 * 1024 * 1024;
  // Ab dieser Textlaenge passt der Volltext nicht mehr sicher in die URL des
  // vorausgefuellten Issues; dann via Zwischenablage statt Prefill.
  const PREFILL_TEXT_LIMIT = 5000;

  // Findet sich keine URL/DOI im Dokument, fragen wir Crossref per Titel
  // (keyless, CORS – laeuft direkt im Browser ohne Backend). Ein Treffer wird
  // nur als Vorschlag uebernommen, wenn die Titel-Aehnlichkeit hoch genug ist.
  const CROSSREF_URL = "https://api.crossref.org/works";
  const TITLE_MATCH_THRESHOLD = 0.7;

  const els = {
    url: document.querySelector("#urlInput"),
    publisher: document.querySelector("#publisherInput"),
    year: document.querySelector("#yearInput"),
    dropzone: document.querySelector("#dropzone"),
    file: document.querySelector("#fileInput"),
    text: document.querySelector("#textInput"),
    fileStatus: document.querySelector("#fileStatus"),
    submit: document.querySelector("#submitBtn"),
    hint: document.querySelector("#submitHint"),
  };
  if (!els.dropzone || !els.submit) return;

  function repoSlug() {
    // owner/repo aus der Pages-URL ableiten (https://<owner>.github.io/<repo>/),
    // lokal greift der Fallback – identisch zu status.js.
    const host = location.hostname;
    if (host.endsWith(".github.io")) {
      const owner = host.slice(0, -".github.io".length);
      const repo = location.pathname.split("/").filter(Boolean)[0];
      if (owner && repo) return { owner, repo };
    }
    return { owner: FALLBACK_OWNER, repo: FALLBACK_REPO };
  }

  function setFileStatus(text, kind) {
    els.fileStatus.textContent = text;
    els.fileStatus.dataset.kind = kind || "";
  }

  function setHint(text, kind) {
    els.hint.textContent = text;
    els.hint.dataset.kind = kind || "";
  }

  function openIssuePage(url, hintText) {
    // Popup blockers can silently swallow window.open; leave a clickable
    // fallback link in the hint so the flow never dead-ends.
    const opened = window.open(url, "_blank", "noopener");
    setHint(hintText, "ok");
    if (!opened) {
      const link = document.createElement("a");
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = " Kein Tab aufgegangen? Hier klicken, um das GitHub-Issue zu öffnen.";
      els.hint.append(link);
    }
  }

  function detectSourceUrl(text, publisher) {
    // Berichte tragen ihre eigene URL/DOI fast immer im Text (Titelseite,
    // Fußzeile, „verfügbar unter …"). Wir lesen sie aus dem Dokument statt im
    // Web zu suchen – das geht offline und ohne Backend. Eine DOI ist am
    // verlässlichsten; sonst die plausibelste http(s)-URL.
    if (!text) return "";
    // Vorder- und Rückseite des Berichts, dort stehen die Links am ehesten.
    const hay = `${text.slice(0, 20000)}\n${text.slice(-8000)}`;
    const strip = (value) => value.replace(/[).,;:\]]+$/, "");

    const doi = hay.match(/\b10\.\d{4,9}\/[^\s"<>)\]]+/i);
    if (doi) return `https://doi.org/${strip(doi[0])}`;

    const urls = (hay.match(/https?:\/\/[^\s"<>)\]]+/gi) || [])
      .map(strip)
      .filter((url) => !/\.(png|jpe?g|gif|svg|css|js|woff2?)$/i.test(url));
    if (!urls.length) return "";

    const hostOf = (url) => {
      try {
        return new URL(url).hostname.replace(/^www\./, "");
      } catch (_) {
        return "";
      }
    };
    // 1) URL, deren Host zum Herausgeber passt; 2) häufigster Host; 3) erste.
    const pub = (publisher || "").trim().toLowerCase();
    if (pub) {
      const match = urls.find((url) => hostOf(url).includes(pub) || pub.includes(hostOf(url).split(".")[0]));
      if (match) return match;
    }
    const freq = {};
    for (const url of urls) {
      const host = hostOf(url);
      if (host) freq[host] = (freq[host] || 0) + 1;
    }
    const topHost = Object.keys(freq).sort((a, b) => freq[b] - freq[a])[0];
    return urls.find((url) => hostOf(url) === topHost) || urls[0];
  }

  function guessTitle(text) {
    // Beste Titel-Vermutung aus dem Fließtext: die längste „titelartige" Zeile
    // unter den ersten paar Zeilen (Titelseite), ohne Inhaltsverzeichnis-Zeilen
    // (Punktführung, führende Seitenzahlen) und mit überwiegend Buchstaben.
    const lines = text.split("\n").map((line) => line.trim()).filter(Boolean);
    let best = "";
    for (const line of lines.slice(0, 25)) {
      if (line.length < 15 || line.length > 200) continue;
      if (/\.{4,}|^\d+(\s|\.|$)/.test(line)) continue;
      const letters = (line.match(/[A-Za-zÄÖÜäöüß]/g) || []).length;
      if (letters < line.length * 0.5) continue;
      if (line.length > best.length) best = line;
    }
    return best;
  }

  function titleSimilarity(a, b) {
    // Wort-Mengen-Ähnlichkeit (Sørensen-Dice); robust gegen Wortreihenfolge.
    const tokens = (value) => (value.toLowerCase().match(/[a-z0-9äöüß]+/gi) || []);
    const setA = new Set(tokens(a));
    const setB = new Set(tokens(b));
    if (!setA.size || !setB.size) return 0;
    let shared = 0;
    for (const word of setA) if (setB.has(word)) shared += 1;
    return (2 * shared) / (setA.size + setB.size);
  }

  async function crossrefLookup(title, yearValue) {
    // Titel -> beste Quelle bei Crossref. Gibt {url, title} nur zurueck, wenn
    // ein Treffer die Aehnlichkeitsschwelle (und, falls angegeben, das Jahr ±1)
    // erreicht. Fehler/CORS/offline -> null (still, kein Abbruch).
    try {
      const params = new URLSearchParams({
        "query.bibliographic": title,
        rows: "4",
        select: "title,DOI,issued,URL",
      });
      const response = await fetch(`${CROSSREF_URL}?${params.toString()}`, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) return null;
      const payload = await response.json();
      const wantYear = parseInt(yearValue, 10) || null;
      let best = null;
      for (const item of payload?.message?.items || []) {
        const candidate = (item.title && item.title[0]) || "";
        const similarity = titleSimilarity(title, candidate);
        if (similarity < TITLE_MATCH_THRESHOLD) continue;
        const year = item.issued?.["date-parts"]?.[0]?.[0] || null;
        if (wantYear && year && Math.abs(year - wantYear) > 1) continue;
        const score = similarity + (wantYear && year === wantYear ? 0.1 : 0);
        const url = item.DOI ? `https://doi.org/${item.DOI}` : item.URL;
        if (url && (!best || score > best.score)) best = { url, title: candidate, score };
      }
      return best;
    } catch (_) {
      return null;
    }
  }

  async function maybeResolveUrl(text, title) {
    // Eine vom Nutzer getippte URL nie überschreiben.
    if (els.url.value.trim()) return;
    // 1) URL/DOI direkt aus dem Dokument (offline, sofort).
    const inDocument = detectSourceUrl(text, els.publisher.value);
    if (inDocument) {
      els.url.value = inDocument;
      setHint("URL automatisch aus dem Dokument erkannt – bitte kurz prüfen.", "ok");
      return;
    }
    // 2) Sonst Titel -> Crossref (Browser-Lookup, keyless).
    const query = (title || guessTitle(text)).trim();
    if (query.length < 8) return;
    setHint("Suche eine passende Quelle (Crossref) …", "busy");
    const found = await crossrefLookup(query, els.year.value);
    // Falls der Nutzer in der Zwischenzeit selbst getippt hat: nicht überschreiben.
    if (els.url.value.trim()) return;
    if (found) {
      els.url.value = found.url;
      const shortTitle = found.title.length > 70 ? `${found.title.slice(0, 70)}…` : found.title;
      setHint(`Mögliche Quelle via Crossref gefunden („${shortTitle}“) – bitte prüfen.`, "ok");
    } else {
      setHint("Keine URL im Dokument und kein eindeutiger Crossref-Treffer – bitte die Quellen-URL eintragen.", "");
    }
  }

  async function extractPdfText(buffer) {
    // pdf.js erst hier laden; Fehler (z. B. offline) sauber nach oben geben.
    let pdfjs;
    try {
      pdfjs = await import(PDFJS_MODULE);
    } catch (err) {
      throw new Error(
        "PDF-Lesen im Browser nicht verfügbar. Bitte die PDF-URL angeben oder " +
          "die Datei auf der GitHub-Seite anhängen."
      );
    }
    pdfjs.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
    const doc = await pdfjs.getDocument({ data: buffer }).promise;
    let title = "";
    try {
      const meta = await doc.getMetadata();
      title = (meta?.info?.Title || "").trim();
    } catch (_) {
      // Metadaten sind optional – ohne Titel fällt der Lookup auf guessTitle zurück.
    }
    const pages = [];
    for (let i = 1; i <= doc.numPages; i += 1) {
      const page = await doc.getPage(i);
      const content = await page.getTextContent();
      pages.push(content.items.map((item) => item.str).join(" "));
    }
    return { text: pages.join("\n\n").replace(/[ \t]+\n/g, "\n").trim(), title };
  }

  // Name of the dropped/picked PDF, remembered so onSubmit can steer the user to
  // attach the original PDF on GitHub. A big report's extracted text does not fit
  // through a GitHub issue body (~64 KB limit), so the clipboard-paste path is a
  // dead end for it; attaching the PDF lets the workflow extract it server-side.
  let droppedPdfName = "";

  async function handleFile(file) {
    if (!file) return;
    if (file.size > MAX_FILE_BYTES) {
      setFileStatus(`Datei zu groß (max. ${MAX_FILE_BYTES / (1024 * 1024)} MB).`, "error");
      return;
    }
    const isPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
    try {
      if (isPdf) {
        setFileStatus(`Lese „${file.name}“ …`, "busy");
        const { text, title } = await extractPdfText(await file.arrayBuffer());
        if (!text) {
          setFileStatus(
            "Aus dem PDF ließ sich kein Text lesen (evtl. ein Scan ohne Textebene). " +
              "Bitte den Text einfügen.",
            "error"
          );
          return;
        }
        els.text.value = text;
        droppedPdfName = file.name;
        setFileStatus(`„${file.name}“ eingelesen (${text.length.toLocaleString("de-CH")} Zeichen).`, "ok");
        await maybeResolveUrl(text, title);
      } else {
        const text = (await file.text()).trim();
        els.text.value = text;
        droppedPdfName = "";
        setFileStatus(`„${file.name}“ eingelesen (${text.length.toLocaleString("de-CH")} Zeichen).`, "ok");
        await maybeResolveUrl(text, "");
      }
    } catch (err) {
      setFileStatus(err.message || "Datei konnte nicht gelesen werden.", "error");
    }
  }

  function buildIssueUrl({ owner, repo, includeText }) {
    const params = new URLSearchParams();
    params.set("template", "ingest-report.yml");
    params.set("url", els.url.value.trim());
    const publisher = els.publisher.value.trim();
    const year = els.year.value.trim();
    if (publisher) params.set("publisher", publisher);
    if (year) params.set("year", year);
    if (includeText) params.set("plaintext", els.text.value.trim());
    return `https://github.com/${owner}/${repo}/issues/new?${params.toString()}`;
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_) {
      return false;
    }
  }

  async function onSubmit() {
    const url = els.url.value.trim();
    const text = els.text.value.trim();
    if (!url) {
      // Fehler dem Feld programmatisch zuordnen: aria-invalid markiert das Feld,
      // aria-describedby verweist auf die (per aria-live angekuendigte) Meldung,
      // damit Screenreader den Grund am Feld finden. [A11Y-006]
      els.url.setAttribute("aria-invalid", "true");
      els.url.setAttribute("aria-describedby", "urlHint submitHint");
      setHint(
        text
          ? "Im Dokument war keine URL/DOI zu finden – bitte die Quellen-URL eintragen (für den Beweispfad nötig)."
          : "Bitte eine Quellen-URL angeben (Pflichtfeld).",
        "error"
      );
      els.url.focus();
      return;
    }
    // Gueltige URL: Fehlerzustand zuruecksetzen.
    els.url.setAttribute("aria-invalid", "false");
    els.url.setAttribute("aria-describedby", "urlHint");
    // Inline-Praevention vor dem Oeffnen des Issues: URL-Wohlgeformtheit und
    // Jahr-Format pruefen, statt eine kaputte Eingabe ins Issue zu tragen. [USE-005]
    try {
      new URL(url);
    } catch (_) {
      els.url.setAttribute("aria-invalid", "true");
      setHint("Die Quellen-URL ist nicht wohlgeformt (z. B. https://… oder eine DOI-URL).", "error");
      els.url.focus();
      return;
    }
    const yearValue = els.year.value.trim();
    if (yearValue && !/^(19|20)\d{2}$/.test(yearValue)) {
      setHint("Bitte eine vierstellige Jahreszahl angeben (z. B. 2023) – oder das Feld leer lassen.", "error");
      els.year.focus();
      return;
    }
    const looksLikePdfUrl = /\.pdf($|[?#])/i.test(url);
    if (!text && !looksLikePdfUrl) {
      setHint(
        "Bitte Text einfügen, eine Datei ablegen – oder eine direkte PDF-URL angeben.",
        "error"
      );
      return;
    }

    const { owner, repo } = repoSlug();
    // Text bevorzugt direkt vorausfuellen; ist er zu lang fuer die URL, via
    // Zwischenablage und Hinweis. Ohne Text (reine PDF-URL) faellt der
    // Server-Pfad ohnehin auf das URL-PDF zurueck.
    if (text && text.length <= PREFILL_TEXT_LIMIT) {
      openIssuePage(
        buildIssueUrl({ owner, repo, includeText: true }),
        "GitHub-Issue geöffnet – dort nur noch absenden."
      );
      return;
    }
    // Großer Bericht aus einem PDF: der Volltext passt nicht in ein Issue (~64 KB).
    // Statt der Zwischenablage die Original-PDF auf GitHub anhängen lassen – der
    // Workflow extrahiert sie dann server-seitig.
    if (droppedPdfName) {
      openIssuePage(
        buildIssueUrl({ owner, repo, includeText: false }),
        `Großer Bericht: häng auf der GitHub-Seite die PDF „${droppedPdfName}“ im Feld ` +
          "„PDF anhängen“ an und sende ab (der Text passt nicht in ein Issue)."
      );
      return;
    }
    if (text) {
      const copied = await copyText(text);
      openIssuePage(
        buildIssueUrl({ owner, repo, includeText: false }),
        copied
          ? "Text ist lang – er liegt in der Zwischenablage. Auf der GitHub-Seite ins Textfeld einfügen und absenden."
          : "Text ist lang – bitte oben kopieren und auf der GitHub-Seite ins Textfeld einfügen."
      );
      return;
    }
    // Nur PDF-URL, kein Text.
    openIssuePage(
      buildIssueUrl({ owner, repo, includeText: false }),
      "GitHub-Issue geöffnet – die PDF-URL wird beim Import gelesen."
    );
  }

  // Drag & Drop
  ["dragenter", "dragover"].forEach((type) =>
    els.dropzone.addEventListener(type, (event) => {
      event.preventDefault();
      els.dropzone.classList.add("is-dragover");
    })
  );
  ["dragleave", "dragend", "drop"].forEach((type) =>
    els.dropzone.addEventListener(type, () => els.dropzone.classList.remove("is-dragover"))
  );
  els.dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    const file = event.dataTransfer?.files?.[0];
    if (file) handleFile(file);
  });

  // Tippen/Klicken -> Datei-Picker (mobil: Dateien/Foto)
  els.dropzone.addEventListener("click", () => els.file.click());
  els.dropzone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      els.file.click();
    }
  });
  els.file.addEventListener("change", () => handleFile(els.file.files?.[0]));
  // A manual edit means the textarea is now the source of truth, not the PDF —
  // so don't steer to attaching the (now-divergent) original PDF. Programmatic
  // fills (els.text.value = …) do not fire "input", so this only reacts to typing.
  els.text.addEventListener("input", () => {
    droppedPdfName = "";
  });

  // Enter in einem der einzeiligen Felder loest das Absenden aus (nicht im
  // Textarea, wo Enter Zeilenumbrueche macht). [USE-005]
  for (const field of [els.url, els.publisher, els.year]) {
    if (!field) continue;
    field.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        onSubmit();
      }
    });
  }

  els.submit.addEventListener("click", onSubmit);
})();
