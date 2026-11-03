# Invariants

Do not break these. Values and lists live in the code named here; do not copy them here.

## Process and memory

- Whisper only in `voicelens/worker.py`, interpreter from `backend._stt_python()`. The GUI process does not import the model (`ui.py`).
- Default (`keep_model = release`): `backend.transcribe_file` returns only after the worker has exited and been reaped. Only then may the UI show success/`model_unloaded` (`controller.py`).
- Only with opt-in (`keep_model = timed|always`) does a resident worker (`backend.ModelSession`, `worker.py --serve`) stay loaded between recordings. It is a child of the GUI process with guard/`PDEATHSIG`; audio reaches it only as a passed memfd descriptor (`ipc.py`, `SCM_RIGHTS`). Timeout, policy change, model change, cancel and window close end and reap it (`controller.release_model`). The footer shows while a model is loaded. No model is loaded at start, unless the user chose "Keep loaded".
- The ffmpeg recorder and the worker are started through `guard.py` (`PDEATHSIG` + parent-PID check before and after `prctl`). Do not kill foreign PIDs; only the own process group (`backend._stop_process`).
- Cancel, error, timeout and window close clean up children and the memfd (`Recorder.close`, `ui.py` `_close`).

## Audio and privacy

- No recording at start. Reading the device list is allowed; capture only after Record or PTT start (`__main__.py`, `backend.Recorder.start`).
- Raw audio only in the anonymous memfd (`backend._create_memfd`), close-on-exec, `pass_fds` targeted. No named capture, no transcript history.
- Do not offer monitor sources as a microphone (`backend._source_is_monitor`). Silent/missing sources become an `AppError` with i18n text.
- One recording ≤ `MAX_RECORD_SECONDS` (backend). One active operation (`controller.busy`).

## Transcript

- A new successful transcription replaces the text; only with the opt-in setting `append_transcript` is it appended below the previous text. Errors, cancel and empty recognition leave the previous text in place (`ui.py`).
- `auto_copy` (opt-in) writes the new result to the system clipboard; without the setting only on explicit copy or as the insertion fallback.
- App languages: `i18n.SUPPORTED_LANGUAGES`. Default `en`.

## Offline

- The worker sets `HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE` / `HF_DATASETS_OFFLINE` before the faster-whisper import. `WhisperModel(..., local_files_only=True)`.
- Model path only from the local Hugging Face cache, the user's VoiceLens model directory or `VOICELENS_MODEL_PATH` — see `settings.resolve_model_path`. Download nothing.

## Push-to-talk

- Control alone only; other keys while holding → `cancel`/`disarm` (`hotkey.py`). Do not swallow shortcuts (extension: `EVENT_PROPAGATE`).
- Never treat the own window as "foreign" for insertion (`inject.OWN_APP_NAMES`). No global key grabbing in Python.
- The overlay stays visible until the text is inserted or cancelled (extension + `ui.py` `_ptt_osd*`).

## Desktop

- Single instance via `Gtk.Application` / `APP_ID`. A second activation shows the same window.
- No autostart, no systemd, no packages in system Python or in other applications' environments. Launchers only for the current user (`install.py`).
