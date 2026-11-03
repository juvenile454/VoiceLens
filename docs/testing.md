# Testing

## Isolated (test doubles, default)

```sh
/usr/bin/python3 -m unittest discover -s tests -p 'test_*.py' -v
env -u WAYLAND_DISPLAY GDK_BACKEND=x11 xvfb-run -a /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py' -v
/usr/bin/python3 -m unittest discover -s tests -p test_overlay.py -v
env -u WAYLAND_DISPLAY GDK_BACKEND=x11 xvfb-run -a /usr/bin/python3 -m unittest discover -s tests -p test_ui.py -v
```

| File | Checks | Real I/O |
|---|---|---|
| `test_backend.py` | Worker/ffmpeg lifecycle, cancel, timeout | no (doubles) |
| `test_controller.py` | Event contract, text preservation, keep policies (reuse, idle release, model/policy change, preloading, cancel) | no (`FakeBackend`, `FakeModelSession`) |
| `test_resident.py` | IPC channel with descriptors, `worker.serve` loop, `ModelSession` (reuse, reaping, cancel/timeout while loading and transcribing, worker crash) | real child processes as protocol doubles, no model |
| `test_lifecycle.py` | Recorder must not outlive its parent; memfd not inheritable | no |
| `test_settings.py` | Catalog, offline paths | no |
| `test_setup.py` | Setup diagnostics, SVG loader and broken assets, missing components, installer without a desktop, cache environment | real GTK asset loader; file/API doubles, no recording |
| `test_hotkey.py` | Hold/chord state machine, terminal role, paste options, old helpers/timeouts | no (AT-SPI/D-Bus doubles) |
| `test_shell_ext.py` | Copying files under `XDG_DATA_HOME`; shared app/launcher/D-Bus identity | no (temp dir; does not enable the session extension) |
| `test_ui.py` | GTK buttons/signals, start without icon/CSS, setup hints with multiple errors, append/auto-copy, clear, Escape, Ctrl+Shift+C, settings switches, menu dialogs, model in memory (settings, preloading at start, reuse, countdown, release, cancel while loading) | xvfb, no microphone |
| `test_overlay.py` | GJS/Cairo, native/IBus cursor geometry, label fade, terminal paste, animation/cancel, signal/timer cleanup | real Cairo; shell, IBus, keyboard, clock and D-Bus are doubles |

File headers mark doubles explicitly. `discover` only sees `test_*.py`.

## Visual preview (synthetic)

```sh
env -u WAYLAND_DISPLAY GDK_BACKEND=x11 xvfb-run -a /usr/bin/python3 tests/preview_ui.py --output verification/ui-en --language en
gjs -m tests/preview_overlay.js verification/overlay-en en
ffmpeg -v error -y -framerate 20 -i verification/overlay-en/%03d.png -filter_complex "[0:v]split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4" -loop 0 verification/overlay-en.gif
```

Renders GTK views in the selected language (`--language en|de`, default `de`) (idle, recording, transcription, result, footer with a loaded model, both settings pages, setup help, keyboard shortcuts) as well as a scene with the original overlay renderer and synthetic levels. Model availability is a double here so that the ready state is visible. Starts no recording and installs no extension. This does not replace a live test of the GNOME overlay in a foreign application.

Both scripts take `de` (the default) or `en`; `preview_ui.py` writes `<view>-<lang>.png`. The README images in `assets/screenshots/` and `assets/demo/` were produced this way.

## Setup diagnostics (read-only)

```sh
/usr/bin/python3 install.py --check --language de
./run.sh --check
```

Reads real device/model lists, loads the bundled icon and stylesheet for checking, and checks the existing interpreter in a reaped child process. No recording, no weights loaded, no launcher installation. This is not a real transcription test.

## Opt-in, real (not discover)

Only with explicit flags. They use the microphone when `--microphone` is set. No audio output to speakers.

```sh
/usr/bin/python3 tests/integration_local.py --speech SPEECH.wav --silence SILENCE.wav --output OUT.json
/usr/bin/python3 tests/integration_local.py --speech SPEECH.wav --silence SILENCE.wav --microphone --output OUT.json
# extra flag required:
/usr/bin/python3 tests/integration_ui.py --microphone --output verification/integration
```

Store measurement dumps only in an explicitly chosen local output folder, such as the ignored `verification/`. Do not version them or present them as a general hardware guarantee.

## Claims

- Do not present isolated tests as real speech recognition, microphone or RAM checks.
- Claim "worker unloaded" only if the worker PID is gone after the return (see `integration_local.measured_transcription`).
- GUI tests without `xvfb-run`/`GDK_BACKEND=x11` skip GTK (`test_ui.py`).
- No new tests that touch production services, network, credentials or unbounded recordings.
