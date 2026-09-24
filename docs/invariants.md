# Invarianten

Nicht brechen. Werte und Listen stehen im genannten Code, nicht hier kopieren.

## Prozess und Speicher

- Whisper nur in `voicelens/worker.py`, Interpreter aus `backend._stt_python()`. GUI-Prozess importiert das Modell nicht (`ui.py`).
- Standard (`keep_model = release`): `backend.transcribe_file` kehrt erst zurück, nachdem der Worker beendet und abgeholt ist. Erst dann darf die UI Erfolg/`model_unloaded` zeigen (`controller.py`).
- Nur mit Opt-in (`keep_model = timed|always`) bleibt ein residenter Worker (`backend.ModelSession`, `worker.py --serve`) zwischen Aufnahmen geladen. Er ist ein Kind des GUI-Prozesses mit Guard/`PDEATHSIG`; Audio erreicht ihn nur als übergebener memfd-Deskriptor (`ipc.py`, `SCM_RIGHTS`). Zeitablauf, Policy-Wechsel, Modellwechsel, Abbruch und Fensterschließen beenden und holen ihn ab (`controller.release_model`). Die Fußzeile zeigt, solange ein Modell geladen ist. Kein Modell wird beim Start geladen, außer der Benutzer hat „Dauerhaft behalten“ gewählt.
- ffmpeg-Recorder und Worker werden über `guard.py` gestartet (`PDEATHSIG` + Parent-PID-Check vor und nach `prctl`). Keine fremden PIDs killen; nur die eigene Prozessgruppe (`backend._stop_process`).
- Abbruch, Fehler, Timeout und Fensterschließen räumen Kinder und den memfd ab (`Recorder.close`, `ui.py` `_close`).

## Audio und Datenschutz

- Keine Aufnahme beim Start. Geräteliste lesen ist erlaubt; Capture erst nach Record oder PTT-Start (`__main__.py`, `backend.Recorder.start`).
- Rohaudio nur im anonymen memfd (`backend._create_memfd`), close-on-exec, `pass_fds` gezielt. Kein benannter Mitschnitt, keine Transkript-Historie.
- Monitorquellen nicht als Mikrofon anbieten (`backend._source_is_monitor`). Stumme/fehlende Quellen als `AppError` mit i18n-Text.
- Eine Aufnahme ≤ `MAX_RECORD_SECONDS` (backend). Eine aktive Operation (`controller.busy`).

## Transkript

- Neue erfolgreiche Transkription ersetzt den Text; nur mit der Opt-in-Einstellung `append_transcript` wird sie unter den bisherigen Text angehängt. Fehler, Abbruch und leere Erkennung lassen den bisherigen Text stehen (`ui.py`).
- `auto_copy` (Opt-in) schreibt das neue Ergebnis in die Systemzwischenablage; ohne die Einstellung nur bei ausdrücklichem Kopieren oder als Einfüge-Fallback.
- Sprachen der App: `i18n.SUPPORTED_LANGUAGES`. Default `en`.

## Offline

- Worker setzt `HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE` / `HF_DATASETS_OFFLINE` vor dem faster-whisper-Import. `WhisperModel(..., local_files_only=True)`.
- Modellpfad nur lokaler Hugging-Face-Cache, Benutzer-VoiceLens-Modellverzeichnis oder `VOICELENS_MODEL_PATH` — siehe `settings.resolve_model_path`. Nichts herunterladen.

## Push-to-Talk

- Nur Steuerung allein; andere Tasten während des Haltens → `cancel`/`disarm` (`hotkey.py`). Shortcuts nicht schlucken (Erweiterung: `EVENT_PROPAGATE`).
- Einfügen nie in das eigene Fenster als „fremd“ (`inject.OWN_APP_NAMES`). Kein globales Key-Grabbing in Python.
- Overlay bleibt sichtbar, bis der Text eingefügt oder abgebrochen ist (Erweiterung + `ui.py` `_ptt_osd*`).

## Desktop

- Single-Instance über `Gtk.Application` / `APP_ID`. Zweite Aktivierung zeigt dasselbe Fenster.
- Kein Autostart, kein systemd, keine Pakete in System-Python oder Umgebungen anderer Anwendungen. Launcher nur für den aktuellen Benutzer (`install.py`).
