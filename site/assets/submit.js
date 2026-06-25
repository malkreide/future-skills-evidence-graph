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

  function maybeAutofillUrl(text) {
    // Eine vom Nutzer getippte URL nie überschreiben.
    if (els.url.value.trim()) return;
    const detected = detectSourceUrl(text, els.publisher.value);
    if (!detected) return;
    els.url.value = detected;
    setHint("URL automatisch aus dem Dokument erkannt – bitte kurz prüfen.", "ok");
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
    const pages = [];
    for (let i = 1; i <= doc.numPages; i += 1) {
      const page = await doc.getPage(i);
      const content = await page.getTextContent();
      pages.push(content.items.map((item) => item.str).join(" "));
    }
    return pages.join("\n\n").replace(/[ \t]+\n/g, "\n").trim();
  }

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
        const text = await extractPdfText(await file.arrayBuffer());
        if (!text) {
          setFileStatus(
            "Aus dem PDF ließ sich kein Text lesen (evtl. ein Scan ohne Textebene). " +
              "Bitte den Text einfügen.",
            "error"
          );
          return;
        }
        els.text.value = text;
        setFileStatus(`„${file.name}“ eingelesen (${text.length.toLocaleString("de-CH")} Zeichen).`, "ok");
        maybeAutofillUrl(text);
      } else {
        const text = (await file.text()).trim();
        els.text.value = text;
        setFileStatus(`„${file.name}“ eingelesen (${text.length.toLocaleString("de-CH")} Zeichen).`, "ok");
        maybeAutofillUrl(text);
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
      setHint(
        text
          ? "Im Dokument war keine URL/DOI zu finden – bitte die Quellen-URL eintragen (für den Beweispfad nötig)."
          : "Bitte eine Quellen-URL angeben (Pflichtfeld).",
        "error"
      );
      els.url.focus();
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
      window.open(buildIssueUrl({ owner, repo, includeText: true }), "_blank", "noopener");
      setHint("GitHub-Issue geöffnet – dort nur noch absenden.", "ok");
      return;
    }
    if (text) {
      const copied = await copyText(text);
      window.open(buildIssueUrl({ owner, repo, includeText: false }), "_blank", "noopener");
      setHint(
        copied
          ? "Text ist lang – er liegt in der Zwischenablage. Auf der GitHub-Seite ins Textfeld einfügen und absenden."
          : "Text ist lang – bitte oben kopieren und auf der GitHub-Seite ins Textfeld einfügen.",
        "ok"
      );
      return;
    }
    // Nur PDF-URL, kein Text.
    window.open(buildIssueUrl({ owner, repo, includeText: false }), "_blank", "noopener");
    setHint("GitHub-Issue geöffnet – die PDF-URL wird beim Import gelesen.", "ok");
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

  els.submit.addEventListener("click", onSubmit);
})();
