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
etwas verändern. Antworten kommen im Standard-Modus im Polling-Takt (bis
~10 Min, sofort per manuellem Dispatch), mit dem optionalen
[Echtzeit-Relay](#echtzeit-modus-optional-webhook-relay) in Sekunden; die
immer aktuelle, interaktive Sicht bleibt das Dashboard selbst.

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
Pull (Standard):  Chat ──(Bot API)──▶ getUpdates ◀──(Poll alle 10 Min)── telegram-intake.yml
Push (optional):  Chat ──(Webhook)──▶ Cloudflare-Relay ──(workflow_dispatch)──▶ telegram-intake.yml
                                        │
                                        ▼
                     „Bericht einreichen“-Issue (Label ingest + ingest-approved)
                                        │
                                        ▼
                     ingest-from-issue.yml → Kandidaten-PR → menschliches Review
```

- `telegram-intake.yml` pollt die Bot API alle 10 Minuten (plus manuell per
  `workflow_dispatch` für „jetzt abholen“). Die Latenz ist der Preis dafür,
  dass kein Server betrieben werden muss — wer Antworten in Sekunden will,
  aktiviert den [Echtzeit-Modus](#echtzeit-modus-optional-webhook-relay)
  weiter unten; die gesamte Logik bleibt auch dann hier im Repository.
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
- **Sofort testen statt auf den Poll warten:** Actions →
  `Telegram intake` → „Run workflow“ holt wartende Nachrichten sofort ab.

## Echtzeit-Modus (optional): Webhook-Relay

Der Standard-Modus pollt alle 10 Minuten. Wer **Antworten in Sekunden** will
(~15–40 s inkl. Runner-Start), schaltet auf Push um: Telegram liefert jedes
Update per Webhook an einen minimalen [Cloudflare
Worker](https://workers.cloudflare.com/) (kostenloses Kontingent reicht
locker), und der tut genau eines — er löst `telegram-intake.yml` per
`workflow_dispatch` aus und reicht das Update als Input durch. **Alle Logik
(Allowlist, Befehle, Issue-Erstellung) bleibt im Repository und läuft in
GitHub Actions**; der Worker ist zustandslose Zustellung. Das ist der bewusst
kleine Schritt außerhalb von GitHub; wer ihn nicht gehen will, bleibt einfach
beim Poll-Modus.

Einrichtung:

1. **Worker anlegen:** Bei Cloudflare (kostenloses Konto) einen neuen Worker
   erstellen und den Inhalt von
   [`relay/telegram-webhook-relay.js`](../relay/telegram-webhook-relay.js)
   einfügen (Dashboard-Editor genügt, kein Tooling nötig). Die Worker-URL
   notieren (`https://<name>.<account>.workers.dev`).
2. **Worker-Secrets setzen** (Worker → Settings → Variables and Secrets):
   - `WEBHOOK_SECRET` — ein frei gewähltes, langes Secret (z. B. aus einem
     Passwortmanager); gleich auch bei Telegram angegeben (Schritt 3).
   - `GITHUB_PAT` — fine-grained PAT, nur dieses Repository, Berechtigung
     **Actions: Read and write** (das ist ein *anderes* Recht als das
     Issues-PAT aus der Grundeinrichtung; ein gemeinsames PAT mit beiden
     Rechten geht auch).
   - `GITHUB_REPOSITORY` — z. B. `malkreide/future-skills-evidence-graph`.
   - optional `GITHUB_BRANCH` — Standard `main`.
3. **Webhook bei Telegram registrieren** (Token, Worker-URL und Secret
   einsetzen):

   ```
   https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<worker-url>&secret_token=<WEBHOOK_SECRET>
   ```

   Prüfen mit `…/getWebhookInfo`. Ab jetzt beantwortet Telegram `getUpdates`
   mit 409 — der 10-Minuten-Poll erkennt das und überspringt sich selbst;
   beide Trigger können also aktiv bleiben.
4. **Zurück zum Poll-Modus** jederzeit per `…/deleteWebhook` — der nächste
   Poll übernimmt wieder, nichts weiter nötig.

Sicherheitsnotizen: Der Worker weist Requests ohne passendes
`X-Telegram-Bot-Api-Secret-Token` ab (nur Telegram kennt das Secret), und die
Chat-Allowlist wird unverändert im Intake-Skript geprüft — das Relay kann sie
nicht umgehen. Schlägt der Dispatch fehl (GitHub-Ausfall, PAT abgelaufen),
antwortet der Worker mit 502 und Telegram wiederholt die Zustellung; das
Update geht nicht verloren. Jeder Push-Lauf verarbeitet genau ein Update und
gruppiert seine Concurrency per `update_id`, damit GitHubs
„ein wartender Lauf pro Gruppe“-Regel keine Nachricht verwirft.

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

- Polling-Latenz bis ~10 Minuten im Standard-Modus (sofortiges Abholen:
  `Telegram intake` manuell dispatchen); Antworten in Sekunden liefert der
  optionale [Echtzeit-Modus](#echtzeit-modus-optional-webhook-relay).
- PDF-Anhänge maximal 20 MB (Bot-API-Limit); größere Berichte als Text
  einfügen oder den direkten PDF-Link senden.
- Sehr lange Texte werden für das Issue auf ~60 000 Zeichen gekürzt
  (GitHub-Limit für Issue-Bodies).
- Review bleibt auf GitHub: Promoten/Ablehnen läuft weiterhin über den
  Kandidaten-PR bzw. die Review-Slash-Kommandos dort — bewusst, damit jede
  redaktionelle Entscheidung auditierbar im Repo steht.
