# Tiny 0.17.0

Stand 01.11.2026: Tiny 0.17.0 ergänzt ein Debian-Paket mit privater Node.js-22-Laufzeit. Diese Laufzeit bleibt unter `/usr/share/tiny/runtime/` und ändert nicht die systemweite Node.js-Version. Installierte Anwendungen speichern ihre Einstellungen im benutzerspezifischen XDG-Verzeichnis. Der Gesamt-Reset umfasst auch die Studio-Aufnahmeoptionen. Backend-, GTK- und Hardwareabnahme sind getrennt zu betrachten; die Kamerawirkung wurde nicht für jede Funktion erneut geprüft.

## Start und Anzeige

Im vollständigen Quellprojekt `./start.sh` oder den dortigen Projektstarter **Tiny** öffnen. Im portablen Linux-Laufzeitarchiv im Terminal `./tiny.py` beziehungsweise `python3 ./tiny.py` ausführen. Das Laufzeitarchiv enthält keinen Projektstarter und kein `start.sh`. Die Anwendung zeigt zwei getrennte, unabhängig verschiebbare Fenster: **Einstellungen** für Gerätewahl und Bildformat sowie **Livebild** mit reiner Bildausgabe ohne Status- und Bedienungstext. Das Livebild lässt sich über **Ansicht → Liveausgabe anzeigen** wieder öffnen und mit **F11** auf Vollbild schalten. Das Schließen eines der beiden Fenster blendet es nur aus; die Kamera und das andere Fenster laufen weiter. **Datei → Beenden** schließt die Anwendung vollständig und führt die Kameras in den Ruhemodus zurück.

Die Seitenleiste enthält Bildformat, Video, Ton, Kameraprofile und Virtuelle Kamera. Auf der Seite Video liegen die von der Kamera gemeldeten Auflösungen, Bildraten und Pixelformate sowie Aufnahmeformat, Qualität, Bitrate, Drehung, Filter und Aufnahmedauer. Dort startest und beendest du Aufnahmen. Bildformat enthält Bilddateiformat, Fotoserie und Speicherordner; Ton bietet separate Audioaufnahmen und Audioeinstellungen. Die Seiten Bewegung & Zoom, Tracking, Bild & Fokus, Positionen und Kameraeinstellungen sind wieder in der Seitenleiste verfügbar. Die Diagnose-Seite bleibt ausgeblendet. Alle von der Kamera gemeldeten, unterstützten Pixelformate bleiben auswählbar; bei Bedarf passt Tiny Auflösung und Bildrate an. Unter Bildformat gibt es die Schaltfläche „Bild speichern“. Sie speichert das aktuelle Livebild in einem lokal unterstützten Format: PNG, JPEG, BMP, ICO/CUR, TIFF oder WebP. Der voreingestellte Bilderordner ist `~/Bilder` und lässt sich über den Ordnerdialog ändern. Im Bereich Kameraprofile stehen Speichern, Laden und Löschen direkt bereit. Status und begrenzte Protokolle bleiben erhalten.

Die Vorschau startet nach der Suche und nach einem Kamerawechsel automatisch. Tiny wird vorher mit Statusbestätigung aufgeweckt. Eine Aufnahme sperrt Kamerawechsel, Bildformat und Filter. Die Bildformatwahl zeigt lokal schreibbare GdkPixbuf-Formate. Die Schaltfläche Bild speichern ist nur aktiv, wenn ein Livebild verfügbar ist. Die Seite Ton enthält zusätzlich eine separate Mikrofonaufnahme mit wählbarem Zielordner und lokal verfügbaren WAV-, OGG/Opus-, FLAC- oder MP3-Encodern. Ton kann außerdem in Videoaufnahmen zugeschaltet werden; die Auswahl bietet abhängig von installierten GStreamer-Encodern Opus (WebM/MKV), AAC (MP4) und PCM (AVI).

## Bildformate und weitere Kameras

Die Erkennung fragt alle V4L2-Knoten nach ihrer Aufnahmefähigkeit ab und schließt reine Metadatenknoten aus. Weitere USB-Webcams benötigen keine neue Modellliste. Unter **Bildformat** stehen die von dieser Kamera angebotenen, vom Programm lesbaren Kombinationen aus Auflösung, Bildrate und Pixelformat. Diskrete sowie ausgewählte zulässige Bereiche werden berücksichtigt. MJPEG/JPEG, übliche unkomprimierte Formate und H.264 mit vorhandenen GStreamer-Decodern sind vorgesehen. Treiber- und Codecunterstützung bleiben Voraussetzung.

Die Bildanzeige unterscheidet vereinbarte und tatsächlich empfangene Bildrate. Eine angeforderte Rate belegt keine entsprechende tatsächliche Lieferung. Es läuft ein Kamerastream; bei Wechsel wird der vorherige beendet.

## Logitech und Standardregler

Für die angeschlossene C922 wurden 17 Regler gelesen: Helligkeit, Kontrast, Sättigung, Weißabgleich, Verstärkung, Flimmerkorrektur, Farbtemperatur, Schärfe, Gegenlicht, Belichtungsautomatik/-zeit, variable Bildrate, horizontaler/vertikaler Bildausschnitt, Fokus und Zoom. Die Verfügbarkeit wird jedes Mal aus dem Treiber ermittelt. Ihr Bildausschnitt ist kein motorisierter Gimbal; Tiny-Tracking wird nicht angeboten.

Die Oberfläche zeigt keine Standardregler oder Tiny-Bewegungssteuerungen mehr an. Die virtuelle Bildausgabe und die Auswahl des Bildformats bleiben davon getrennt.

## Video, Filter und Ton

Die Seite **Video** enthält den von der Kamera gemeldeten Videomodus mit Auflösung, Bildrate und Pixelformat, dazu Video-Container und Codecs, Qualität, Bitrate, Aufnahmedauer, Bilddrehung und Filter. Dort lassen sich Videoaufnahmen starten und beenden; das Menü **Aufnahme** bleibt als zusätzlicher Zugriff verfügbar.

Spiegelung, Drehung, Graustufen und Negativ gelten für Livebild, PNG und Video. Das Fadenkreuz wird ausschließlich über das Livebild gezeichnet. Koordinatenbasierte Tiny-Steuerung rechnet Drehung und Spiegelung zurück; ihre Bildmaße müssen zur angezeigten Ausrichtung passen. Wasserzeichen und Fadenkreuz gelangen nicht in gespeicherte Kamerabilder.

**Aufnahme → Ton aufnehmen** verwendet ausschließlich ein zum physischen USB-Gerät der ausgewählten Kamera gehörendes Mikrofon. Eine separate Mikrofonwahl ist entfernt. Fehlendes oder stummgeschaltetes Kameramikrofon erzeugt einen Fehler; es gibt keinen stillen Wechsel auf ein fremdes Mikrofon.

**Extras → Fotoserie starten** fragt einen Zielordner ab und speichert die angegebene Anzahl Bilder im ausgewählten Bildformat und gewählten Abstand. Das erste Foto wird sofort erstellt. Livebild-Stopp, Fehler oder Programmende beenden auch die Serie. Vorhandene Dateien werden nicht überschrieben.

## Kameraprofile und Grundwerte

Unter **Kameraprofile** einen Namen eingeben und **Speichern** wählen. Ein Profil in der Liste markieren und **Laden** oder **Löschen** wählen. Unter **Bildformat** wählt ein lokal schreibbares Bilddateiformat und speichert mit **Bild speichern** das aktuelle Livebild. Ersetzen und Löschen erfordern eine Bestätigung. Profile enthalten Bildformat, Aufnahmevorgaben, Spiegelung, Bildfilter und gültige beschreibbare Kamera-Bildregler. Tiny-Schwenken/-Neigen und virtuelle Ausgabe werden nicht gespeichert. Profile sind je Kamera getrennt. Ein Ladefehler stoppt das bestehende Livebild nicht. Die Datei ist projektlokales, versioniertes JSON ohne ausführbare Konfiguration.

Das Zurücksetzen von Kamera-Reglern ist aus der Oberfläche entfernt.

## Virtuelle Kamera

Das bearbeitete Livebild lässt sich über **Extras → Virtuelle Kamera** an ein eingerichtetes akvcam-/v4l2loopback-Ausgabegerät weitergeben. Die Seitenleiste bietet Ziel und Format an. Eine Beispielkonfiguration kann gespeichert werden; das Programm installiert oder lädt keine Treiber. Einzelheiten in `AKVCAM.md`.

## Programmende und Tiny-Ruhemodus

Beim Schließen werden Fotoserien beendet, laufende Aufnahmen fertiggeschrieben und Streams geschlossen. Anschließend werden vom Programm verwendete Tiny-Kameras anhand ihrer gemerkten Seriennummer in den Ruhemodus versetzt, auch wenn inzwischen eine Logitech ausgewählt ist. Der Zustand wird zurückgelesen. Eine bereits entfernte Tiny wird übersprungen. Bei fehlender Bestätigung wird ein Fehler mit der Entscheidung zum trotzdem Beenden angezeigt. Auch Schließen während des Aufweckens und während der Container-Fertigstellung wird behandelt.

## Ablage und Voraussetzungen

Python mit GTK 4, GStreamer und den jeweils angebotenen Plugins sowie der lokale native Helfer werden verwendet. FFmpeg dient der technischen Medienprüfung. Kamera- und Audiorechte sowie die USB-Durchreichung in die Labor-VM müssen vorhanden sein. Das Debian-Paket enthält seine eigene Node.js-22-Laufzeit. Für den Quellcode und das portable Laufzeitarchiv wird Node.js 20 oder neuer benötigt; das Laufzeitarchiv enthält die Node-Produktionsabhängigkeiten und kennzeichnet das Backend ausdrücklich als ES-Modul.

Einstellungen, Kameraprofile und begrenzte Logs liegen unter `.config/`, der lokale MCP-Endpunkt unter `.config/ipc/`. Keine Suche nach Tail-2-Netzwerkgeräten. Das bereitgestellte Kamerabild bleibt Programmsymbol. Es wurde kein GUVCView-Code übernommen oder GUVCView installiert.

## Sicherheits- und Implementierungshinweise

Die Anwendung verwendet native GTK-Oberflächen, verständliche Statusanzeigen, ausschließlich lesende Voraussetzungendiagnose, keinen Reparaturautomatismus, keine Löschung von APT-Sperrdateien, kein `eval` für Konfiguration und keine Shell-Auswertung von Kameraparametern. Einstellungen werden lokal, atomar und validiert gespeichert. Es werden keine Polkit-Regeln, globalen APT-Schlüssel oder Dienste eingerichtet. Die lokale GUI-Bibliothek ist enthalten; unabhängige Upstream-Lizenzhinweise bleiben in den Quellordnern erhalten.

Die Auswahl der vorhandenen Kamerabibliothek wurde am 29.10.2026 mit der [Upstream-Dokumentation](https://github.com/lxman/obsbot-mcp) abgeglichen. Ihre vorhandene Geräteverwaltung, Protokollkodierung und Linux-Begrenzungen bleiben Grundlage. Keine neue Fremdbibliothek für die Kamerasteuerung erforderlich.

## Prüfung und Grenzen

Die folgenden Entwicklungs- und Prüfkommandos gelten nur im vollständigen Quellprojekt. Dort stellt `npm ci` die in `package-lock.json` festgelegten Entwicklungsabhängigkeiten wieder her; danach prüft `npm test` den Backend-Code. `/usr/bin/python3 -B -m unittest discover -s test/desktop -v` öffnet GTK-Fenster und prüft mit synthetischen Medien unter anderem Aufnahmecontainer, Filter, Profile, Timer und Beenden. Testdaten entstehen unter `work/`. Das portable Laufzeitarchiv enthält diese Testdateien, `package-lock.json` und Entwicklungsabhängigkeiten nicht. Diese Tests benötigen keine Kamera und beweisen allein keine reale Kamerafunktion.

Tiny 2 und C922 wurden zusätzlich real mit Livebild, Kameramikrofon, PNG, Profil-Rückladen, Grundwerten und wiederhergestellten Ausgangswerten geprüft. Das Schließen während einer C922-Aufnahme und der anschließende Tiny-Ruhemodus wurden bestätigt. Weitere Modelle wurden über einen unabhängigen V4L2-Testfall geprüft, nicht mit weiterer physischer Hardware. Weitere Prüfdetails stehen ausschließlich in `PRUEFUNG.md` und `docs/pruefprotokolle/` des vollständigen Quellprojekts; diese Dateien sind nicht Bestandteil des Laufzeitarchivs.

Die eingebaute Tiny-Sprachsteuerung unterstützt weiterhin keine deutschen Kamerabefehle. Eine eigene deutsche Spracherkennung ist nicht implementiert.

Tracking-Eingaben (Aktivierung, Motiv, Geschwindigkeit und Gesichtsfokus) werden lokal gespeichert und bei Funktionswechsel und Neustart wiederhergestellt. Zum Senden an die Kamera weiterhin „Ausführen“ wählen. Links öffnet „Bewegung & Zoom“ die entsprechenden Kamerafunktionen.

## Sprache/Gestik

Der linke Eintrag „Sprache/Gestik“ enthält die beiden Reiter „Sprache“ und „Gestik“. Alle Sprachbefehle und Gesten stehen jeweils in eigenen sichtbaren Zeilen mit unabhängig gespeicherten Schaltern. Im Reiter „Sprache“ gibt es zusätzlich die Erkennungssprache (Englisch/Chinesisch). Gestenschalter betreffen Zielauswahl, Zoom, dynamischen Zoom und die Spiegelung der Zoomrichtung. Auswahlwerte werden lokal zusammen mit den Tracking-Eingaben in `tracking.json` gespeichert. Mit „Ausführen“ wird jeweils nur die markierte Zeile des aktiven Reiters an die gewählte Tiny 2 übertragen. Das Ändern eines Schalters markiert automatisch seine Zeile.

Die Befehlsübertragung wurde mit einem simulierten Transport geprüft; die Wirkung der Sprach- und Gestenschalter an echter Hardware ist noch nicht bestätigt. Die Rückgabe enthält daher `verified: false`. Ein erfolgreiches Schreiben ist kein Nachweis einer Firmwareänderung.

Technische Referenz: [OBSBOT SDK-Header im Projekt malko/obsbot-js-sdk](https://github.com/malko/obsbot-js-sdk/blob/main/libdev_v2.1.0_7/include/dev/dev.hpp), SDK v2.1.0_7. Sprachbefehle verwenden `cameraSetAudioCtrlStateU`: XU-Selektor 6, 60 Bytes, Präfix `15 02`, Befehlsnummer und Zustandswert. Gestenschalter verwenden die vorhandene Opcode-Tabelle; boolesche Nutzlast ein Byte. Keine SDK-Bibliothek wird zur Laufzeit mitgeliefert oder benötigt.

Die Gestenliste zeigt eigene SVG-Handzeichen: offene Handfläche (Tracking), L-Zeichen (Zoom), zwei L-Zeichen mit Abstandspfeil (dynamischer Zoom). Die Richtungsumkehr zeigt dasselbe Zeichen mit Spiegelachse. Kurze Anleitungen stehen unmittelbar bei jeder Funktion. Referenz für die drei Handzeichen: [OBSBOT Tiny 2 Benutzerhandbuch, Seiten 6–7](https://resource-cdn.obsbothk.com/download/obsbot-tiny-2/manual/OBSBOT%20Tiny%202%20User%20Manual_EN.pdf). Die Illustrationen wurden eigenständig als Vektorgrafiken erstellt.

## Aufnahme- und Reglerschutz ab 0.16.4

Fehlgeschlagene Tonabschlüsse erhalten die Datei und zeigen deren Speicherort. Unplausible Treiberregler sowie die Tiny-2-Treiberbelichtung sind nur lesbar. Für Belichtung die vorhandenen Funktionen unter „Bild & Fokus“ verwenden.

Serienbilder übernehmen die ausgewählte Bilddateiart. Die separat gespeicherte JPEG-Qualität wirkt auf Einzel- und Serienbilder und ist bei anderen Formaten deaktiviert. MP4/H.264 verwendet die Videobitrate; sein separater Qualitätsregler ist deaktiviert. Ohne verfügbaren Videoencoder sind Aufnahme und Profilspeicherung gesperrt.
