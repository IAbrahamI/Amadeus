#!/usr/bin/env bash
# Installs Amadeus Core for the current user on a KDE Plasma (Wayland) desktop:
# systemd user services (core, tray icon, voice, wake word, nightly leak scan), the `amadeus` launcher, the app-menu entry,
# Thunderbird autostart (minimized) and the KWin rule for the small window.
# Run it again after moving the repository. Use --dry-run to only print what would be written.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd)
HERE="$REPO/core/deploy"
BIN="$HOME/.local/bin"
DRY=${1:-}
put() {  # put <template> <target>: fill in the paths and write the file
  if [ "$DRY" = "--dry-run" ]; then echo "would write $2"; return; fi
  mkdir -p "$(dirname "$2")"
  sed -e "s|@REPO@|$REPO|g" -e "s|@BIN@|$BIN|g" "$1" > "$2"
  echo "wrote $2"
}
for u in amadeus-core amadeus-tray amadeus-voice amadeus-wake amadeus-leak-scan; do put "$HERE/systemd/$u.service" "$HOME/.config/systemd/user/$u.service"; done
put "$HERE/systemd/amadeus-leak-scan.timer" "$HOME/.config/systemd/user/amadeus-leak-scan.timer"
put "$HERE/bin/amadeus" "$BIN/amadeus"
put "$HERE/bin/amadeus-mail-start" "$BIN/amadeus-mail-start"
put "$HERE/bin/amadeus-leak-scan" "$BIN/amadeus-leak-scan"
put "$HERE/kwin/minimize-thunderbird.js" "$HOME/.local/share/amadeus/kwin/minimize-thunderbird.js"
put "$HERE/autostart/amadeus.desktop" "$HOME/.local/share/applications/amadeus.desktop"
put "$HERE/autostart/amadeus-thunderbird.desktop" "$HOME/.config/autostart/amadeus-thunderbird.desktop"
[ "$DRY" = "--dry-run" ] && exit 0
chmod +x "$BIN/amadeus" "$BIN/amadeus-mail-start" "$BIN/amadeus-leak-scan"
systemctl --user daemon-reload
systemctl --user enable --now amadeus-core amadeus-tray amadeus-leak-scan.timer
if [ -x "$HOME/.local/share/amadeus/voice/venv-lite/bin/python" ]; then
  systemctl --user enable --now amadeus-voice
  [ -d "$HOME/.local/share/amadeus/voice/models/vosk-model-small-en-us-0.15" ] && systemctl --user enable --now amadeus-wake
else
  echo "voice: not set up (see docs/INSTALL.md, optional: voice); amadeus-voice not started"
fi
"$REPO/core/desktop/install-kwin-rule.sh" || echo "KWin rule skipped (not on KDE?)"
echo "Done. Open Amadeus with: amadeus"
