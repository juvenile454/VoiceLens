# VoiceLens Repo-Präsentation – Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Das Repo `juvenile454/VoiceLens` soll für Außenstehende auf den ersten Blick verständlich, vertrauenswürdig und ansprechend wirken – ohne das Verhalten der App zu ändern.

**Architecture:** Reine Präsentations- und Doku-Arbeit plus CI. Neue Bilder entstehen ausschließlich mit den vorhandenen synthetischen Vorschau-Skripten (`tests/preview_ui.py`, `tests/preview_overlay.js`) – keine echten Aufnahmen. Ein neuer Test `tests/test_docs.py` sichert Links, Anker, Versionsangaben und Bildgrößen ab und läuft in der neuen GitHub-Actions-CI mit.

**Tech Stack:** Markdown (GitHub-Flavored, Mermaid), GitHub Actions (`ubuntu-24.04`), Python 3.12 `unittest`, GTK 3/PyGObject, GJS/Cairo, ffmpeg, librsvg (`rsvg-convert`), shields.io-Badges.

**Spec:** Die Empfehlungen aus der Repo-Analyse in dieser Session (Punkte 1–8). Zusammengefasst:
1. Kernfunktion (Steuerung halten → Linse → Text) als GIF oben in der README.
2. README neu ordnen: Badges, Feature-Blöcke, Quick Start, Plattform-Tabelle, Ablaufdiagramm, Screenshot-Galerie, Details aufklappbar.
3. Veröffentlichtes Release v0.2.0 (Text vorbereiten; Veröffentlichung macht der Maintainer).
4. Doku einheitlich auf Englisch; deutsche Kurzanleitung bleibt.
5. Veraltete Angaben korrigieren (`docs/release.md` steht auf 0.1.0).
6. GitHub-Actions-CI mit Test-Badge.
7. Community-Dateien: `CONTRIBUTING.md`, `CHANGELOG.md`, `SECURITY.md`, Feature-Request-Formular, Issue-`config.yml`.
8. Social-Preview-Bild 1280×640.

**Nicht im Umfang (bewusst):** GitHub-Pages-Landingpage und Aufteilen von `voicelens/ui.py` (Punkt 9 „optional, später“). Beides bringt für Erstbesucher wenig gegenüber der README, und der `ui.py`-Umbau wäre ein riskanter Refactor ohne sichtbaren Nutzen.

## Global Constraints

- App-Verhalten bleibt unverändert: keine Änderungen unter `voicelens/`, `gnome-shell-extension/`, `install.py`, `run.sh`.
- Keine neuen Tatsachenbehauptungen. Jede Aussage in README/Doku muss aus vorhandener Doku, Release-Notes oder Code belegbar sein. Einschränkungen („Early release“, nur Ubuntu 24.04 / GNOME 46 / x86_64 geprüft) bleiben sichtbar.
- Alle Bilder sind synthetisch (Test-Doubles); Bildunterschriften sagen das („Synthetic preview, no recording“).
- Keine Emojis in Markdown-Überschriften (sonst brechen Anker-Links).
- Bildbudget: jede Datei unter `assets/screenshots/` und `assets/demo/` ≤ 3 MB, alle zusammen ≤ 6 MB; `assets/social/social-preview.png` < 1 MB (GitHub-Limit).
- In der Sandbox ist `/usr/bin/python3` = 3.13 ohne passende GTK-Bindings → lokal immer `/usr/bin/python3.12` verwenden. In CI (`ubuntu-24.04`) ist `/usr/bin/python3` bereits 3.12.
- Keine persönliche E-Mail-Adresse in Repo-Dateien.
- Branch: `claude/wizardly-wright-bbkfi9`. Jede Commit-Nachricht endet mit:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_018uz5SNeU9RWzREyn3NuZys
  ```
- Kein Pull Request, solange der Nutzer nicht ausdrücklich darum bittet.

## Review Focus

1. **Kaputte relative Links/Anker** nach dem Verschieben von Bildern und dem Umbenennen von Überschriften → `test_docs.py::test_relative_links_resolve` und `test_same_file_anchors_exist` (Task 1).
2. **Zu große Bilder** machen README und Clone langsam bzw. GitHub lehnt das Social-Bild ab → `test_presentation_assets_stay_small` (Task 1) plus Größenprüfung in Task 4.
3. **Übersetzungsdrift**: Die englische Doku nennt andere Code-Bezeichner als die deutsche → Bezeichner-Vergleich in Task 5, Schritt 3.
4. **CI rot wegen Umgebung** (fehlendes apt-Paket, kein Display) statt wegen Code → Workflow lokal mit denselben Befehlen nachstellen und nach dem Push den Lauf prüfen (Task 2).
5. **Versionswidersprüche** zwischen `voicelens/__init__.py`, `docs/release.md` und `CHANGELOG.md` → `test_release_status_matches_package_version` (Task 1) und `test_changelog_top_entry_matches_version` (Task 7).

---

## Datei-Übersicht

| Pfad | Aktion | Verantwortung |
|---|---|---|
| `tests/test_docs.py` | neu | Guard: Links, Anker, Versionen, Bildgrößen |
| `docs/release.md` | ändern | Validierungsstand 0.2.0 |
| `.github/workflows/tests.yml` | neu | CI unter xvfb inkl. GJS-Overlay-Test |
| `tests/preview_ui.py` | ändern | `--language en\|de`, englisches Mikrofon-Label |
| `tests/preview_overlay.js` | ändern | optionales 2. Argument `en\|de` |
| `assets/screenshots/*.png` | neu | README-Galerie (ersetzt `assets/voicelens-preview.png`) |
| `assets/demo/dictation-en.gif` | neu | Hero-Demo |
| `assets/social/social-preview.svg`, `.png` | neu | Social-Preview |
| `README.md` | neu schreiben | Einstieg für Außenstehende |
| `docs/architecture.md`, `docs/invariants.md`, `docs/ops.md`, `docs/testing.md` | übersetzen | Englisch |
| `docs/README.md` | neu | Doku-Index |
| `CONTRIBUTING.md`, `CHANGELOG.md`, `SECURITY.md` | neu | Community |
| `.github/ISSUE_TEMPLATE/feature_request.yml`, `config.yml` | neu | Issue-Auswahl |
| `.github/pull_request_template.md` | ändern | Checkliste |

---

### Task 0: Umgebung und Ausgangslage

**Files:** keine

- [ ] **Step 1: Pakete installieren**

```bash
sudo apt-get update -qq
sudo apt-get install -y python3-gi python3-gi-cairo python3-cairo gir1.2-gtk-3.0 librsvg2-common librsvg2-bin gjs xvfb ffmpeg fonts-cantarell
```

- [ ] **Step 2: Ausgangs-Testlauf**

Run: `env -u WAYLAND_DISPLAY GDK_BACKEND=x11 xvfb-run -a /usr/bin/python3.12 -m unittest discover -s tests -p 'test_*.py'`
Expected: `OK` (ggf. mit Skips). Die Zahl `Ran N tests` notieren – sie wird in Task 1 und Task 2 gebraucht. Laut v0.2.0-Notizen sollten es 153 sein; wenn nicht, gilt die gemessene Zahl.

---

### Task 1: Doku-Guard-Test und `docs/release.md` auf 0.2.0

**Files:**
- Create: `tests/test_docs.py`
- Modify: `docs/release.md`

**Interfaces:**
- Produces: `tests/test_docs.py` mit Hilfsfunktionen `markdown_files() -> list[Path]` (alle `*.md` im Repo außer `.git/`, `.venv/`, `docs/superpowers/`), `github_slug(heading: str) -> str`, `links(path: Path) -> list[str]`. Task 7 ergänzt dort einen weiteren Test.

- [ ] **Step 1: Tests schreiben**

```python
class DocsTests(unittest.TestCase):
    def test_relative_links_resolve(self):
        # every markdown link/image target without scheme (http, https, mailto) and not starting with '#'
        # resolves (after stripping '#fragment') to an existing file relative to the .md file
        ...
    def test_same_file_anchors_exist(self):
        # every '#anchor' and 'file.md#anchor' target matches github_slug() of a heading in the target file
        ...
    def test_release_status_matches_package_version(self):
        self.assertIn(f'VoiceLens {voicelens.__version__}', (ROOT / 'docs/release.md').read_text())
        self.assertTrue((ROOT / f'docs/releases/v{voicelens.__version__}.md').exists())
    def test_presentation_assets_stay_small(self):
        files = [p for d in ('assets/screenshots', 'assets/demo') for p in (ROOT / d).glob('*') if p.is_file()]
        for p in files:
            self.assertLessEqual(p.stat().st_size, 3 * 1024 * 1024, p)
        self.assertLessEqual(sum(p.stat().st_size for p in files), 6 * 1024 * 1024)
        social = ROOT / 'assets/social/social-preview.png'
        if social.exists():
            self.assertLess(social.stat().st_size, 1024 * 1024)
```

`github_slug`: Kleinbuchstaben, alles außer `[a-z0-9 _-]` (Unicode-Buchstaben wie `ä` bleiben erhalten) entfernen, Leerzeichen → `-`. Links in Code-Blöcken (```` ``` ````) und Inline-Code ignorieren. Fehlende Asset-Ordner zählen als leer (Task 3/4 legen sie an). Dateikopf-Docstring: „Offline checks of repository documentation; no network.“ `ROOT = Path(__file__).resolve().parent.parent` und `sys.path.insert(0, str(ROOT))` vor `import voicelens` (wie in `tests/preview_ui.py`).

- [ ] **Step 2: Laufen lassen – muss fehlschlagen**

Run: `/usr/bin/python3.12 -m unittest tests.test_docs -v`
Expected: `test_release_status_matches_package_version` FAIL (`release.md` nennt 0.1.0). Die anderen drei PASS. Falls ein Link-Test fehlschlägt, ist das ein vorhandener Fehler: beheben und im Commit erwähnen.

- [ ] **Step 3: `docs/release.md` aktualisieren**

Erster Satz: „VoiceLens 0.2.0 is an early source release for Ubuntu 24.04 / GNOME 46 on x86_64.“ In der Evidence-Tabelle die vorhandenen 0.1.0-Zeilen mit dem Präfix „0.1.0:“ behalten. Neue Zeile „0.2.0 automated suite“ mit der in Task 0 gemessenen Testzahl („… tests passed under Xvfb with explicit backend doubles“). Neue Zeile „0.2.0 manual smoke test: still recommended on a real GNOME 46 desktop“ (Quelle: `docs/releases/v0.2.0.md`). Den Satz „The extension currently declares GNOME 46.“ beibehalten.

- [ ] **Step 4: Tests laufen lassen**

Run: `/usr/bin/python3.12 -m unittest tests.test_docs -v`
Expected: 4 × PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_docs.py docs/release.md
git commit -m "Add documentation guard tests and update release status to 0.2.0"
```

---

### Task 2: GitHub-Actions-CI

**Files:**
- Create: `.github/workflows/tests.yml`

**Interfaces:**
- Produces: Workflow-Datei `tests.yml`, Job-Name `tests`. Badge-URL für Task 6: `https://github.com/juvenile454/VoiceLens/actions/workflows/tests.yml/badge.svg`

- [ ] **Step 1: Workflow schreiben**

Trigger: `push` (alle Branches), `pull_request`, `workflow_dispatch`. `runs-on: ubuntu-24.04`, `timeout-minutes: 15`, `permissions: contents: read`. Schritte:
1. `actions/checkout@v4`
2. `sudo apt-get update && sudo apt-get install -y python3-gi python3-gi-cairo python3-cairo gir1.2-gtk-3.0 librsvg2-common gjs xvfb ffmpeg pulseaudio-utils`
3. `env -u WAYLAND_DISPLAY GDK_BACKEND=x11 xvfb-run -a /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py' -v`

Kein faster-whisper, kein Modell, kein Netzwerkzugriff in Tests (laut `docs/testing.md` alles Doubles).

- [ ] **Step 2: Syntax lokal prüfen**

Run: `/usr/bin/python3.12 -c "import yaml,sys; d=yaml.safe_load(open('.github/workflows/tests.yml')); print(list(d['jobs']))"`
Expected: `['tests']` (falls PyYAML fehlt: `sudo apt-get install -y python3-yaml`)

- [ ] **Step 3: Commit und Push**

```bash
git add .github/workflows/tests.yml
git commit -m "Run the test suite on GitHub Actions under Xvfb"
git push -u origin claude/wizardly-wright-bbkfi9
```

- [ ] **Step 4: CI-Lauf prüfen**

Mit `mcp__github__actions_list` (Workflow-Runs für den Branch) den Lauf abwarten, ohne Polling in Schleifen: einmal nach ca. 3–5 Minuten prüfen.
Expected: `conclusion: success` und die Testzahl aus Task 0 plus 4 aus Task 1. Bei Fehlschlag: Job-Log mit `mcp__github__get_job_logs` lesen. Bei fehlendem Paket: Paket ergänzen. Ein Test, der nur in CI fehlschlägt, wird **nicht** übersprungen, sondern als Befund an den Nutzer gemeldet.

---

### Task 3: Englische Screenshots

**Files:**
- Modify: `tests/preview_ui.py`
- Create: `assets/screenshots/main.png`, `recording.png`, `result.png`, `settings-general.png`, `settings-model.png`, `main-de.png`
- Delete: `assets/voicelens-preview.png` (einzige Referenz ist `README.md:14`, die in Task 6 ersetzt wird)

**Interfaces:**
- Produces: `tests/preview_ui.py --output DIR [--language en|de]` (Standard `de`, damit der dokumentierte Befehl gültig bleibt). Ausgabedateien heißen `<view>-<lang>.png` mit `view ∈ {voicelens, settings, settings-model, setup-help, shortcuts, recording, transcribing, result, resident, compact}`.

- [ ] **Step 1: `preview_ui.py` parametrisieren**

`--language` mit `choices=('en','de')`, Standard `de`. Die ganze Sequenz läuft in der gewählten Sprache (`Settings(language=lang, ...)`, `set_language(lang)`). Der bisherige Sprachwechsel am Ende entfällt, `compact` wird in der gewählten Sprache aufgenommen. Beispieltext für `result`: auf Englisch „This is a sample transcript from the synthetic backend. It shows how finished text looks in the window and can be edited.“, auf Deutsch wie bisher. Neue Klasse `PreviewBackend(FakeBackend)` in `preview_ui.py`, deren `list_microphones()` als `description` `'Built-in microphone'` (en) bzw. `'Eingebautes Mikrofon'` (de) liefert; `tests/test_controller.py` bleibt unverändert.

- [ ] **Step 2: Rendern**

```bash
env -u WAYLAND_DISPLAY GDK_BACKEND=x11 xvfb-run -a /usr/bin/python3.12 tests/preview_ui.py --output verification/ui-en --language en
env -u WAYLAND_DISPLAY GDK_BACKEND=x11 xvfb-run -a /usr/bin/python3.12 tests/preview_ui.py --output verification/ui-de --language de
```
Expected: Ausgabe „Synthetic GTK previews: …“, je 10 PNGs + `app-icon.png`.

- [ ] **Step 3: Sichtprüfung**

Jedes PNG mit dem Read-Tool ansehen. Kein abgeschnittener Text, keine deutschen Strings im englischen Satz, Fenster vollständig.

- [ ] **Step 4: Übernehmen und verkleinern**

Kopieren: `voicelens-en → main.png`, `recording-en → recording.png`, `result-en → result.png`, `settings-en → settings-general.png`, `settings-model-en → settings-model.png`, `voicelens-de → main-de.png`. Danach `optipng -o2` (oder, falls nicht vorhanden, `ffmpeg -i in.png -compression_level 9 out.png`). `git rm assets/voicelens-preview.png`.

- [ ] **Step 5: Tests**

Run: `env -u WAYLAND_DISPLAY GDK_BACKEND=x11 xvfb-run -a /usr/bin/python3.12 -m unittest discover -s tests -p 'test_*.py'`
Expected: OK. `test_relative_links_resolve` schlägt jetzt fehl, weil `README.md` noch auf `assets/voicelens-preview.png` zeigt → in diesem Commit `README.md:14` vorläufig auf `assets/screenshots/main.png` umstellen. Danach OK.

- [ ] **Step 6: Commit**

```bash
git add tests/preview_ui.py assets/screenshots README.md
git commit -m "Render English and German preview screenshots for the README"
```

---

### Task 4: Demo-GIF und Social-Preview

**Files:**
- Modify: `tests/preview_overlay.js`
- Create: `assets/demo/dictation-en.gif`, `assets/social/social-preview.svg`, `assets/social/social-preview.png`

**Interfaces:**
- Produces: `gjs -m tests/preview_overlay.js OUTPUT_DIRECTORY [en|de]` (Standard `de`).

- [ ] **Step 1: Sprachparameter im Overlay-Skript**

`ARGV.length` 1 oder 2 erlauben, sonst Usage-Fehler wie bisher (Usage-Text um `[en|de]` ergänzen). Ein Objekt `STRINGS = {de: {...}, en: {...}}` mit den bisherigen deutschen Texten und diesen englischen:

| Schlüssel | en |
|---|---|
| title | `VoiceLens  /  Cursor flow` |
| eyebrow | `NOTES` |
| heading | `An idea becomes text.` |
| prefix | `I have an idea. ` |
| suffix | `Let's build it.` |
| listening | `VoiceLens · Listening` |
| transcribing | `VoiceLens · Transcribing` |
| capListening | `Hold Control · Speak` |
| capTranscribing | `Release Control · Transcribing locally` |
| capReturning | `Back to the caret` |
| capDone | `Text inserted.` |
| footer | `Synthetic preview · production renderer` |

Zeichenlogik, Zeiten und Maße bleiben unverändert.

- [ ] **Step 2: Frames rendern und GIF bauen**

```bash
gjs -m tests/preview_overlay.js verification/overlay-en en
ffmpeg -v error -y -framerate 20 -i verification/overlay-en/%03d.png -filter_complex "[0:v]split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4" -loop 0 assets/demo/dictation-en.gif
ls -l assets/demo/dictation-en.gif
```
Expected: 140 Frames, GIF ≤ 3 MB. Wenn größer: `-r 15` vor dem Ausgabepfad ergänzen.

- [ ] **Step 3: Sichtprüfung**

Die Frames `000.png`, `040.png`, `080.png`, `110.png`, `139.png` mit dem Read-Tool ansehen: Linse sichtbar, englische Texte, „Text inserted.“ im letzten Frame.

- [ ] **Step 4: Social-Preview-SVG**

Format 1280×640. Hintergrund `#0e151b` mit radialem Mint-Schein (`#70eacb`, Deckkraft 0.25 → 0) bei (320, 320), r = 360. Links das App-Icon (Inhalt von `assets/voicelens.svg` inline als `<g>`, auf 288 px skaliert, Ursprung (176, 176)). Rechts ab x = 520, linksbündig, Schrift `Cantarell, 'DejaVu Sans', sans-serif`:
- `VoiceLens` – 104 px, 700, `#f0f7f7`, y = 290
- `Hold Control. Speak. Release.` – 44 px, 600, `#83ddca`, y = 360
- `Offline dictation for Linux · local Whisper · no cloud` – 26 px, `#a1b4bf`, y = 420

Ein Sicherheitsrand von 64 px ringsum bleibt frei (GitHub beschneidet je nach Plattform).

- [ ] **Step 5: PNG erzeugen und prüfen**

```bash
rsvg-convert -w 1280 -h 640 assets/social/social-preview.svg -o assets/social/social-preview.png
optipng -o2 assets/social/social-preview.png
ls -l assets/social/social-preview.png
```
Expected: < 1 MB. PNG mit dem Read-Tool ansehen: Text vollständig, Schrift ist nicht in Ersatz-Glyphen gefallen.

- [ ] **Step 6: Tests und Commit**

Run: `/usr/bin/python3.12 -m unittest tests.test_docs -v` → PASS (Größen-Test)

```bash
git add tests/preview_overlay.js assets/demo assets/social
git commit -m "Add an English dictation demo GIF and a social preview image"
```

---

### Task 5: Doku auf Englisch und Doku-Index

**Files:**
- Modify: `docs/architecture.md`, `docs/invariants.md`, `docs/ops.md`, `docs/testing.md`
- Create: `docs/README.md`

Task 5 läuft vor dem README-Umbau, damit die README auf fertige englische Seiten verlinkt.

- [ ] **Step 1: Bezeichner-Liste vor der Übersetzung sichern**

```bash
for f in architecture invariants ops testing; do grep -o '`[^`]*`' docs/$f.md | sort -u > verification/ids-$f-before.txt; done
```

- [ ] **Step 2: Übersetzen**

Treu ins Englische übersetzen, in der Sachlichkeit von `docs/models.md`. Tabellen, Code-Blöcke, Inline-Code und Dateipfade bleiben unverändert. Keine neuen Aussagen, keine weggelassenen Aussagen. Titel: `# Architecture`, `# Invariants`, `# Operations`, `# Testing`. Ausnahmen in Code-Blöcken:
- `docs/ops.md`, erster Code-Block: die Kommentare werden übersetzt („GUI, system Python“, „JSON, check local setup only“, „user launchers + PTT extension“, „diagnostics only, no installation“).
- `docs/testing.md`, Abschnitt „Visual preview“: die Befehle aus Task 3/4 mit `--language en` bzw. `en` dokumentieren. Den Satz „in beiden Sprachen“ ersetzen durch „in the selected language (`--language en|de`, default `de`)“.

Die Menütexte in `ops.md` („Modell jetzt laden“ / „Modell freigeben“) werden durch die englischen Strings aus `voicelens/i18n.py` ersetzt; die passenden Schlüssel dort nachschlagen.

- [ ] **Step 3: Bezeichner-Abgleich (gegen Übersetzungsdrift)**

```bash
for f in architecture invariants ops testing; do grep -o '`[^`]*`' docs/$f.md | sort -u > verification/ids-$f-after.txt; diff verification/ids-$f-before.txt verification/ids-$f-after.txt; done
```
Expected: Unterschiede nur bei übersetzten deutschen Inline-Texten, bei Menütexten und bei den neuen `--language`-Befehlen. Jeder entfernte Code-Bezeichner (`modul.name`, Pfad, Flag) ist ein Fehler.

- [ ] **Step 4: `docs/README.md` anlegen**

Titel `# Documentation`, eine Tabelle `| Page | What it covers |` mit diesen Seiten: `usage-de.md` (German quick guide), `models.md`, `architecture.md`, `invariants.md`, `ops.md`, `testing.md`, `release.md`, `releases/v0.2.0.md`, `releases/v0.1.0.md`. Die Beschreibungen sind jeweils ein Satz aus dem ersten Absatz der Seite.

- [ ] **Step 5: Tests und Commit**

Run: `/usr/bin/python3.12 -m unittest tests.test_docs -v` → PASS

```bash
git add docs
git commit -m "Translate developer documentation to English and add a docs index"
```

---

### Task 6: README neu aufbauen

**Files:**
- Modify: `README.md` (vollständig neu)

**Interfaces:**
- Consumes: Bilder aus Task 3/4, Badge-URL aus Task 2, `docs/README.md` aus Task 5.

- [ ] **Step 1: README in genau dieser Reihenfolge schreiben**

1. **Kopf (zentriert, HTML `<p align="center">`):** Icon `assets/voicelens.svg` mit 112 px, `<h1>VoiceLens</h1>`, fett „Hold Control. Speak. Release. Your words appear at the caret.“, darunter „Offline dictation for Linux desktops with local Whisper. No cloud, no account, no telemetry.“
2. **Badges (zentriert):**
   - `[![Tests](https://github.com/juvenile454/VoiceLens/actions/workflows/tests.yml/badge.svg)](https://github.com/juvenile454/VoiceLens/actions/workflows/tests.yml)`
   - `https://img.shields.io/github/v/release/juvenile454/VoiceLens?include_prereleases&label=release` → Link `/releases`
   - `https://img.shields.io/badge/license-MIT-86e6d0` → `LICENSE`
   - `https://img.shields.io/badge/Ubuntu-24.04-E95420?logo=ubuntu&logoColor=white`
   - `https://img.shields.io/badge/GNOME-46-4A86CF?logo=gnome&logoColor=white`
   - `https://img.shields.io/badge/runs-offline-0e151b`
3. **Navigationszeile:** `Quick start · Features · Install · Usage · Privacy · Docs · Deutsch` mit Ankern auf die Überschriften unten bzw. `docs/usage-de.md`.
4. **Demo:** `assets/demo/dictation-en.gif`, Breite 640, Unterschrift kursiv: „Synthetic preview rendered with the production overlay code. No recording.“
5. **`## Features`:** eine Tabelle mit 3 Spalten ohne Kopfzeilen-Text-Emojis:
   - **Private by design**: „Audio lives only in an anonymous memory file. No cloud, no account, no telemetry, no transcript history.“
   - **Dictate anywhere**: „Hold Control alone in any GNOME app. A small lens follows the caret and inserts the text when you release. Shortcuts like Ctrl+C keep working.“
   - **Local Whisper models**: „faster-whisper with Tiny up to Large v3 from your own disk. English and German for speech and interface.“

   Darunter `<details><summary>All features</summary>` mit der vollständigen bisherigen Feature-Liste aus der aktuellen README (wörtlich).
6. **`## Screenshots`:** eine 2×2-Tabelle mit `main.png`, `recording.png`, `result.png`, `settings-model.png` (jeweils `width="100%"`, kurze Unterschrift), darunter ein Link „German interface“ → `assets/screenshots/main-de.png`. Unterschrift: „Synthetic previews with a simulated microphone.“
7. **`## Supported platforms`:** Tabelle:

   | Platform | Status |
   |---|---|
   | Ubuntu 24.04 · GNOME 46 · Wayland · x86_64 | Tested: manual smoke test and automated suite |
   | Other GNOME versions, distributions, architectures | Untested; reports welcome |
   | Windows, macOS | Not supported |

8. **`## Quick start`:** Ein Satz „Assumes the Ubuntu packages from Install step 1.“ Danach ein `sh`-Block:
   ```sh
   git clone https://github.com/juvenile454/VoiceLens.git ~/VoiceLens   # keep this folder in place
   cd ~/VoiceLens
   /usr/bin/python3 -m venv .venv
   .venv/bin/python3 -m pip install -r requirements-stt.txt
   # put a model folder into ~/.local/share/voicelens/models/small/ (see docs/models.md)
   /usr/bin/python3 install.py --check
   /usr/bin/python3 install.py
   ./run.sh
   ```
9. **`## How it works`:** Mermaid-Diagramm:
   ```mermaid
   flowchart LR
     A["Hold Control<br/>or press Record"] --> B["ffmpeg records into<br/>an anonymous memory file"]
     B --> C["Separate worker process<br/>faster-whisper + local model"]
     C --> D["Text at the caret<br/>or in the window"]
     C -. "exits after each take by default" .-> E["Nothing stored on disk"]
   ```
   Darunter ein Satz mit Link auf `docs/architecture.md`.
10. **`## Install`:** Der vollständige bisherige Inhalt der Abschnitte 1–3 (wörtlich). Die Absätze zu Offline-Wheels, Constraints-Datei und Laufzeit-Suchreihenfolge kommen jeweils in ein `<details><summary>…</summary>`.
11. **`## Usage`:** die bisherigen Schritte 1–6 und die Absätze danach. Zusätzlich eine Tabelle `### Keyboard shortcuts` mit diesen Zeilen (Texte aus `voicelens/i18n.py`, Englisch): Hold **Control** alone → „Dictate into the focused window“, **Escape** → „Cancel the current recording or transcription“, **Ctrl+Shift+C** → „Copy the transcript“.
12. **`## Privacy`:** bisheriger Text wörtlich.
13. **`## Documentation`:** Link auf `docs/README.md`, dazu die drei wichtigsten Seiten (models, architecture, testing).
14. **`## Contributing`:** ein Satz mit Links auf `CONTRIBUTING.md`, `SECURITY.md` und das Bug-Report-Formular.
15. **`## License`:** bisheriger Text.

Die „Early release“-Notiz aus der alten README steht direkt unter den Badges als GitHub-Hinweisblock (`> [!NOTE]`).

- [ ] **Step 2: Vollständigkeit prüfen**

Jeden Absatz der alten README (`git show origin/main:README.md`) mit der neuen abgleichen. Jede Aussage muss wiederzufinden sein. Fehlendes ergänzen.

- [ ] **Step 3: Tests**

Run: `/usr/bin/python3.12 -m unittest tests.test_docs -v`
Expected: PASS. Anker wie `#quick-start` und `#supported-platforms` werden vom Anker-Test geprüft; `CONTRIBUTING.md` und `SECURITY.md` existieren erst nach Task 7 → Abschnitt 14 (Contributing) wird erst in Task 7 eingefügt.

- [ ] **Step 4: Rendering prüfen**

Pushen und die README auf GitHub (Branch-Ansicht) mit `mcp__github__get_file_contents` bzw. im Browser des Nutzers prüfen lassen: Mermaid gerendert, Bilder sichtbar, Badges laden (der Release-Badge zeigt bis zur Veröffentlichung „no releases“ – erwartet).

- [ ] **Step 5: Commit und Push**

```bash
git add README.md
git commit -m "Restructure the README for first-time visitors"
git push -u origin claude/wizardly-wright-bbkfi9
```

---

### Task 7: Community-Dateien und Changelog

**Files:**
- Create: `CONTRIBUTING.md`, `CHANGELOG.md`, `SECURITY.md`, `.github/ISSUE_TEMPLATE/feature_request.yml`, `.github/ISSUE_TEMPLATE/config.yml`
- Modify: `.github/pull_request_template.md`, `tests/test_docs.py`, `README.md` (Abschnitt Contributing)

**Interfaces:**
- Consumes: `markdown_files()` aus Task 1.

- [ ] **Step 1: Test schreiben**

```python
def test_changelog_top_entry_matches_version(self):
    text = (ROOT / 'CHANGELOG.md').read_text()
    versions = re.findall(r'^## \[(\d+\.\d+\.\d+)\]', text, re.M)
    self.assertEqual(versions[0], voicelens.__version__)
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `/usr/bin/python3.12 -m unittest tests.test_docs -v` → FAIL (`CHANGELOG.md` fehlt)

- [ ] **Step 3: `CHANGELOG.md`**

Format „Keep a Changelog“. Abschnitte: `## [Unreleased]` (Repository presentation: README, screenshots, demo GIF, CI, English docs, community files), `## [0.2.0] - 2026-09-24` und `## [0.1.0] - 2026-09-13`. Die Inhalte kommen aus `docs/releases/v0.2.0.md` bzw. `v0.1.0.md`, gekürzt auf Stichpunkte unter `### Added` / `### Changed`. Link-Referenzen unten auf die Release-Notiz-Dateien.

- [ ] **Step 4: `CONTRIBUTING.md`**

Abschnitte:
- *Ground rules*: Privacy (keine Aufnahmen, Transkripte, persönlichen Pfade in Issues/PRs/Tests), Offline-Invarianten mit Link auf `docs/invariants.md`, keine Netz- oder Credential-Zugriffe in Tests.
- *Development setup*: apt-Liste aus der README plus `xvfb gjs`.
- *Running tests*: die beiden Befehle aus `docs/testing.md`.
- *Previews*: die Befehle aus Task 3/4.
- *Translations*: neue UI-Strings immer in `en` und `de` in `voicelens/i18n.py`.
- *Pull requests*: PR-Vorlage ausfüllen, Doubles und echte Geräte-/Modelltests unterscheiden.

- [ ] **Step 5: `SECURITY.md`**

Tabelle Supported versions (`0.2.x` ✅, `< 0.2` ❌). Melden über GitHubs private Meldefunktion: Link `https://github.com/juvenile454/VoiceLens/security/advisories/new`. Hinweis: keine öffentlichen Issues für Sicherheitslücken, keine privaten Aufnahmen anhängen. Keine E-Mail-Adresse.

- [ ] **Step 6: Issue-Formulare und PR-Vorlage**

- `feature_request.yml`: Name „Feature request“, Titel-Präfix `[Feature]: `, Felder: *Problem* (textarea, Pflicht), *Proposed solution* (textarea, Pflicht), *Alternatives considered* (textarea), *Platform* (input, Platzhalter „Ubuntu 24.04, GNOME 46, Wayland“).
- `config.yml`: `blank_issues_enabled: false`. `contact_links`: „Setup help“ → `https://github.com/juvenile454/VoiceLens#install`, „Security issue“ → die Advisory-URL aus Step 5.
- `pull_request_template.md`: die drei vorhandenen Abschnitte als `## `-Überschriften behalten und eine Checkliste anhängen: `- [ ] Tests pass under xvfb`, `- [ ] New UI strings exist in en and de`, `- [ ] No recordings, transcripts or personal paths included`, `- [ ] Docs updated if behaviour changed`.

- [ ] **Step 7: README-Abschnitt Contributing ergänzen** (siehe Task 6, Punkt 14)

- [ ] **Step 8: Tests und Commit**

Run: `env -u WAYLAND_DISPLAY GDK_BACKEND=x11 xvfb-run -a /usr/bin/python3.12 -m unittest discover -s tests -p 'test_*.py'` → OK

```bash
git add CONTRIBUTING.md CHANGELOG.md SECURITY.md .github tests/test_docs.py README.md
git commit -m "Add contributing guide, changelog, security policy and issue forms"
git push -u origin claude/wizardly-wright-bbkfi9
```

---

### Task 8: Abschluss

**Files:**
- Delete: `docs/superpowers/` (dieser Plan; gehört nicht ins öffentliche Repo)

- [ ] **Step 1: Gesamtprüfung**

Run: kompletter Testlauf (wie Task 7, Step 8) → OK. Danach den CI-Lauf des letzten Pushes prüfen (`mcp__github__actions_list`) → success.

- [ ] **Step 2: Abschluss-Review**

`superpowers:requesting-code-review` auf den gesamten Branch-Diff gegen `main`. Schwerpunkt: Review Focus 1–5 und die Global Constraints (keine Änderungen an App-Code, keine neuen Behauptungen).

- [ ] **Step 3: Plan entfernen, Commit, Push**

```bash
git rm -r docs/superpowers
git commit -m "Remove internal implementation plan"
git push -u origin claude/wizardly-wright-bbkfi9
```

- [ ] **Step 4: Dem Nutzer berichten** und anbieten, einen PR zu erstellen.

---

## Manuelle Schritte für den Maintainer (nicht automatisierbar)

Nach dem Merge in `main`:

1. **Release v0.2.0 veröffentlichen:** GitHub → Releases → *Draft a new release* → Tag `v0.2.0` auf dem Merge-Commit. Titel „VoiceLens 0.2.0“, Text aus `docs/releases/v0.2.0.md`, `assets/screenshots/main.png` als Bild einbetten. Als *Pre-release* markieren, weil „early release“. Den alten v0.1.0-Entwurf veröffentlichen (Tag auf `4d1d3c1`) oder löschen.
2. **Social Preview:** Settings → General → Social preview → `assets/social/social-preview.png` hochladen.
3. **Private Sicherheitsmeldungen aktivieren:** Settings → Code security → *Private vulnerability reporting* → Enable (sonst führt der Link in `SECURITY.md` ins Leere).
4. **Optional:** Im „About“-Feld der Repo-Startseite einen Link auf das Release setzen.
