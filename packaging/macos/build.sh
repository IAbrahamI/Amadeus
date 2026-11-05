#!/usr/bin/env bash
# Builds Amadeus.app and Amadeus-<version>-<arch>.dmg on a Mac: the desktop app with its own Python and the core inside,
# so nothing else has to be installed for it to start. No paid signature: signed ad hoc, so the first start needs
# "Open Anyway" in System Settings → Privacy & Security.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
[ "$(uname -s)" = Darwin ] || { echo "This builds the Mac app, on a Mac." >&2; exit 1; }
VERSION="$(cat VERSION)"
ARCH="$(uname -m)"
[ "$ARCH" = arm64 ] || { echo "Amadeus supports Macs with an M1 or newer." >&2; exit 1; }
PY_RELEASE=20261026 PY_VERSION=3.13.18
PY_ARCH=aarch64 PY_SHA=e5af2fde6a937a0e0c795a0c595c4efb70578d57463a2657c819992b9b9acbac
OUT="$ROOT/dist/macos"
mkdir -p "$OUT"

# 1. the desktop app
(cd core/desktop-tauri
 npx --yes @tauri-apps/cli@2.12.4 icon icons/icon.png --output icons >/dev/null
 CARGO_TARGET_DIR="$ROOT/.tauri-build/target" npx --yes @tauri-apps/cli@2.12.4 build --bundles app \
   --config '{"bundle":{"active":true,"icon":["icons/icon.icns","icons/icon.png"],"macOS":{"minimumSystemVersion":"12.0"}}}' -- --locked)
APP="$OUT/Amadeus.app"
rm -rf "$APP"
cp -R .tauri-build/target/release/bundle/macos/Amadeus.app "$APP"
RES="$APP/Contents/Resources"

# 2. its own Python
TARBALL="$OUT/python-$PY_VERSION-$PY_ARCH.tar.gz"
[ -f "$TARBALL" ] || curl -fsSL -o "$TARBALL" "https://github.com/astral-sh/python-build-standalone/releases/download/$PY_RELEASE/cpython-$PY_VERSION+$PY_RELEASE-$PY_ARCH-apple-darwin-install_only.tar.gz"
echo "$PY_SHA  $TARBALL" | shasum -a 256 -c -
tar -xzf "$TARBALL" -C "$RES"

# 3. the core (only what it needs when running)
git archive HEAD core VERSION LICENSE | tar -x -C "$RES"
rm -rf "$RES/core/tests" "$RES/core/desktop-tauri"

# 4. one signature over all of it, then the disk image with the usual drag to Applications
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"
STAGE="$OUT/stage"
rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
DMG="$OUT/Amadeus-$VERSION-$ARCH.dmg"
rm -f "$DMG"
hdiutil create -volname Amadeus -srcfolder "$STAGE" -fs HFS+ -format UDZO "$DMG"
rm -rf "$STAGE"
echo "Built $DMG"
