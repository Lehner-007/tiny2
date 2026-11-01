#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
VERSION="$(cat "$ROOT/VERSION")"
PACKAGE=tiny
ARCH=amd64
NODE_VERSION=22.23.4
NODE_SHA256=1805bcd35e6815559bd2eb97db438d3fdb0eb3a5e6a977b7c1badca76337e9ce
OUT_DIR="${TINY_DEB_OUTPUT_DIR:-$ROOT/work/release-output}"
WORK="$ROOT/work/deb-build"

[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Ungültige VERSION" >&2; exit 1; }
[[ "$(node -p "require('$ROOT/package.json').version")" == "$VERSION" ]] || { echo "package.json und VERSION unterscheiden sich" >&2; exit 1; }
[[ -f "$ROOT/assets/tiny.png" && -f "$ROOT/LICENSE" && -f "$ROOT/dist/index.js" ]] || { echo "Programmdateien oder Symbol fehlen; erst Build ausführen" >&2; exit 1; }
[[ -x "$ROOT/native/prebuilt/linux-x64/obsbot-helper" ]] || { echo "Linux-Hilfsprogramm fehlt oder ist nicht ausführbar" >&2; exit 1; }
for tool in dpkg-deb sha256sum curl tar npm desktop-file-validate; do command -v "$tool" >/dev/null || { echo "Benötigtes Werkzeug fehlt: $tool" >&2; exit 1; }; done
[[ "$(dpkg --print-architecture)" == "$ARCH" ]] || { echo "Dieses Paket wird nur für amd64 gebaut" >&2; exit 1; }
mkdir -p "$WORK/downloads" "$OUT_DIR"
DEB="$OUT_DIR/${PACKAGE}_${VERSION}_${ARCH}.deb"
[[ ! -e "$DEB" ]] || { echo "Zieldatei existiert bereits: $DEB" >&2; exit 1; }

ARCHIVE="node-v${NODE_VERSION}-linux-x64.tar.xz"
BASE="https://nodejs.org/dist/v${NODE_VERSION}"
curl -fL "$BASE/$ARCHIVE" -o "$WORK/downloads/$ARCHIVE"
printf '%s  %s\n' "$NODE_SHA256" "$WORK/downloads/$ARCHIVE" | sha256sum --check --status || { echo "Node.js-Archiv-Prüfsumme stimmt nicht" >&2; exit 1; }

STAGE="$(mktemp -d "$WORK/stage.XXXXXX")"
trap 'rm -rf -- "$STAGE"' EXIT
ROOTFS="$STAGE/root"
mkdir -p "$ROOTFS/DEBIAN" "$ROOTFS/usr/share/tiny" "$ROOTFS/usr/bin" "$ROOTFS/usr/share/applications" "$ROOTFS/usr/share/doc/tiny" "$ROOTFS/usr/share/tiny/runtime/node"
APP="$ROOTFS/usr/share/tiny"
for path in assets desktop dist help lang; do
  [[ -d "$ROOT/$path" ]] && cp -a "$ROOT/$path" "$APP/"
done
mkdir -p "$APP/native/prebuilt"
cp -a "$ROOT/native/prebuilt/linux-x64" "$APP/native/prebuilt/"
for file in tiny.py projekt.json VERSION package.json package-lock.json; do cp "$ROOT/$file" "$APP/"; done
rm -rf "$APP/desktop/__pycache__" "$APP/desktop/vendor/josef_basis/__pycache__"
find "$APP" -type d -name __pycache__ -prune -exec rm -rf -- {} +
find "$APP" -type f -name '*.pyc' -delete
chmod 0644 "$APP/assets/tiny.png"
tar -xJf "$WORK/downloads/$ARCHIVE" --strip-components=1 -C "$APP/runtime/node"
npm ci --omit=dev --ignore-scripts --prefix "$APP" --no-audit --no-fund
rm -f "$APP/package.json" "$APP/package-lock.json"
cp "$ROOT/LICENSE" "$APP/LICENSE"
cp "$ROOT/LICENSE" "$ROOTFS/usr/share/doc/tiny/copyright"

cat > "$ROOTFS/usr/bin/tiny" <<'LAUNCHER'
#!/bin/sh
exec /usr/bin/python3 -B /usr/share/tiny/tiny.py "$@"
LAUNCHER
chmod 0755 "$ROOTFS/usr/bin/tiny" "$APP/native/prebuilt/linux-x64/obsbot-helper" "$APP/runtime/node/bin/node"
cat > "$ROOTFS/usr/share/applications/tiny.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Tiny
GenericName=Kamerasteuerung
Comment=OBSBOT Tiny 2 und Logitech C922 steuern
Exec=/usr/bin/tiny
Icon=/usr/share/tiny/assets/tiny.png
Terminal=false
Categories=AudioVideo;Video;
StartupNotify=true
DESKTOP
desktop-file-validate "$ROOTFS/usr/share/applications/tiny.desktop"

cat > "$ROOTFS/DEBIAN/control" <<CONTROL
Package: tiny
Version: $VERSION
Section: video
Priority: optional
Architecture: $ARCH
Depends: python3, python3-gi, gir1.2-gtk-4.0, gir1.2-gstreamer-1.0, gir1.2-gst-plugins-base-1.0, python3-gst-1.0, gstreamer1.0-plugins-base, libjpeg8
Recommends: gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad, gstreamer1.0-libav, ffmpeg, pulseaudio-utils
Maintainer: Josef Lehner
Description: OBSBOT Tiny 2 and Logitech C922 camera control
 GTK 4 desktop application for camera control, live preview and capture.
 Node.js 22 is bundled privately and does not replace system Node.js.
CONTROL

cat > "$ROOTFS/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -u
case "${1:-}" in
  purge)
    getent passwd | while IFS=: read -r user _ uid _ _ home _; do
      [ "$uid" -ge 1000 ] 2>/dev/null && [ "$uid" -lt 60000 ] 2>/dev/null || continue
      case "$home" in /home/*) ;; *) continue ;; esac
      [ -d "$home" ] && [ ! -L "$home" ] || continue
      registry="$home/.local/state/tiny/obsbot-config-dir"
      config="$home/.config/obsbot"
      if [ -f "$registry" ] && [ ! -L "$registry" ]; then
        config=$(cat -- "$registry" 2>/dev/null || true)
      fi
      case "$config" in /*) ;; *) echo "Tiny: ungueltiger XDG-Pfad fuer $user; Registrierung bleibt erhalten." >&2; continue ;; esac
      resolved=$(realpath -m -- "$config" 2>/dev/null || true)
      case "$resolved" in "$home"/*/obsbot) ;; *) echo "Tiny: XDG-Konfiguration ausserhalb des Benutzerordners geschuetzt: $config" >&2; continue ;; esac
      if [ -L "$resolved" ]; then
        echo "Tiny: Konfigurations-Symlink geschuetzt: $resolved" >&2
        continue
      fi
      if { [ -e "$resolved" ] || [ -L "$resolved" ]; } && ! runuser -u "$user" -- env HOME="$home" /bin/sh -c 'rm -rf -- "$1"' sh "$resolved"; then
        echo "Tiny: Konfiguration konnte nicht entfernt werden: $resolved" >&2
        continue
      fi
      if [ -e "$registry" ] || [ -L "$registry" ]; then
        if [ -f "$registry" ] && [ ! -L "$registry" ] && runuser -u "$user" -- env HOME="$home" /bin/sh -c 'rm -f -- "$1"' sh "$registry"; then
          rmdir "$home/.local/state/tiny" "$home/.local/state" 2>/dev/null || true
        else
          echo "Tiny: XDG-Registrierung konnte nicht entfernt werden: $registry" >&2
          continue
        fi
      fi
    done
    ;;
esac
exit 0
POSTRM
chmod 0755 "$ROOTFS/DEBIAN/postrm"

dpkg-deb --root-owner-group --build "$ROOTFS" "$DEB"
(cd "$OUT_DIR" && sha256sum "$(basename "$DEB")" > "$(basename "$DEB").sha256")
dpkg-deb --info "$DEB" >/dev/null
dpkg-deb --contents "$DEB" >/dev/null
(cd "$OUT_DIR" && sha256sum --check "$(basename "$DEB").sha256")
echo "DEB: $DEB"
echo "SHA256: $DEB.sha256"
