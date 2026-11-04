#!/usr/bin/env bash
# Sets up the Amadeus Bridge for Thunderbird: registers the native host and builds the add-on file.
# Then in Thunderbird: Add-ons and Themes → gear icon → "Install Add-on From File…" → pick the .xpi printed below.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=~/.local/share/amadeus/amadeus-bridge.xpi
for d in ~/.thunderbird/native-messaging-hosts ~/.mozilla/native-messaging-hosts; do
  mkdir -p "$d"
  cat > "$d/amadeus_bridge.json" <<JSON
{
  "name": "amadeus_bridge",
  "description": "Amadeus Bridge (local)",
  "path": "$HERE/bridge_host.py",
  "type": "stdio",
  "allowed_extensions": ["amadeus-bridge@local"]
}
JSON
done
mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"
(cd "$HERE/addon" && python3 -c "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1],'w',zipfile.ZIP_DEFLATED); [z.write(f) for f in ('manifest.json','background.js')]; z.close()" "$OUT")
# Thunderbird starts minimized at login, so mail is there when Amadeus needs it
DEPLOY="$HERE/../deploy"; BIN="$HOME/.local/bin"
mkdir -p "$BIN" "$HOME/.config/autostart" "$HOME/.local/share/amadeus/kwin"
sed -e "s|@BIN@|$BIN|g" "$DEPLOY/bin/amadeus-mail-start" > "$BIN/amadeus-mail-start"; chmod +x "$BIN/amadeus-mail-start"
cp "$DEPLOY/kwin/minimize-thunderbird.js" "$HOME/.local/share/amadeus/kwin/minimize-thunderbird.js"
sed -e "s|@BIN@|$BIN|g" "$DEPLOY/autostart/amadeus-thunderbird.desktop" > "$HOME/.config/autostart/amadeus-thunderbird.desktop"
echo "Native host registered. Add-on file: $OUT"
