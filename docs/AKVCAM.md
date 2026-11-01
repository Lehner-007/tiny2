# akvcam-Prüfung und Programmanbindung – 29.10.2026

## Ergebnis

akvcam ist ein virtueller V4L2-Kameratreiber, keine Oberfläche zur Steuerung einer USB-Kamera. Die vorhandenen Bildregler, Formate und Filter von Tiny bleiben für die reale Kamera zuständig. Neu kann das bereits bearbeitete Bild an ein eingerichtetes virtuelles Ausgabegerät weitergegeben werden. Die Gegenstelle erscheint anderen Anwendungen als Kamera.

Geprüfter Upstream-Stand: `webcamoid/akvcam`, Commit `d1243f277d0a10efd9fec04574ad6fcb4265f7b0`, Version **2.0.0**, Commitdatum 18.10.2026. Der Treiber wurde ausschließlich im Projekt-Arbeitsbereich erfolgreich gegen die vorhandenen Header für **7.0.0-42-generic** gebaut. `modinfo` bestätigt Version, GPL-Lizenz und passende Kernel-Versionskennung. Dies beweist die Übersetzbarkeit, nicht das erfolgreiche Laden oder die Laufzeitfunktion.

## Eingebaut

- Seitenleiste **Virtuelle Kamera** mit tatsächlich erkannten Ausgabegeräten und deren Rohbildformaten.
- **Extras → Virtuelle Kamera → Bild weitergeben / Weitergabe beenden / Ausgabegeräte neu suchen**.
- **akvcam-Beispielkonfiguration speichern** exportiert eine INI-Datei; sie wird nicht angewendet.
- Automatische Größen- und Formatumsetzung einschließlich Bildratenanpassung. Spiegelung, Drehung, Graustufen und Negativ werden übernommen; Anzeigen-Overlays nicht.
- Begrenzte Warteschlangen; ein langsamer Empfänger soll die physische Quelle nicht blockieren.
- Eine aktive Ausgabe wird erst nach vom Ausgabesink bestätigten Bildern als empfangend angezeigt. Fehler und ausbleibende erste Bilder beenden die Weitergabe sichtbar, ohne die physische Vorschau zu beenden.
- Nur Ausgabegeräte der Treiber `akvcam` und `v4l2loopback` werden angeboten. Physische Videoausgänge sind ausgeschlossen. Virtuelle Quellen sind für die Weitergabe gesperrt, um Bildschleifen zu vermeiden.
- Kamerawechsel, Quellformat und Bildfilter bleiben während der Weitergabe gesperrt. Aufnahme und Weitergabe können denselben Quellstream verwenden. Livebild-Stopp und Programmende schließen die Ausgabe.

Die virtuelle V4L2-Kamera überträgt hier ausschließlich Video. In der empfangenden Anwendung muss weiterhin das Mikrofon der physischen Kamera als Tonquelle verwendet werden. Tiny erhält keine separate Mikrofon-Auswahl.

## Konfiguration und Systemgrenze

Die eigene Beispielkonfiguration `akvcam.ini.example` definiert ein Ausgabegerät, ein verbundenes Aufnahmegerät und Formate für 640 × 480 sowie 1280 × 720 bei 30 Bildern/s. Gerätenummern werden nicht festgelegt, damit bestehende Kamera-Nummern nicht reserviert werden. Für andere Anwendungen ist die Aufnahmeseite „Tiny Virtuelle Kamera“ vorgesehen, für dieses Programm die Ausgabeseite „Tiny Bildausgabe“.

Der Treiber ist in dieser Labor-VM bisher **nicht installiert und nicht geladen**. Es wurden keine Systemdateien, Dienste, DKMS-Einträge oder Kernelmodule verändert. Die temporären Quellen und das gebaute Modul wurden nach dem Bautest beim angeforderten Aufräumen entfernt. Geprüfter Quellstand und Modulkennung bleiben dokumentiert; der Fremdtreiber ist kein Bestandteil des MIT-Programmcodes. Die Installation muss gesondert beauftragt werden. Dabei wären insbesondere Kernelmodul/DKMS, Treiberkonfiguration und Laden des Moduls Systemänderungen. Ein vollständiger Laufzeittest einschließlich zweitem Kamera-Verbraucher steht bis dahin aus.

Es wurde kein GPL-Treibercode in die MIT-Anwendung übernommen. Die selbst geschriebene Anwendung kommuniziert über die normale V4L2-/GStreamer-Schnittstelle mit einem getrennt installierten Treiber. Eine spätere Weitergabe des Treibers müsste dessen eigene Lizenzbedingungen erfüllen.

## Prüfungen

Die zusätzlichen automatischen Tests prüfen getrennte Capture-/Output-Knoten, Ausschluss physischer Ausgabegeräte, Schleifenschutz, exportierte Konfiguration und einen echten GStreamer-Ausgabestream mit verarbeiteten Bildpunkten. Dafür dient ein synthetischer Sink; er ersetzt keinen Test mit geladenem akvcam-Modul. Alle 25 Desktop-Tests und die zuvor ausgeführten 875 Backend-Tests bestanden.

## Originalquellen

- [Projekt und README](https://github.com/webcamoid/akvcam)
- [Kameras und Verbindungen konfigurieren](https://github.com/webcamoid/akvcam/wiki/Configure-the-cameras)
- [Benutzung und Beispiele](https://github.com/webcamoid/akvcam/wiki/Usage-and-examples)
- [Lizenz](https://github.com/webcamoid/akvcam/blob/d1243f277d0a10efd9fec04574ad6fcb4265f7b0/COPYING)
