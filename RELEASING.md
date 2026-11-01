# Tiny veröffentlichen

Tiny wird als Debian-Paket auf GitHub veröffentlicht. Die Release-Aktion wird durch einen Versions-Tag `vX.Y.Z` gestartet. Sie prüft die Version, führt die Node-Tests aus, baut Backend und Linux-Hilfsprogramm und erstellt ein amd64-DEB samt SHA-256-Datei. Das DEB enthält eine private Node.js-22-Laufzeit unter `/usr/share/tiny/runtime/`; die systemweite Node-Installation wird weder ersetzt noch geändert.

Vor einem Release müssen `VERSION`, `package.json`, `package-lock.json`, `server.json`, `src/version.ts`, README und Changelog dieselbe Versionsnummer tragen. Der Workflow führt `npm audit`, die Node- und Desktop-Tests aus, baut das DEB und prüft es vor dem Upload. Das Paket wird lokal mit `scripts/erstelledeb.sh` gebaut. Es darf nicht installiert werden, um den Paketinhalt zu prüfen.

Der Workflow `.github/workflows/release.yml` veröffentlicht ausschließlich GitHub Release-Anhänge. Er veröffentlicht weder das npm-Paket noch Metadaten im MCP Registry.
