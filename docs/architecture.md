# Architektur

Kleine native App: sprechen → transkribieren → Text. Default-UI Englisch, umschaltbar auf Deutsch.

Start: `run.sh` → `/usr/bin/python3 -m voicelens` (`voicelens/__main__.py`). Ohne Flags GUI; `--list-microphones` / `--transcribe FILE` nur JSON auf stdout.

## Module

| Pfad | Rolle |
|---|---|
| `voicelens/__main__.py` | CLI vs. GUI; startet nie implizit eine Aufnahme |
| `voicelens/ui.py` | GTK3-Fenster, Single-Instance `org.voicelens.VoiceLens`, Settings-Dialog |
| `voicelens/visualizer.py`, `assets/ui.css` | Native Lichtlinse, gemeinsame Gestaltung von Hauptfenster und Einstellungen; statisch im Leerlauf |
| `voicelens/controller.py` | Eine Hintergrundoperation; Events in eine Queue, GTK liest sie |
| `voicelens/backend.py` | Mikrofone (`pactl`), ffmpeg-Aufnahme in memfd, Spawn von Guard+Worker |
| `voicelens/guard.py` | `prctl(PDEATHSIG)` plus Race-Check, dann `exec` des Kindes |
| `voicelens/worker.py` | One-shot faster-whisper im STT-Interpreter; JSON auf stdout; danach Exit |
| `voicelens/settings.py` | `~/.config/voicelens/settings.json`, lokaler Modellkatalog, keine Downloads |
| `voicelens/diagnostics.py` | Nur lesende Einrichtungsprüfung für Installer und CLI: Abhängigkeiten, Geräte, vollständige Modelle |
| `voicelens/i18n.py` | UI-Strings; Default `en` |
| `voicelens/hotkey.py` | Steuerung-halten-State-Machine (`HOLD_SECONDS`) |
| `voicelens/inject.py` | Text an Caret: AT-SPI, sonst Zwischenablage + GNOME-Helper-Paste |
| `voicelens/shell_ext.py` | Benutzer-GNOME-Erweiterung kopieren/aktivieren |
| `gnome-shell-extension/` | Compositor-Modifier, Cursor-Overlay, D-Bus `PttHelper`; `lens.js` enthält Cairo-Renderer und Geometrie |
| `install.py` | Nur User-Launcher + Erweiterung; kein Systemdienst |
| `assets/` | Icon, `.desktop.in` |
| `tests/` | Isolierte Tests; Testdoubles sind in den Dateiköpfen als solche markiert |

## Aufnahme / STT

```
GTK (System-Python) ──queue──► controller-Thread
                                 ├─ ffmpeg via guard.py  → anonymes memfd WAV (16 kHz mono)
                                 └─ STT-Python via guard.py → worker.py → JSON → Exit
GUI importiert keine STT-Bibliotheken. Erfolg erst nach Abholen des Kindes (`model_unloaded`).
```

ffmpeg und Worker laufen in neuer Session (`start_new_session`) mit `pass_fds` nur für den memfd. Umgebung des Workers ist eine Allowlist plus `HF_*_OFFLINE=1`.

Beim Start/Refresh prüft ein Hintergrundthread die STT-Umgebung mit `worker.py --check` über den Guard, ohne Modell oder Audio zu laden. UI-Updates laufen über die Queue. Der Diagnose-Worker wird auch bei Abbruch/Timeout beendet und abgeholt. Im Leerlauf aktualisiert die UI regelmäßig ausschließlich die Mikrofonliste; unveränderte Listen überschreiben keine Ergebnisanzeige. Die automatische Auswahl wird bei Aufnahmestart erneut gegen die aktuelle Systemauswahl aufgelöst.

## Push-to-Talk

Steuerung **allein** halten startet Diktat; Akkorde (Strg+C usw.) brechen ab bzw. starten nicht.

| Kontext | Quelle |
|---|---|
| VoiceLens-Fenster fokussiert | GDK in `ui.py` → `hotkey.PushToTalk` |
| Anderes Fenster, GNOME Wayland | Erweiterung liest Compositor-Modifier (nicht Fenstertasten) und feuert App-Actions `ptt-down` / `ptt-up` / `ptt-chord` |

Ablauf: Fokus-/Caret-Snapshot → Aufnahme (`inject=True`) → Overlay `ShowSession`/`SetLevel` → Transkription und vollständiges Worker-Cleanup → Zustand `settling` → asynchrones `FinishSession` bestätigt die Rückkehranimation → `inject_text` (AT-SPI, sonst Helper-`Paste`, sonst nur Zwischenablage). Erst danach wird die UI wieder freigegeben. Abbruch/Schließen entwerten ausstehende Rückrufe.

Caret-Geometrie kommt bevorzugt aus GNOMEs Input-Method-Signal, dann aus IBus und schließlich aus AT-SPI-Zeichenkoordinaten. Direkte IBus-Clients (unter anderem Electron/XWayland) benötigen keinen `Main.inputMethod.currentFocus`. Absolute IBus-Rechtecke kommen vom Shell-IBusManager; der optionale relative Panel-Service meldet Koordinaten bezogen auf den Compositor-Fensterursprung. Die Erweiterung liest nur Geometrie/Fokus, keine Textinhalte. Fokuswechsel und IBus-Neustarts verwerfen alte Rechtecke; alle Signalverbindungen werden beim Deaktivieren entfernt. Ungültige Rechtecke verdecken keine gültige Ersatzquelle.

Ohne gültige Geometrie schwebt die Linse am aktiven Fenster; es wird keine Cursorposition geraten. Sie fliegt frei zwischen Caret und Schwebeort, ohne Verbindungslinie oder zusätzlich gezeichneten Cursor. Statushinweise blenden nach kurzer Anzeige aus (`lens.js`: `labelOpacity`); identische Wiederholungen starten die Anzeige nicht neu. Zeichenroutine auf einer kleinen Fläche mit begrenzter Bildrate, ohne Neuzeichnungen im verborgenen Zustand. Die GNOME-Einstellung für reduzierte Animationen wird berücksichtigt. Fokuswechsel/Sperren melden `ptt-cancel` unabhängig vom Zustand der Steuerungstaste. Alte Erweiterungen bleiben über `ShowStatus` nutzbar, bis die neue Version geladen wurde.

Einfügen: AT-SPI bleibt der erste Versuch. Beim Clipboard-Fallback übergibt `PasteWithOptions` zusätzlich die AT-SPI-Terminalrolle; der Helper erkennt eigenständige Terminals auch anhand ihrer App-ID/WM-Klasse (keine Fenstertitel). Terminals erhalten Strg+Umschalt+V, andere Textfelder Strg+V; es wird keine Enter-Taste angehängt. Der Fokus wird vor den verzögerten Tastensignalen erneut geprüft. Ein unbekanntes D-Bus-Verfahren erlaubt den Rückfall auf `Paste` für normale Apps; bei Timeouts wird nicht erneut eingefügt.

D-Bus-Name: `inject.HELPER_NAME`. Erweiterungs-UUID: `shell_ext.UUID`.
