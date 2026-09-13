# Release status and validation

VoiceLens 0.1.0 is prepared as an early source release for Ubuntu 24.04 / GNOME 46 on x86_64. Publication is a separate maintainer action; preparing a draft does not change repository visibility.

## Evidence

| Check | Result and scope |
|---|---|
| User installation | Launchers, fresh preferences, local Small-model discovery and microphone discovery passed on Ubuntu 24.04 / GNOME 46 / Wayland. Existing system dependencies and model cache were reused. |
| Manual functional smoke test | In-app dictation and Control-hold dictation were reported working after that installation. No recordings or transcripts are included in the repository. |
| Original automated suite | 115 tests passed locally and in an independent Debian 13 / Xvfb environment; 14 additional independent audit tests also passed. |
| Release cleanup | 116 repository tests passed under Xvfb with no failures or skips, including portable-runtime discovery and the cross-component desktop/D-Bus identity check. Release contents and metadata were reviewed separately. |
| Runtime versions | System GTK Python 3.12; speech runtime Python 3.11, faster-whisper 1.2.1, CPU/INT8. Dependency versions are recorded in `requirements-stt-constraints.txt`. |

The manual smoke test preceded the final identifier/runtime-discovery cleanup. It is evidence for the dictation workflow, not a fresh-account installation test of every release dependency. Automated tests use doubles for microphone and transcription operations; they do not establish real speech accuracy, RAM usage or compatibility with every audio device.

## Distribution

- MIT application license in [LICENSE](../LICENSE); model and dependency licenses remain separate.
- Source archive and SHA-256 checksums; no bundled models, Python environments, recordings or diagnostic logs.
- A clean release history with neutral project author metadata.
- Local agent instructions, skills, development history and machine-specific reports are excluded from Git and source archives.
- The application and installer remain offline. Manual dependency/model preparation is documented explicitly.

## Remaining platform validation

- A fresh Ubuntu account following the dependency installation instructions, including a new Python 3.12 speech environment.
- The final application identifiers with a newly installed GNOME helper and a fresh login.
- Additional USB, built-in and Bluetooth microphones, hotplug and audio-server failure cases on real hardware.
- Representative speech, silence and measured worker/process memory cleanup across local models.
- Other GNOME versions, distributions, architectures and graphics/session configurations.

Report only the combinations actually tested. The extension currently declares GNOME 46. Future model bundles need their own exact upstream revisions, applicable notices and checksums.

## Maintainer publication checks

Review the release branch, its complete reachable history, source archive, draft text and attached checksums. Confirm that the draft targets the reviewed commit. Keep local development files and personal commit identities out of future commits. Make repository visibility and release publication explicit, separate actions.
