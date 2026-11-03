# Changelog

All notable changes to VoiceLens are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Restructured README with an animated demo GIF and screenshots. All images are synthetic previews rendered with test doubles; none contain a recording.
- GitHub Actions workflow that runs the test suite.
- English developer documentation and a documentation index at `docs/README.md`.
- Documentation guard test for relative links, anchors, release status and image size budgets.
- `--language` option for `tests/preview_ui.py` and an `en` option for `tests/preview_overlay.js`.
- Social preview image.
- Contributing guide, security policy, changelog, feature-request form and pull request checklist.

## [0.2.0] - 2026-09-24

### Added

- Colour-coded state indicators, a live microphone level bar and the recording budget next to the timer.
- Transcript word and character counts, a clear button and a copy button with confirmation.
- Settings split into General and Model pages, plus a header menu with Settings, Setup help and a shortcut list.
- Optional append mode and automatic clipboard copy (both off by default).
- Escape cancels the running recording or transcription and keeps the previous text; Ctrl+Shift+C copies the transcript.
- Open models folder action.
- Model in memory: release after each take (default), keep for a chosen number of minutes, or keep loaded.

### Changed

- Reworked stylesheet and visualizer background.
- Settings files from 0.1.0 load unchanged; new keys default to off / release.

## [0.1.0] - 2026-09-13

### Added

- Early source release for Ubuntu 24.04 / GNOME 46 on x86_64.
- Local faster-whisper transcription with English and German interface and recognition settings.
- Automatic microphone and complete local-model discovery, with setup diagnostics.
- GNOME Push-to-Talk, caret overlay and insertion into the focused application.
- Short-lived transcription workers, anonymous in-memory audio and no built-in transcript history.
- MIT-licensed source, installation instructions, offline model guidance and regression tests.

[Unreleased]: https://github.com/juvenile454/VoiceLens/compare/v0.2.0...HEAD
[0.2.0]: docs/releases/v0.2.0.md
[0.1.0]: docs/releases/v0.1.0.md
