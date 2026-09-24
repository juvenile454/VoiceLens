# Tests

## Isoliert (Testdoubles, Standard)

```sh
/usr/bin/python3 -m unittest discover -s tests -p 'test_*.py' -v
env -u WAYLAND_DISPLAY GDK_BACKEND=x11 xvfb-run -a /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py' -v
/usr/bin/python3 -m unittest discover -s tests -p test_overlay.py -v
env -u WAYLAND_DISPLAY GDK_BACKEND=x11 xvfb-run -a /usr/bin/python3 -m unittest discover -s tests -p test_ui.py -v
```

| Datei | Prüft | Echtes I/O |
|---|---|---|
| `test_backend.py` | Worker-/ffmpeg-Lifecycle, Cancel, Timeout | nein (Doubles) |
| `test_controller.py` | Eventvertrag, Text-Erhalt | nein (`FakeBackend`) |
| `test_lifecycle.py` | Recorder darf Parent nicht überleben; memfd nicht vererbbar | nein |
| `test_settings.py` | Katalog, Offline-Pfade | nein |
| `test_setup.py` | Einrichtungsdiagnose, SVG-Loader und defekte Assets, fehlende Komponenten, Installer ohne Schreibtisch, Cache-Umgebung | GTK-Asset-Lader echt; Datei-/API-Doubles, keine Aufnahme |
| `test_hotkey.py` | Halten/Akkord-State-Machine, Terminalrolle, Paste-Optionen, alte Helper/Timeouts | nein (AT-SPI/D-Bus-Doubles) |
| `test_shell_ext.py` | Dateien kopieren unter `XDG_DATA_HOME`; gemeinsame App-/Launcher-/D-Bus-Identität | nein (temp dir; aktiviert die Session-Erweiterung nicht) |
| `test_ui.py` | GTK-Buttons/Signale, Start ohne Icon/CSS, Einrichtungshinweise bei mehreren Fehlern, Anhängen/Auto-Kopieren, Leeren, Escape, Strg+Umschalt+C, Einstellungsschalter, Menüdialoge | xvfb, kein Mikrofon |
| `test_overlay.py` | GJS/Cairo, native/IBus-Cursor-Geometrie, Label-Fade, Terminal-Paste, Animation/Abbruch, Signal-/Timer-Cleanup | Cairo echt; Shell, IBus, Tastatur, Uhr und D-Bus sind Doubles |

Dateiköpfe markieren Doubles ausdrücklich. `discover` sieht nur `test_*.py`.

## Visuelle Vorschau (synthetisch)

```sh
env -u WAYLAND_DISPLAY GDK_BACKEND=x11 xvfb-run -a /usr/bin/python3 tests/preview_ui.py --output verification/ui
gjs -m tests/preview_overlay.js verification/ui/frames
ffmpeg -v error -y -framerate 20 -i verification/ui/frames/%03d.png -filter_complex "[0:v]split[a][b];[a]palettegen[p];[b][p]paletteuse" -loop 0 verification/ui/cursor-flow.gif
```

Rendert GTK-Ansichten in beiden Sprachen (Leerlauf, Aufnahme, Transkription, Ergebnis, beide Einstellungsseiten, Einrichtungshilfe, Tastenkürzel) sowie eine Szene mit dem Original-Overlay-Renderer und synthetischen Pegeln. Die Modellverfügbarkeit ist dabei ein Double, damit der Bereit-Zustand sichtbar ist. Startet keine Aufnahme und installiert keine Erweiterung. Das ersetzt keinen Live-Test des GNOME-Overlays in einer fremden Anwendung.

## Einrichtungsdiagnose (nur lesend)

```sh
/usr/bin/python3 install.py --check --language de
./run.sh --check
```

Liest echte Geräte-/Modelllisten, lädt das mitgelieferte Icon und Stylesheet zur Prüfung und prüft den vorhandenen Interpreter in einem abgeholten Kindprozess. Keine Aufnahme, keine Gewichte geladen, keine Launcher-Installation. Das ist kein echter Transkriptionstest.

## Opt-in, echt (nicht discover)

Nur mit expliziten Flags. Nehmen das Mikrofon, wenn `--microphone` gesetzt ist. Keine Audioausgabe an Lautsprecher.

```sh
/usr/bin/python3 tests/integration_local.py --speech SPEECH.wav --silence SILENCE.wav --output OUT.json
/usr/bin/python3 tests/integration_local.py --speech SPEECH.wav --silence SILENCE.wav --microphone --output OUT.json
# extra Flag Pflicht:
/usr/bin/python3 tests/integration_ui.py --microphone --output verification/integration
```

Messdumps nur in einem ausdrücklich gewählten lokalen Ausgabeordner ablegen, etwa dem ignorierten `verification/`. Nicht versionieren oder als allgemeine Hardwaregarantie darstellen.

## Aussagen

- Isolierte Tests nicht als echte Spracherkennung, Mikrofon- oder RAM-Prüfung ausgeben.
- „Worker entladen“ nur behaupten, wenn die Worker-PID nach Return weg ist (siehe `integration_local.measured_transcription`).
- GUI-Tests ohne `xvfb-run`/`GDK_BACKEND=x11` überspringen GTK (`test_ui.py`).
- Keine neuen Tests, die Produktionsdienste, Netz, Credentials oder unbegrenzte Aufnahmen anfassen.
