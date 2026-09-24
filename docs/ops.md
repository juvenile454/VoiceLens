# Betrieb

## Start

```sh
./run.sh                          # GUI, System-Python
./run.sh --list-microphones       # JSON
./run.sh --check                 # JSON, nur lokale Einrichtung prüfen
./run.sh --transcribe FILE [--language en|de] [--model small]
/usr/bin/python3 install.py       # User-Launcher + PTT-Erweiterung
/usr/bin/python3 install.py --check --language de  # nur Diagnose, keine Installation
```

`run.sh` wechselt in den Projektordner und `exec`’t `/usr/bin/python3 -m voicelens`. Das Projekt muss an seinem Pfad bleiben, weil die `.desktop`-Exec darauf zeigt.

## Umgebungsvariablen

| Variable | Zweck |
|---|---|
| `VOICELENS_STT_PYTHON` | Absoluter Interpreter mit faster-whisper. Überschreibt die automatische Auswahl. |
| `VOICELENS_MODEL_PATH` | Vorhandener vollständiger CTranslate2-Modellordner; Vorrang für die zugeordnete Modellgröße. |
| `VOICELENS_MODEL_ID` | Modellgröße für einen beliebig benannten eigenen Modellordner. |
| `HF_HUB_CACHE`, `HUGGINGFACE_HUB_CACHE`, `HF_HOME`, `XDG_CACHE_HOME` | Lokaler Hugging-Face-Cache, Priorität in `settings.cache_dir`. |
| `XDG_DATA_HOME` | Benutzer-Modelle/-Umgebung und Launcher; Standard laut XDG. |
| `VOICELENS_MODEL` / `VOICELENS_LANGUAGE` | Setzt der Parent für den Worker; nicht als User-API dokumentieren. |

Automatische Interpreter-Reihenfolge: Projekt-`.venv`, Benutzer-VoiceLens-Venv, System-Python (`backend.stt_python_candidates`). Umgebungen anderer Anwendungen werden nicht durchsucht. Es wird der erste ausführbare Pfad gewählt. Eine kaputte frühere Umgebung wird als Fehler gemeldet; mit `VOICELENS_STT_PYTHON` lässt sich eine funktionierende ausdrücklich auswählen. Pakete nur in eine eigene VoiceLens-Venv installieren. Die Einrichtungsprüfung importiert STT nur im bewachten Worker, prüft CPU-INT8-Unterstützung, beendet ihn und holt ihn ab. Sie lädt keine Gewichte und startet keine Aufnahme.

Umgebungsvariablen in einem Terminal gelten nicht automatisch für das Anwendungsmenü. Für Launcher möglichst die automatisch erkannten VoiceLens-Verzeichnisse verwenden oder die Variablen bereits in der Desktop-Sitzung setzen.

## Modelle

Katalog und RAM-Hinweise: `settings.WHISPER_MODELS`. Vollständigkeit: `settings.missing_model_files`. Gesucht werden ein zugeordneter expliziter Ordner, Benutzer-Modelle und Hugging-Face-Snapshots; es wird nichts geholt. Modellquellen und Formate: [models.md](models.md). Vorauswahl ohne gespeichertes Modell: `settings.initial_model`; gespeicherte Entscheidungen bleiben erhalten.

Persistenz: `~/.config/voicelens/settings.json` (`language`, `model`, `push_to_talk`, `append_transcript`, `auto_copy`, `keep_model` = `release`|`timed`|`always`, `keep_minutes` 1–720). Fehlende oder ungültige Schlüssel fallen auf die Standardwerte zurück (`release`, 10 Minuten).

Modell im Speicher: `release` startet pro Aufnahme einen Worker und holt ihn ab. `timed` hält den Worker `keep_minutes` nach der letzten Nutzung (Fußzeile zeigt die Restzeit), `always` hält ihn bis Modell-/Policy-Wechsel oder Schließen und lädt ihn schon beim App-Start. Ladezeitlimit: `backend.MODEL_LOAD_TIMEOUT`. Menü: „Modell jetzt laden“ / „Modell freigeben“. Ein Abbruch während der Transkription beendet den residenten Worker; die nächste Aufnahme lädt neu.

`install.py --check` verändert keine Einstellungen. Die Installation speichert die vorhandene/vorausgewählte Modellwahl nur bei lokal verfügbarem Modell. Mikrofone werden frisch erkannt und nicht als veraltende Geräteliste gespeichert.

## Launcher

`install.py` prüft zuerst GTK/Cairo, Audio-Werkzeuge, STT-Umgebung, Mikrofone und Modelle. Die Ausgabe ist standardmäßig lesbarer Text; `--json` liefert strukturierte Daten. `--check` liefert Exit 0 bei vollständiger Einrichtung, sonst 1. Normale Installation kann trotz fehlendem Mikrofon/Modell Launcher bereitstellen; die Diagnose bleibt im Ergebnis sichtbar.

`install.py` schreibt Benutzer-Launcher, Erweiterung und Einstellungen:

- `~/.local/share/applications/org.voicelens.VoiceLens.desktop`
- `$(xdg-user-dir DESKTOP)/VoiceLens.desktop` nur für einen vorhandenen, aktivierten Schreibtischordner (`metadata::trusted=true`)
- GNOME-Erweiterung in einer GNOME-Sitzung nach `~/.local/share/gnome-shell/extensions/<UUID>/`
- Einstellungen laut `settings.settings_path`

Weicht ein vorhandener Launcher ab und zeigt noch auf eine existierende Exec, bricht die Installation ab. Fremde oder alte Entwicklungs-Launcher werden nicht entfernt. Kein Autostart, kein systemd.

## GNOME Push-to-Talk

UUID und Dateien: `voicelens/shell_ext.py`. Quelle: `gnome-shell-extension/`.

Nach Änderung an `extension.js` / `lens.js` / `stylesheet.css`: `install.py` bzw. `shell_ext.ensure()` beim Start kopiert und versucht disable/enable. Unter GNOME 46 bleibt alter Erweiterungscode oft im Speicher — einmal **ab- und anmelden**. Im VoiceLens-Fenster selbst funktioniert Steuerung halten auch ohne Erweiterung. Das Cursor-Overlay benötigt die neue Erweiterung; solange die alte Version geladen ist, nutzt die App deren bisherige Statusanzeige.

IBus-Cursorpositionen und Terminal-Paste benötigen ebenfalls den aktualisierten Helper. Erkennt die App eine Terminalrolle, aber der geladene Helper kennt `PasteWithOptions` noch nicht, bleibt das Ergebnis in der Zwischenablage (manuell Strg+Umschalt+V). Fehlende Cursorinformationen einer Anwendung lassen sich nicht durch das Raten von Positionen ersetzen; dann bleibt die Fensterposition der Rückfall.

Abhängigkeiten: GTK3/PyGObject/Cairo, `ffmpeg`, `pactl`, PipeWire/Pulse-Benutzersitzung, STT-Interpreter mit faster-whisper, lokales Modell. Manuelle Vorbereitung auf einem neuen Rechner steht in [README.md](../README.md). Installer und App laden keine Pakete oder Modelle herunter.
