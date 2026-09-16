#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP="$ROOT/dist/FotoZeef.app"

cd "$ROOT"
uv run pyinstaller --noconfirm --clean packaging/fotozeef.spec

# Signing and notarisation are opt-in: set the variables below in CI secrets
# once a Developer ID certificate exists. Without them the bundle still runs
# locally after the first right-click ▸ Open.
if [ -n "${MACOS_SIGN_IDENTITY:-}" ]; then
  codesign --deep --force --options runtime --timestamp \
    --sign "$MACOS_SIGN_IDENTITY" "$APP"
  codesign --verify --strict --verbose=2 "$APP"
fi

if [ -n "${MACOS_NOTARY_PROFILE:-}" ]; then
  ditto -c -k --keepParent "$APP" "$ROOT/dist/FotoZeef.zip"
  xcrun notarytool submit "$ROOT/dist/FotoZeef.zip" \
    --keychain-profile "$MACOS_NOTARY_PROFILE" --wait
  xcrun stapler staple "$APP"
fi

echo "built $APP"
