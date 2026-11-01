#!/usr/bin/env bash
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
version_file="$root/VERSION"
[[ -r "$version_file" ]] || { echo "VERSION fehlt" >&2; exit 2; }
version="$(<"$version_file")"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Ungültige VERSION: $version" >&2; exit 2; }

for cmd in npm node zip unzip sha256sum; do
    command -v "$cmd" >/dev/null || { echo "Benötigtes Werkzeug fehlt: $cmd" >&2; exit 2; }
done
[[ -f "$root/dist/index.js" ]] || { echo "dist/index.js fehlt; zuerst npm run build ausführen" >&2; exit 2; }
[[ -x "$root/native/prebuilt/linux-x64/obsbot-helper" ]] || { echo "Linux-Helfer fehlt oder ist nicht ausführbar" >&2; exit 2; }
[[ -f "$root/assets/tiny.png" && -f "$root/LICENSE" ]] || { echo "Symbol oder Lizenz fehlt" >&2; exit 2; }

work="$root/work"
mkdir -p -- "$work"
stage="$(mktemp -d "$work/zip-stage.XXXXXX")"
trap 'rm -rf -- "$stage"' EXIT
app="$stage/Tiny-$version"
mkdir -p -- "$app"

for item in assets desktop dist help lang; do
    cp -a -- "$root/$item" "$app/$item"
done
mkdir -p -- "$app/native/prebuilt/linux-x64"
cp -a -- "$root/native/prebuilt/linux-x64/obsbot-helper" "$app/native/prebuilt/linux-x64/"
cp -a -- "$root/tiny.py" "$root/projekt.json" "$root/VERSION" "$root/LICENSE" "$app/"
touch "$app/.development"
mkdir -p -- "$app/docs"
cp -a -- "$root/docs/DESKTOP.md" "$root/docs/AKVCAM.md" "$app/docs/"

# Install only locked production dependencies in the isolated archive staging area.
cp -- "$root/package.json" "$root/package-lock.json" "$app/"
PATH="$(dirname -- "$(command -v node)"):$(dirname -- "$(command -v npm)"):$PATH" \
    npm ci --omit=dev --ignore-scripts --prefix "$app"
python3 - "$app/package.json" "$version" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
version = sys.argv[2]
source = json.loads(path.read_text(encoding='utf-8'))
runtime = {
    'name': source['name'],
    'version': version,
    'description': source.get('description', ''),
    'type': 'module',
    'license': source.get('license', ''),
    'engines': source.get('engines', {}),
    'dependencies': source.get('dependencies', {}),
}
if source.get('optionalDependencies'):
    runtime['optionalDependencies'] = source['optionalDependencies']
path.write_text(json.dumps(runtime, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
PY
rm -f -- "$app/package-lock.json"
find "$app" -type f \( -name package-lock.json -o -name .package-lock.json \) -delete

find "$app" -type d -name __pycache__ -prune -exec rm -rf -- {} +
find "$app/node_modules" -type d \( -name test -o -name tests -o -name __tests__ \) -prune -exec rm -rf -- {} +
find "$app" -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '*.tsbuildinfo' \) -delete
chmod 0755 "$app/tiny.py"
cat > "$app/START-HERE.txt" <<EOF
Tiny $version – Linux x86-64

Starten: In diesem Ordner ein Terminal öffnen und ./tiny.py ausführen.
Alternativ: python3 ./tiny.py

Voraussetzungen: Python 3, GTK 4 mit PyGObject, GStreamer mit den in
docs/DESKTOP.md genannten Plugins sowie Node.js 20 oder neuer. Die Node-
Laufzeitabhängigkeiten und der Linux-Kamerahelfer sind enthalten. Das Archiv
installiert keine Systempakete und keine Kameratreiber.

Einstellungen und Profile werden im Ordner .config neben tiny.py gespeichert.
Dieser Ordner benötigt Schreibrechte.

Entwicklungs- und vollständige Testanweisungen liegen im separaten vollständigen
Quellprojekt; dieses Laufzeitarchiv enthält weder Tests noch package-lock.json.
EOF
cat > "$app/START-HERE.en.txt" <<EOF
Tiny $version – Linux x86-64

Start from a terminal opened in this folder with ./tiny.py, or run:
  python3 ./tiny.py

Requirements: Python 3, GTK 4 with PyGObject, GStreamer with the plugins listed
in docs/DESKTOP.md, and Node.js 20 or newer. Node production dependencies and
the Linux camera helper are included. The archive does not install system
packages or camera drivers.

Settings and profiles are stored in .config beside tiny.py. This folder must
be writable.

Development and full test instructions belong to the separate complete source
project; this runtime archive contains neither tests nor package-lock.json.
EOF

outdir="$work/release-output"
mkdir -p -- "$outdir"
suffix="${TINY_ZIP_SUFFIX:-}"
if [[ -n "$suffix" && ! "$suffix" =~ ^[a-zA-Z0-9._-]+$ ]]; then
    echo "Ungültiger TINY_ZIP_SUFFIX" >&2
    exit 2
fi
archive="$outdir/Tiny-$version-linux-x64${suffix:+-$suffix}.zip"
checksum="$archive.sha256"
[[ ! -e "$archive" && ! -e "$checksum" ]] || {
    echo "Ausgabedatei existiert bereits; unverändert gelassen: $archive" >&2
    exit 3
}
(cd -- "$stage" && zip -q -r -X "$archive" "Tiny-$version")
unzip -tq "$archive"
unzip -Z1 "$archive" > "$stage/archive-list.txt"
for required in \
    "Tiny-$version/tiny.py" \
    "Tiny-$version/VERSION" \
    "Tiny-$version/LICENSE" \
    "Tiny-$version/package.json" \
    "Tiny-$version/assets/tiny.png" \
    "Tiny-$version/desktop/gui.py" \
    "Tiny-$version/dist/index.js" \
    "Tiny-$version/native/prebuilt/linux-x64/obsbot-helper" \
    "Tiny-$version/node_modules/@modelcontextprotocol/sdk/package.json"; do
    grep -Fxq -- "$required" "$stage/archive-list.txt" || {
        echo "Pflichtdatei fehlt im ZIP: $required" >&2
        rm -f -- "$archive"
        exit 4
    }
done
grep -Eq '"type"[[:space:]]*:[[:space:]]*"module"' <(unzip -p "$archive" "Tiny-$version/package.json") || {
    echo "ES-Modul-Kennzeichnung fehlt in package.json" >&2
    exit 4
}
if grep -Eq '(^|/)(\.config|work|test|tests|__pycache__|\.git|node_modules/[^/]+/test)(/|$)|(^|/)\.?package-lock\.json$|\.py[co]$|\.env($|\.)' "$stage/archive-list.txt"; then
    echo "Nicht zur Laufzeit gehörende oder private Datei im ZIP gefunden" >&2
    rm -f -- "$archive"
    exit 4
fi
(cd -- "$outdir" && sha256sum "$(basename -- "$archive")" > "$(basename -- "$checksum")")
echo "ZIP erstellt und geprüft: $archive"
echo "SHA-256: $checksum"
