# Telegram-Integration (optional)

Mit einem Telegram-Bot lässt sich das Projekt vom Handy aus begleiten, ohne
die GitHub-first-Architektur zu verlassen: **Telegram ist Spiegel und
Briefkasten, nie Kontrollinstanz.** Alles läuft weiterhin über GitHub Actions,
Issues und Pull Requests; es gibt keinen Server, keinen Webhook-Endpunkt und
keinen neuen Entscheidungsweg. Ohne die Telegram-Secrets ist die gesamte
Integration ein No-op — kein Workflow schlägt fehl, kein Verhalten ändert
sich.

## Was der Bot kann

**Benachrichtigungen (Richtung Projekt → Chat):**

- 🔎 **Wöchentliche Recherche gelaufen** — ob neue Kandidaten gefunden wurden,
  mit Link auf den `research/candidates`-Review-PR
  (`research-pipeline.yml`).
- 📄 **Bericht-Import gelaufen/übersprungen** — Ergebnis jedes manuellen
  Berichts-Imports über das Issue-Formular, inkl. Grund bei Skip
  (`ingest-from-issue.yml`).
- 📌 **Neues Issue** — jedes eröffnete oder wieder geöffnete Issue, mit Titel,
  Autor:in und Link (`telegram-notify.yml`).
- ⚠️ **Fehlschläge** — wenn die Recherche-Pipeline oder ein Bericht-Import
  abbricht, mit Link auf den Actions-Lauf.

**Einreichen (Richtung Chat → Projekt):**

Eine Nachricht an den Bot wird in dasselbe „Bericht einreichen“-Issue
übersetzt, das auch das Issue-Formular erzeugt (Label `ingest`), und läuft
damit durch den identischen Import-Pfad (`parse_ingest_issue.py` →
`ingest_reports.py` → Kandidaten-PR). Drei Wege:

1. **Direkter PDF-Link** senden (`https://…/bericht.pdf`).
2. **PDF-Datei anhängen** (bis 20 MB, das Limit der Bot API). Der Poller lädt
   die Datei selbst, extrahiert den Text und fügt ihn ins Issue ein — die
   token-tragende, kurzlebige Telegram-Datei-URL landet nie auf GitHub.
3. **Berichtstext einfügen** (mindestens 200 Zeichen).

Eine Landing-Page-URL oder DOI allein reicht bewusst nicht (dahinter steht
meist kein frei ladbares PDF); der Bot antwortet dann mit einer Anleitung
statt ein leeres Issue zu erzeugen. Wie überall entstehen **nur Kandidaten**;
aktiv wird nichts ohne menschliches Review im Kandidaten-PR.

**Befehle (Dashboard-Abfragen im Chat):**

Die Befehle lesen dieselben versionierten Daten, aus denen das Dashboard
gebaut wird, und geben sie als Text wieder — nur lesend, nichts davon kann
etwas verändern. Antworten kommen im Polling-Takt (bis ~30 Min, sofort per
manuellem Dispatch); die immer aktuelle, interaktive Sicht bleibt das
Dashboard selbst.

- `/status` — Bestand im Katalog (Quellen/Claims/Skills nach Status).
- `/skills` — Top-Skills nach Evidenz-Score, mit Status und Claim-Anzahl
  (die Skill-Karten des Dashboards als Liste).
- `/skill <suchbegriff>` — ein Skill im Detail: Definition, Evidenz-Score,
  unterstützende/widersprechende Claims, Framework-Zuordnungen inkl.
  Lehrplan-21-Abdeckung. Sucht in Name (de/en), Kürzel und ID; ein exakter
  Name gewinnt, sonst listet der Bot die Treffer zum Eingrenzen.
- `/lp21` — der Lehrplan-21-Vergleich als Zusammenfassung: durchschnittliche
  Abdeckung und alle Skills aufsteigend (größte Lücken zuerst), mit dem
  Hinweis, dass die Werte redaktionelle Einzelurteile sind.
- `/dashboard` — Link zum interaktiven Dashboard als antippbarer Button
  (URL abgeleitet aus dem Repository; `DASHBOARD_URL`-Variable übersteuert,
  z. B. für eine eigene Domain).
- `/hilfe`, `/help`, `/start` — Kurzanleitung.

## Wie es funktioniert (serverlos)

```
Chat ──(Bot API)──▶ getUpdates ◀──(Poll alle 30 Min)── telegram-intake.yml
                                        │
                                        ▼
                     „Bericht einreichen“-Issue (Label ingest + ingest-approved)
                                        │
                                        ▼
                     ingest-from-issue.yml → Kandidaten-PR → menschliches Review
```

- `telegram-intake.yml` pollt die Bot API alle 30 Minuten (plus manuell per
  `workflow_dispatch` für „jetzt abholen“). Die Latenz ist der Preis dafür,
  dass kein Server betrieben werden muss.
- Der Update-Zeiger (Offset) lebt vollständig bei Telegram (unbestätigte
  Updates bleiben dort ~24 h); der Poller schreibt nichts ins Repository.
  Bestätigt wird **vor** der Verarbeitung: ein Absturz mitten im Lauf erzeugt
  so keine Duplikat-Issues bei jedem weiteren Poll — Fehler werden stattdessen
  pro Nachricht in den Chat zurückgemeldet und der Workflow-Lauf schlägt
  sichtbar fehl.
- `scripts/telegram_notify.py` und `scripts/telegram_intake.py` sind reine
  Standardbibliothek (nur der PDF-Anhang braucht das ohnehin vorhandene,
  optionale `pypdf`).

## Einrichtung

1. **Bot anlegen:** In Telegram [@BotFather](https://t.me/BotFather)
   anschreiben, `/newbot`, Namen vergeben → BotFather liefert den **Bot-Token**.
2. **Chat-ID ermitteln:** Dem neuen Bot eine Nachricht schicken (oder ihn in
   eine private Gruppe einladen und dort schreiben), dann im Browser
   `https://api.telegram.org/bot<TOKEN>/getUpdates` öffnen — im JSON steht
   `message.chat.id` (bei Gruppen negativ, das Minuszeichen gehört dazu). In
   der URL sind `<` `>` Platzhalter-Klammern: es steht nur der nackte Token
   hinter dem Präfix `bot`.
3. **Nur bei Nutzung in einer Gruppe:** Bots sehen in Gruppen standardmäßig
   **keine normalen Nachrichten**, nur Befehle („Privacy Mode“) — das
   Einreichen per PDF-Link, Anhang oder Text funktioniert aus einer Gruppe
   also erst, wenn der Privacy Mode abgeschaltet ist: bei BotFather
   `/setprivacy` → Bot wählen → `Disable`; danach den Bot einmal aus der
   Gruppe entfernen und neu hinzufügen, damit die Einstellung greift. Im
   1:1-Chat mit dem Bot ist nichts davon nötig.
4. **Secrets im Repository hinterlegen** (Settings → Secrets and variables →
   Actions):
   - `TELEGRAM_BOT_TOKEN` — der Token aus Schritt 1.
   - `TELEGRAM_CHAT_ID` — Ziel-Chat für Benachrichtigungen; dient zugleich als
     Standard-Allowlist fürs Einreichen.
   - *(Optional)* `TELEGRAM_ALLOWED_CHAT_IDS` — kommagetrennte weitere Chats,
     die einreichen dürfen.
   - *(Empfohlen)* `TELEGRAM_GITHUB_TOKEN` — ein fine-grained PAT (nur dieses
     Repository, Berechtigung **Issues: Read and write**). Hintergrund: Issues,
     die ein Workflow mit seinem eigenen `GITHUB_TOKEN` erstellt, lösen aus
     GitHub-Sicherheitsgründen keine `issues`-Workflows aus — ohne PAT startet
     der Import einer Telegram-Einreichung also erst, wenn ein Maintainer im
     Issue das Label `ingest-approved` neu setzt. Mit PAT startet er
     automatisch. Die Chat-Antwort sagt jeweils, welcher Fall gilt.
5. Fertig. Kein Workflow muss aktiviert werden; ohne Secrets bleiben alle
   Telegram-Schritte No-ops. Wer den 30-Minuten-Poll gar nicht will, kann
   `Telegram intake` in der Actions-Oberfläche deaktivieren.

### Fehlerbehebung bei der Einrichtung

- **`getUpdates` liefert 404 „Not Found“:** Die URL zeigt auf keinen gültigen
  Bot. Fast immer fehlt das Präfix `bot` direkt vor dem Token
  (`…/bot123456:AAH…/getUpdates`), die Platzhalter-Klammern `<` `>` wurden
  mitkopiert, oder der Token ist unvollständig (er enthält einen Doppelpunkt
  und wird beim Kopieren gern abgeschnitten). Schnelltest mit derselben
  URL-Struktur: `…/getMe` — antwortet es mit `"ok":true`, stimmen Token und
  Format. Zur Not zeigt BotFather den Token per `/token` erneut an.
- **`getUpdates` liefert `"ok":true,"result":[]`:** Kein Fehler — es warten
  schlicht keine Nachrichten. Entweder wurde dem Bot noch nichts geschickt
  (Achtung: an den eigenen Bot schreiben, nicht an @BotFather), die Nachricht
  ist älter als ~24 h (Updates verfallen), sie ging in einer Gruppe mit
  aktivem Privacy Mode unter (Schritt 3) — **oder die Secrets sind schon
  gesetzt und der `Telegram intake`-Workflow hat die Updates bereits
  abgeholt.** In letzterem Fall steht die gesuchte Chat-ID im Log des letzten
  Workflow-Laufs: eine noch nicht allowgelistete Absender-ID erscheint dort
  als `ignoriert (Chat <ID> nicht autorisiert)`.
- **Sofort testen statt bis zu 30 Minuten warten:** Actions →
  `Telegram intake` → „Run workflow“ holt wartende Nachrichten sofort ab.

## Sicherheits- und Kostenmodell

- **Allowlist statt offener Briefkasten:** Nur Nachrichten aus den
  konfigurierten Chats werden verarbeitet; alle anderen werden ohne Antwort
  ignoriert (der Bot ist kein Spam-Relay und verrät Fremden nicht, dass er
  zuhört). Weil die Allowlist die Einreichenden bereits authentifiziert,
  bekommen Telegram-Issues direkt `ingest-approved` — dieselbe
  Vertrauensentscheidung, die ein Maintainer bei externen
  Formular-Einreichungen per Label trifft. Damit steuert die Allowlist auch
  das LLM-Budget des Imports.
- **Kein Token im Issue:** PDF-Anhänge werden im Runner extrahiert; ins Issue
  gelangt nur Text. Fehlermeldungen redigieren den Bot-Token, bevor sie
  geloggt oder in den Chat geschickt werden.
- **Kein neuer Aktivierungspfad:** Der Bot kann nichts promoten, nichts
  mergen, nichts aktiv schalten. Er erzeugt Issues und liest den Datenbestand
  — mehr Rechte hat der Intake-Job nicht (`permissions: issues: write`).
- **Benachrichtigungen sind Best-Effort:** `telegram_notify.py` bricht nie
  einen Workflow ab; ein Telegram-Ausfall kostet nur die Nachricht, nie die
  Pipeline.

## Grenzen

- Polling-Latenz bis ~30 Minuten (sofortiges Abholen: `Telegram intake`
  manuell dispatchen).
- PDF-Anhänge maximal 20 MB (Bot-API-Limit); größere Berichte als Text
  einfügen oder den direkten PDF-Link senden.
- Sehr lange Texte werden für das Issue auf ~60 000 Zeichen gekürzt
  (GitHub-Limit für Issue-Bodies).
- Review bleibt auf GitHub: Promoten/Ablehnen läuft weiterhin über den
  Kandidaten-PR bzw. die Review-Slash-Kommandos dort — bewusst, damit jede
  redaktionelle Entscheidung auditierbar im Repo steht.
