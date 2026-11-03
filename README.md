<p align="center">
  <img src="assets/voicelens.svg" width="112" alt="VoiceLens icon">
</p>

<h1 align="center">VoiceLens</h1>

<p align="center">
  <strong>Hold Control. Speak. Release. Your words appear at the caret.</strong><br>
  Offline dictation for Linux desktops with local Whisper. No cloud, no account, no telemetry.
</p>

<p align="center">
  <a href="https://github.com/juvenile454/VoiceLens/actions/workflows/tests.yml"><img src="https://github.com/juvenile454/VoiceLens/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <a href="https://github.com/juvenile454/VoiceLens/releases"><img src="https://img.shields.io/github/v/release/juvenile454/VoiceLens?include_prereleases&label=release" alt="Latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-86e6d0" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/Ubuntu-24.04-E95420?logo=ubuntu&logoColor=white" alt="Ubuntu 24.04">
  <img src="https://img.shields.io/badge/GNOME-46-4A86CF?logo=gnome&logoColor=white" alt="GNOME 46">
  <img src="https://img.shields.io/badge/runs-offline-0e151b" alt="Runs offline">
</p>

> [!NOTE]
> **Early release:** the initial target is Ubuntu 24.04 / GNOME 46 on x86_64. Other distributions, architectures and GNOME versions need validation; this is not a universal Linux installer. Windows and macOS are not supported. See the [release notes](docs/releases/v0.2.0.md) and [validation](docs/release.md).

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#features">Features</a> ·
  <a href="#install">Install</a> ·
  <a href="#usage">Usage</a> ·
  <a href="#privacy">Privacy</a> ·
  <a href="#documentation">Docs</a> ·
  <a href="docs/usage-de.md">Deutsch</a>
</p>

<p align="center">
  <img src="assets/demo/dictation-en.gif" width="640" alt="Animated preview: holding Control shows the VoiceLens lens at the caret in a notes field, releasing it transcribes locally and inserts the sentence at the caret">
  <br>
  <em>Synthetic preview rendered with the production overlay code. No recording.</em>
</p>

## Features

A native GTK 3 dictation app for Linux desktops, with local faster-whisper transcription.
No browser, web server, cloud transcription, telemetry, account or subscription.

| **Private by design** | **Dictate anywhere** | **Local Whisper models** |
|---|---|---|
| Audio lives only in an anonymous memory file. No cloud, no account, no telemetry, no transcript history. | Hold Control alone in any GNOME app. A small lens follows the caret and inserts the text when you release. Shortcuts like Ctrl+C keep working. | faster-whisper with Tiny up to Large v3 from your own disk. English and German for speech and interface. |

<details>
<summary>All features</summary>

- Detects microphone inputs during installation and startup, and refreshes them automatically while idle. Speaker-monitor sources and explicitly disconnected ports are excluded.
- Uses the current system default microphone for each recording, or a microphone you select. Muted devices are marked; VoiceLens never unmutes them for you.
- Finds complete local CTranslate2 Whisper models. On first use, prefers Small, then an available smaller model, then larger models. Your saved choice is preserved.
- Checks the local transcription runtime before enabling recording. Missing components have setup guidance in English and German.
- Supports English and German transcription and interface text.
- Loads Whisper only in a separate worker process. By default the worker exits and is reaped before completion is shown; optionally it stays loaded for a chosen number of minutes or permanently, so the next take starts without the loading delay.
- Provides a GNOME Control-hold shortcut and animated caret overlay. Record / Stop and manual copying also work in the app.
- Shows a live microphone level and the remaining recording budget while recording, with colour-coded state in the window.
- Optionally appends each result below the existing transcript, or copies it to the clipboard automatically. Both are off by default.
- Offers a transcript word count, a clear button, copy feedback, Escape to cancel and Ctrl+Shift+C to copy. The app menu lists the shortcuts and opens setup help.

</details>

## Screenshots

<table>
  <tr>
    <td width="50%"><img src="assets/screenshots/main.png" width="100%" alt="VoiceLens main window, ready to record with the automatic microphone selected"><br><sub>Main window, ready to record</sub></td>
    <td width="50%"><img src="assets/screenshots/recording.png" width="100%" alt="VoiceLens while recording, with the live microphone level, a Stop button and the remaining recording time"><br><sub>Recording with live level and time budget</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="assets/screenshots/result.png" width="100%" alt="VoiceLens after transcription, with an editable transcript and its word count"><br><sub>Finished transcript, ready to edit or copy</sub></td>
    <td width="50%"><img src="assets/screenshots/settings-model.png" width="100%" alt="VoiceLens model settings listing local Whisper models from Tiny to Large and the options for keeping the model in memory"><br><sub>Model choice and memory settings</sub></td>
  </tr>
</table>

*Synthetic previews with a simulated microphone.* Also available: [German interface](assets/screenshots/main-de.png).

## Supported platforms

| Platform | Status |
|---|---|
| Ubuntu 24.04 · GNOME 46 · Wayland · x86_64 | Tested: manual smoke test and automated suite |
| Other GNOME versions, distributions, architectures | Untested; reports welcome |
| Windows, macOS | Not supported |

## Quick start

Assumes the Ubuntu packages from [Install step 1](#1-prepare-dependencies).

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

## How it works

```mermaid
flowchart LR
  A["Hold Control<br/>or press Record"] --> B["ffmpeg records into<br/>an anonymous memory file"]
  B --> C["Separate worker process<br/>faster-whisper + local model"]
  C --> D["Text at the caret<br/>or in the window"]
  C -. "exits after each take by default" .-> E["Nothing stored on disk"]
```

The [architecture overview](docs/architecture.md) describes the modules, the recording and transcription path, and push-to-talk.

## Install

Keep the extracted or cloned project at its final location: launchers refer to this folder.

### 1. Prepare dependencies

VoiceLens's installer is **offline**: it checks existing components and installs user launchers. It does not install system packages or download models.

On Ubuntu 24.04, the following is an **optional manual preparation step requiring network access and administrator rights**. Run it yourself if those packages are missing:

```sh
sudo apt install python3-gi python3-gi-cairo python3-cairo gir1.2-gtk-3.0 \
  librsvg2-common python3-venv ffmpeg pulseaudio-utils xdg-user-dirs desktop-file-utils
```

Use a running PulseAudio-compatible PipeWire or PulseAudio desktop session. For the GNOME helper, `gnome-extensions` must be available. Automatic insertion may also use AT-SPI (`gir1.2-atspi-2.0`); manual copying remains available.

Prepare a **separate VoiceLens environment** from the project directory. These manual commands download Python packages:

```sh
/usr/bin/python3 -m venv .venv
.venv/bin/python3 -m pip install -r requirements-stt.txt
```

<details>
<summary>Installing on a computer without network access</summary>

For a computer without network access, copy compatible wheels and prepare the environment with `.venv/bin/python3 -m pip install --no-index --find-links /path/to/wheels -r requirements-stt.txt`. The wheel collection must contain all dependencies for that computer's Python version and architecture.

</details>

<details>
<summary>Reproducing the tested dependency versions</summary>

`requirements-stt.txt` pins faster-whisper. The optional [runtime constraints](requirements-stt-constraints.txt) record dependency versions from the Python 3.11 / Linux x86_64 speech runtime used for the functional smoke test. Add `-c requirements-stt-constraints.txt` when reproducing those versions in a compatible environment. These are version pins, not a wheel archive or a lockfile with package hashes; a fresh install using Ubuntu's Python 3.12 still needs validation.

</details>

<details>
<summary>Where VoiceLens looks for the transcription runtime</summary>

The GTK interface always runs with `/usr/bin/python3`. The transcription runtime is discovered in the project `.venv`, then `~/.local/share/voicelens/venv`, then system Python. Prefer a dedicated VoiceLens environment; the app does not search other applications' environments. An existing interpreter can be selected with an absolute `VOICELENS_STT_PYTHON` path. See [runtime search order](docs/ops.md).

</details>

### 2. Provide one local model

Existing Hugging Face caches are detected automatically, including `HF_HUB_CACHE`, `HUGGINGFACE_HUB_CACHE`, `HF_HOME` and `XDG_CACHE_HOME` locations.

Alternatively, copy a complete model folder to:

```text
~/.local/share/voicelens/models/small/
    config.json
    model.bin
    tokenizer.json
    vocabulary.txt   (or vocabulary.json)
```

`XDG_DATA_HOME` is respected. Use the corresponding model ID as the directory name for other sizes. Model weights alone are insufficient; broken symlinks and missing tokenizer files are reported.

[Official model links and offline setup instructions](docs/models.md). Models are not bundled in this repository and VoiceLens never downloads them.

### 3. Check and install

```sh
/usr/bin/python3 install.py --check       # read-only report; no microphone capture
/usr/bin/python3 install.py              # check, then install user launchers
./run.sh
```

For German output, add `--language de`. For machine-readable output, add `--json` to the installer or run `./run.sh --check`.

The check reports audio tools, GTK/Cairo including SVG support and the bundled icon/stylesheet, the transcription runtime, connected microphones, and local models. It imports the transcription libraries in a guarded child process without loading model weights. Passing the check does not certify model contents or transcription accuracy. If the icon or stylesheet cannot be loaded, the app still opens with the desktop's default appearance; the setup check reports the problem.

Installation creates an application-menu entry and, when configured, a desktop shortcut. Missing optional desktop utilities produce warnings. An incomplete speech setup can still install launchers; `--check` exits with status 1 until required components are available. No autostart or system service is created.

## Usage

1. Open **VoiceLens** and choose English or German in settings (the app menu in the header also opens settings, setup help and the shortcut list).
2. Leave microphone selection on **Automatic**, or select a specific input. The level bar under the selector moves while recording.
3. Press **Record**, speak, then press **Stop**. Edit or copy the result; **Escape** cancels a running take and keeps the previous text.
4. For dictation into another app, keep VoiceLens open, focus a text field, hold **Control alone**, speak, and release it.
5. In **Settings → General**, optionally append each result below the existing transcript or copy it to the clipboard automatically.
6. In **Settings → Model**, choose whether the model is released after each take (default), kept for a number of minutes after the last use, or kept loaded (then it is loaded at start-up). The footer shows what is in memory; the app menu can load or release the model at any time. A kept model uses its RAM for as long as it stays loaded.

The global shortcut and overlay require the VoiceLens GNOME extension. Enable it and log out and back in after first installation or a helper update if needed. Supported Shell versions are listed in [the extension metadata](gnome-shell-extension/metadata.json); compatibility declarations are not equivalent to tests on every version.

New microphones appear automatically while idle. **Refresh** also rechecks the transcription runtime after setup changes. No microphone is opened during discovery. Recording starts only after Record or the Control-hold gesture. Shortcuts such as Ctrl+C remain usable.

In terminals the helper pastes with Ctrl+Shift+V and never sends Enter. If insertion is unavailable, paste manually. While transcribing, **Cancel** keeps your previous text. Closing the app also stops its operation. Recordings have a bounded duration; the implementation limit is in `voicelens/backend.py`.

### Keyboard shortcuts

| Shortcut | Action |
|---|---|
| Hold **Control** alone | Dictate into the focused window |
| **Escape** | Cancel the current recording or transcription |
| **Ctrl+Shift+C** | Copy the transcript |

## Privacy

Audio stays in an anonymous Linux memory file and is closed on completion, cancellation or failure. A kept model receives each recording only as a passed memory descriptor and is closed with the app. VoiceLens keeps no audio or transcript history on disk. Only preferences are saved. Successful transcription replaces the previous result; errors, silence and cancellation preserve it.

Copying intentionally sends text to the system clipboard; a separate clipboard manager may retain its own history. Model files remain on disk, and Linux may retain their pages in reclaimable file cache after the worker exits. Transcription may make mistakes: check significant names, numbers and instructions.

## Documentation

All pages are listed in the [documentation index](docs/README.md). Start with:

- [Models and licenses](docs/models.md): official model sources, offline setup and redistribution.
- [Architecture](docs/architecture.md): modules, recording and transcription, push-to-talk.
- [Testing](docs/testing.md): isolated tests with doubles, the synthetic visual preview and opt-in real checks.

### Development and verification

```sh
/usr/bin/python3 -m unittest discover -s tests -p 'test_*.py' -v
env -u WAYLAND_DISPLAY GDK_BACKEND=x11 xvfb-run -a /usr/bin/python3 -m unittest discover -s tests -p test_ui.py -v
```

Tests use explicit doubles and temporary files; they do not validate real speech recognition or microphone quality. See [testing](docs/testing.md), [architecture](docs/architecture.md), [invariants](docs/invariants.md), and [operations](docs/ops.md). Real audio integration checks are separately opt-in. For an issue, use the repository's [bug-report form](https://github.com/juvenile454/VoiceLens/issues/new?template=bug_report.yml); avoid sharing private transcripts or unredacted diagnostic paths.

## License

VoiceLens is licensed under the [MIT License](LICENSE). Whisper, faster-whisper and model licenses are separate; see [model sources and third-party licenses](docs/models.md).
