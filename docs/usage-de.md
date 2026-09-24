# VoiceLens – Kurzanleitung

Native GTK3-Diktier-App für Linux: **Steuerung halten → sprechen → loslassen → Text am Cursor**. Diese frühe Version richtet sich an Ubuntu 24.04 mit GNOME 46 auf x86_64. Andere Plattformen sind noch nicht geprüft.

## Einrichtung

Die vollständigen Vorbereitungsschritte stehen in [README.md](../README.md). Benötigt werden GTK3/Cairo im System-Python, ffmpeg, pactl, eine PulseAudio-kompatible Desktop-Sitzung und faster-whisper in einer eigenen VoiceLens-Umgebung.

```sh
/usr/bin/python3 install.py --check --language de
/usr/bin/python3 install.py --language de
./run.sh
```

Der Installer prüft angeschlossene Mikrofone, Abhängigkeiten und vollständige lokale Modelle. Er nimmt nichts auf und lädt keine Modelle. Vorhandene Mikrofone stehen automatisch in der Auswahl. Ein fehlendes Mikrofon verhindert die Launcher-Installation nicht; nach dem Anschließen erkennt die App es im Leerlauf automatisch.

Beim ersten Start wird ein vorhandenes Modell vorausgewählt. Bereits gespeicherte Entscheidungen bleiben erhalten. Modellquellen, Ordnerstruktur und Lizenzen: [Modelle](models.md). In den Einstellungen gibt es außerdem eine Einrichtungshilfe. Nach einer Änderung der Transkriptionsumgebung die Einstellungen schließen und ↻ drücken.

## Bedienung

- VoiceLens im Anwendungsmenü oder mit `./run.sh` öffnen. Der Projektordner muss an seinem Installationspfad bleiben.
- Die Oberfläche startet auf Englisch. Über den Einstellungsbutton oder das Menü in der Kopfzeile zu Deutsch wechseln; dort auch Modell und Push-to-Talk auswählen.
- **Aufnehmen** drücken, sprechen, **Stoppen** drücken. Text anschließend bearbeiten oder kopieren. Die Pegelanzeige unter der Mikrofonauswahl zeigt, dass Ton ankommt; der Zähler zeigt die verbleibende Aufnahmezeit. **Escape** bricht eine laufende Aufnahme oder Transkription ab und behält den bisherigen Text.
- Das Transkript zeigt Wort- und Zeichenzahl. **Kopieren** (auch Strg+Umschalt+C) bestätigt kurz im Button; das Papierkorb-Symbol leert das Transkript.
- Unter **Einstellungen → Allgemein** lässt sich einstellen, dass ein neues Ergebnis unter den vorhandenen Text angehängt wird oder automatisch in die Zwischenablage wandert. Beides ist standardmäßig aus. Die Seite **Modell** zeigt installierte Modelle und öffnet den lokalen Modellordner.
- Ebenfalls unter **Modell**: das Modell nach jeder Aufnahme freigeben (Standard), eine frei wählbare Zahl Minuten nach der letzten Nutzung behalten oder dauerhaft behalten (dann wird es schon beim Start geladen). Die Fußzeile zeigt, was im Speicher liegt und wann es freigegeben wird; das Menü in der Kopfzeile lädt oder gibt das Modell jederzeit frei. Ein gehaltenes Modell belegt seinen Arbeitsspeicher, solange es geladen ist.
- Für ein anderes Textfeld VoiceLens geöffnet lassen, das Ziel fokussieren, **Steuerung allein halten**, sprechen und loslassen. Die VoiceLens-GNOME-Erweiterung muss dafür aktiviert sein. Nach der ersten Installation gegebenenfalls einmal ab- und anmelden.
- Die Linse folgt den verfügbaren Cursorinformationen. Ohne diese schwebt sie am aktiven Fenster. Beim Loslassen wird transkribiert; nach dem Beenden des Workers und der Rückkehranimation erscheint der Text.
- Im Terminal verwendet der Helper Strg+Umschalt+V ohne zusätzliche Enter-Taste. Falls das Einfügen nicht klappt, manuell einfügen.
- **Automatisch** verwendet für jede Aufnahme das aktuelle Standardmikrofon. Alternativ ein bestimmtes Gerät auswählen. Stumme Geräte werden markiert; VoiceLens hebt die Stummschaltung nicht selbst auf.
- Abbruch, Fehler und Stille behalten den vorhandenen Text. Eine erfolgreiche Transkription ersetzt ihn. Die Aufnahmedauer ist begrenzt; der Grenzwert steht in `backend.MAX_RECORD_SECONDS`.

Audio liegt ausschließlich in einem anonymen Speicher-Dateideskriptor. VoiceLens speichert keine Audio- oder Text-Historie. Die bewusst verwendete Systemzwischenablage kann durch andere Programme protokolliert werden. Namen, Zahlen und wichtige Aussagen nach der Erkennung prüfen.
