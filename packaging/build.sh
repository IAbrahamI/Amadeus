#!/usr/bin/env bash
# Builds the packages into dist/ from what's committed plus the built desktop app. Needs nfpm and a release build of
# the app in .tauri-build/target/release/. The layout under /usr/lib/amadeus is the same as a git checkout, without
# what's only for developing.
set -euo pipefail
cd "$(dirname "$0")/.."
export VERSION; VERSION="$(cat VERSION)"
export RPM_KEY="${RPM_KEY:-}"  # the signing key for the .rpm: without it, it's unsigned
BIN=.tauri-build/target/release/amadeus-desktop
[ -x "$BIN" ] || { echo "Build the desktop app first: $BIN is missing"; exit 1; }
rm -rf dist; mkdir -p dist/stage
git archive HEAD core obsidian install.sh amadeus.env.example VERSION LICENSE | tar -x -C dist/stage
rm -rf dist/stage/core/tests
find dist/stage/core/desktop-tauri -mindepth 1 -not -name build.sh -delete
mkdir -p dist/stage/.tauri-build/target/release
cp "$BIN" dist/stage/.tauri-build/target/release/
sed -e "s|@REPO@|/usr/lib/amadeus|g" core/deploy/bin/amadeus > dist/amadeus
for f in deb rpm archlinux; do nfpm package --config packaging/nfpm.yaml --packager "$f" --target dist/; done
rm -rf dist/stage dist/amadeus
(cd dist && sha256sum ./* > SHA256SUMS)
ls -la dist
