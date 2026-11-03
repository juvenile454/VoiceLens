# Operations

## Start

```sh
./run.sh                          # GUI, system Python
./run.sh --list-microphones       # JSON
./run.sh --check                 # JSON, check local setup only
./run.sh --transcribe FILE [--language en|de] [--model small]
/usr/bin/python3 install.py       # user launchers + PTT extension
/usr/bin/python3 install.py --check --language de  # diagnostics only, no installation
```

`run.sh` changes into the project folder and `exec`s `/usr/bin/python3 -m voicelens`. The project must stay at its path because the `.desktop` Exec points to it.

## Environment variables

| Variable | Purpose |
|---|---|
| `VOICELENS_STT_PYTHON` | Absolute interpreter with faster-whisper. Overrides the automatic selection. |
| `VOICELENS_MODEL_PATH` | Existing complete CTranslate2 model folder; takes precedence for the assigned model size. |
| `VOICELENS_MODEL_ID` | Model size for a custom model folder with an arbitrary name. |
| `HF_HUB_CACHE`, `HUGGINGFACE_HUB_CACHE`, `HF_HOME`, `XDG_CACHE_HOME` | Local Hugging Face cache, priority in `settings.cache_dir`. |
| `XDG_DATA_HOME` | User models/environment and launchers; default per XDG. |
| `VOICELENS_MODEL` / `VOICELENS_LANGUAGE` | Set by the parent for the worker; do not document as user API. |

Automatic interpreter order: project `.venv`, user VoiceLens venv, system Python (`backend.stt_python_candidates`). Environments of other applications are not searched. The first executable path is chosen. A broken earlier environment is reported as an error; `VOICELENS_STT_PYTHON` can be used to explicitly select a working one. Install packages only into a dedicated VoiceLens venv. The setup check imports STT only in the guarded worker, checks CPU INT8 support, ends the worker and reaps it. It loads no weights and starts no recording.

Environment variables in a terminal do not automatically apply to the application menu. For launchers, preferably use the automatically detected VoiceLens directories or set the variables in the desktop session already.

## Models

Catalog and RAM hints: `settings.WHISPER_MODELS`. Completeness: `settings.missing_model_files`. Searched are an assigned explicit folder, user models and Hugging Face snapshots; nothing is fetched. Model sources and formats: [models.md](models.md). Preselection without a saved model: `settings.initial_model`; saved decisions are kept.

Persistence: `~/.config/voicelens/settings.json` (`language`, `model`, `push_to_talk`, `append_transcript`, `auto_copy`, `keep_model` = `release`|`timed`|`always`, `keep_minutes` 1–720). Missing or invalid keys fall back to the defaults (`release`, 10 minutes).

Model in memory: `release` starts a worker per recording and reaps it. `timed` keeps the worker for `keep_minutes` after the last use (the footer shows the remaining time), `always` keeps it until a model/policy change or close and loads it already at app start. Load time limit: `backend.MODEL_LOAD_TIMEOUT`. Menu: "Load model now" / "Release model". Cancelling during transcription ends the resident worker; the next recording loads again.

`install.py --check` changes no settings. The installation saves the existing/preselected model choice only if the model is available locally. Microphones are detected fresh and not stored as an ageing device list.

## Launchers

`install.py` first checks GTK/Cairo, audio tools, the STT environment, microphones and models. The output is human-readable text by default; `--json` provides structured data. `--check` exits 0 when the setup is complete, otherwise 1. A normal installation can provide launchers despite a missing microphone/model; the diagnostics remain visible in the result.

`install.py` writes user launchers, the extension and settings:

- `~/.local/share/applications/org.voicelens.VoiceLens.desktop`
- `$(xdg-user-dir DESKTOP)/VoiceLens.desktop` only for an existing, enabled desktop folder (`metadata::trusted=true`)
- GNOME extension in a GNOME session to `~/.local/share/gnome-shell/extensions/<UUID>/`
- Settings per `settings.settings_path`

If an existing launcher differs and still points to an existing Exec, the installation aborts. Foreign or old development launchers are not removed. No autostart, no systemd.

## GNOME push-to-talk

UUID and files: `voicelens/shell_ext.py`. Source: `gnome-shell-extension/`.

After changes to `extension.js` / `lens.js` / `stylesheet.css`: `install.py` or `shell_ext.ensure()` at start copies and tries disable/enable. Under GNOME 46, old extension code often stays in memory — **log out and back in** once. In the VoiceLens window itself, holding Control works even without the extension. The cursor overlay needs the new extension; while the old version is loaded, the app uses its previous status display.

IBus cursor positions and terminal paste also need the updated helper. If the app detects a terminal role but the loaded helper does not yet know `PasteWithOptions`, the result stays in the clipboard (paste manually with Ctrl+Shift+V). Missing cursor information from an application cannot be replaced by guessing positions; the window position then remains the fallback.

Dependencies: GTK3/PyGObject/Cairo, `ffmpeg`, `pactl`, PipeWire/Pulse user session, STT interpreter with faster-whisper, local model. Manual preparation on a new machine is described in [README.md](../README.md). Installer and app download no packages or models.
