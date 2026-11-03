# Contributing to VoiceLens

Thank you for helping. VoiceLens is an early release; small, focused changes with tests are easiest to review.

## Ground rules

- Privacy first: never include recordings, transcripts or personal paths in issues, pull requests, tests or fixtures.
- Keep the offline invariants described in [docs/invariants.md](docs/invariants.md).
- Tests found by `unittest discover` must not use the network, real credentials or a real microphone; real-device checks stay opt-in (see [docs/testing.md](docs/testing.md)).

## Development setup

On Ubuntu 24.04, install the system packages (this needs network access and administrator rights):

```sh
sudo apt install python3-gi python3-gi-cairo python3-cairo gir1.2-gtk-3.0 \
  librsvg2-common python3-venv ffmpeg pulseaudio-utils xdg-user-dirs desktop-file-utils \
  xvfb gjs
```

## Running tests

```sh
/usr/bin/python3 -m unittest discover -s tests -p 'test_*.py' -v
env -u WAYLAND_DISPLAY GDK_BACKEND=x11 xvfb-run -a /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py' -v
```

See [docs/testing.md](docs/testing.md) for what each test file covers.

## Previews

Synthetic screenshots and the overlay preview are rendered with test doubles; they start no recording.

```sh
env -u WAYLAND_DISPLAY GDK_BACKEND=x11 xvfb-run -a /usr/bin/python3 tests/preview_ui.py --output verification/ui-en --language en
gjs -m tests/preview_overlay.js verification/overlay-en en
```

## Translations

Every new UI string must exist in both `en` and `de` in `voicelens/i18n.py`.

## Pull requests

- Fill in the pull request template.
- Say which checks used test doubles and which used a real device or model.
- Update the documentation when behaviour changes.
