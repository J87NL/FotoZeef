#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST="$ROOT/dist"
APPDIR="$DIST/FotoZeef.AppDir"

cd "$ROOT"
uv run pyinstaller --noconfirm --clean packaging/fotozeef.spec

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a "$DIST/FotoZeef/." "$APPDIR/usr/bin/"
cp packaging/linux/fotozeef.desktop "$APPDIR/usr/share/applications/fotozeef.desktop"
cp packaging/linux/fotozeef.desktop "$APPDIR/fotozeef.desktop"
cp fotozeef/resources/icon.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/fotozeef.png"
cp fotozeef/resources/icon.png "$APPDIR/fotozeef.png"

cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/FotoZeef" "$@"
RUN
chmod +x "$APPDIR/AppRun"

if [ ! -x "$DIST/appimagetool" ]; then
  curl -fsSL -o "$DIST/appimagetool" \
    "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$(uname -m).AppImage"
  chmod +x "$DIST/appimagetool"
fi

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)"
APPIMAGE="$DIST/FotoZeef-$VERSION-$(uname -m).AppImage"

ARCH="$(uname -m)" "$DIST/appimagetool" --appimage-extract-and-run "$APPDIR" "$APPIMAGE"
echo "built $APPIMAGE"
