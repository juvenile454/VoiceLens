# Architecture

Small native app: speak → transcribe → text. The default UI language is English and can be switched to German.

Start: `run.sh` → `/usr/bin/python3 -m voicelens` (`voicelens/__main__.py`). Without flags it starts the GUI; `--list-microphones` / `--transcribe FILE` only print JSON to stdout.

## Modules

| Path | Role |
|---|---|
| `voicelens/__main__.py` | CLI vs. GUI; never starts a recording implicitly |
| `voicelens/ui.py` | GTK3 window, single instance `org.voicelens.VoiceLens`, settings dialog (General/Model pages), keyboard shortcut dialog, header menu |
| `voicelens/visualizer.py`, `assets/ui.css` | Native light lens, shared styling of main window and settings; static when idle |
| `voicelens/controller.py` | One background operation; events go into a queue that GTK reads; optionally holds the resident worker together with its idle timer |
| `voicelens/backend.py` | Microphones (`pactl`), ffmpeg recording into a memfd, spawn of guard + worker |
| `voicelens/guard.py` | `prctl(PDEATHSIG)` plus race check, then `exec` of the child |
| `voicelens/worker.py` | faster-whisper in the STT interpreter: one-shot (JSON on stdout, then exit) or resident with `--serve` (requests over a socket, the model stays loaded) |
| `voicelens/ipc.py` | Line-based JSON over a Unix socket plus descriptor passing (`SCM_RIGHTS`); shared by GUI and worker |
| `voicelens/settings.py` | `~/.config/voicelens/settings.json`, local model catalog, no downloads |
| `voicelens/diagnostics.py` | Read-only setup check for installer and CLI: dependencies, devices, complete models |
| `voicelens/i18n.py` | UI strings; default `en` |
| `voicelens/hotkey.py` | Hold-Control state machine (`HOLD_SECONDS`) |
| `voicelens/inject.py` | Text at the caret: AT-SPI, otherwise clipboard + GNOME helper paste |
| `voicelens/shell_ext.py` | Copy/enable the user GNOME extension |
| `gnome-shell-extension/` | Compositor modifier, cursor overlay, D-Bus `PttHelper`; `lens.js` contains the Cairo renderer and geometry |
| `install.py` | User launchers + extension only; no system service |
| `assets/` | Icon, `.desktop.in` |
| `tests/` | Isolated tests; test doubles are marked as such in the file headers |

## Recording / STT

```
GTK (system Python) ──queue──► controller thread
                                 ├─ ffmpeg via guard.py  → anonymous memfd WAV (16 kHz mono)
                                 └─ STT Python via guard.py → worker.py → JSON → exit
                                    or (opt-in) resident worker.py --serve ◄─socket+memfd fd─► ModelSession
The GUI imports no STT libraries. Without a keep policy, success is reported only after the child has been reaped (`model_unloaded`);
with a policy the resident worker answers (`resident`), stays a child with PDEATHSIG, and is ended and reaped via
`controller.release_model` on timeout, policy/model change, cancel or close.
```

ffmpeg and the worker run in a new session (`start_new_session`) with `pass_fds` only for the memfd. The worker's environment is an allowlist plus `HF_*_OFFLINE=1`.

On start/refresh a background thread checks the STT environment with `worker.py --check` through the guard, without loading a model or audio. UI updates go through the queue. The diagnostic worker is also ended and reaped on cancel/timeout. While idle, the UI periodically refreshes only the microphone list; unchanged lists do not overwrite a displayed result. Automatic selection is resolved again against the current system selection when a recording starts.

## Push-to-talk

Holding Control **alone** starts dictation; chords (Ctrl+C etc.) cancel or do not start it.

| Context | Source |
|---|---|
| VoiceLens window focused | GDK in `ui.py` → `hotkey.PushToTalk` |
| Another window, GNOME Wayland | The extension reads the compositor modifier (not window keys) and fires the app actions `ptt-down` / `ptt-up` / `ptt-chord` |

Flow: focus/caret snapshot → recording (`inject=True`) → overlay `ShowSession`/`SetLevel` → transcription and complete worker cleanup → state `settling` → asynchronous `FinishSession` confirms the return animation → `inject_text` (AT-SPI, otherwise helper `Paste`, otherwise clipboard only). Only then is the UI released again. Cancel/close invalidate pending callbacks.

Caret geometry preferably comes from GNOME's input-method signal, then from IBus, and finally from AT-SPI character coordinates. Direct IBus clients (including Electron/XWayland) do not need `Main.inputMethod.currentFocus`. Absolute IBus rectangles come from the shell IBusManager; the optional relative panel service reports coordinates relative to the compositor window origin. The extension reads only geometry/focus, no text content. Focus changes and IBus restarts discard old rectangles; all signal connections are removed on disable. Invalid rectangles do not hide a valid fallback source.

Without valid geometry the lens hovers at the active window; no cursor position is guessed. It flies freely between caret and hover position, without a connecting line or an additionally drawn cursor. Status hints fade out after a short display (`lens.js`: `labelOpacity`); identical repeats do not restart the display. The drawing routine uses a small surface with a limited frame rate and no redraws while hidden. The GNOME setting for reduced animations is respected. Focus changes/locking report `ptt-cancel` regardless of the state of the Control key. Old extensions remain usable through `ShowStatus` until the new version has been loaded.

Insertion: AT-SPI remains the first attempt. For the clipboard fallback, `PasteWithOptions` additionally passes the AT-SPI terminal role; the helper also recognises standalone terminals by their app ID/WM class (no window titles). Terminals receive Ctrl+Shift+V, other text fields Ctrl+V; no Enter key is appended. Focus is checked again before the delayed key signals. An unknown D-Bus method allows falling back to `Paste` for normal apps; on timeouts the text is not inserted again.

D-Bus name: `inject.HELPER_NAME`. Extension UUID: `shell_ext.UUID`.
