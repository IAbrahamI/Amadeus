#!/usr/bin/env bash
# Installs Amadeus Core for the current user (best on KDE Plasma; other Linux desktops work with small limits):
# systemd user services (core, tray icon, voice, wake word, nightly leak scan), the `amadeus` launcher, the app-menu entry,
# and the KWin rule for the small window. (Thunderbird's autostart comes with the mail setup: core/thunderbird/install.sh.)
# Run it again after moving the repository. Use --dry-run to only print what would be written, and --uninstall to remove
# everything it (and the main install.sh) put on the system, except your data in ~/.local/share/amadeus/.
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
if [ "$DRY" = "--uninstall" ]; then
  units="amadeus-core amadeus-desktop amadeus-tray amadeus-voice amadeus-wake amadeus-tn amadeus-leak-scan.timer amadeus-vault-snapshot.timer"
  systemctl --user disable --now $units 2>/dev/null || true
  for f in amadeus-core.service amadeus-desktop.service amadeus-tray.service amadeus-voice.service amadeus-wake.service amadeus-tn.service amadeus-leak-scan.service \
           amadeus-leak-scan.timer amadeus-vault-snapshot.service amadeus-vault-snapshot.timer; do rm -fv "$HOME/.config/systemd/user/$f"; done
  systemctl --user daemon-reload
  rm -fv "$BIN/amadeus" "$BIN/amadeus-mail-start" "$BIN/amadeus-leak-scan" "$BIN/amadeus-vault-snapshot" \
    "$HOME/.local/share/applications/amadeus.desktop" "$HOME/.config/autostart/amadeus-thunderbird.desktop" \
    "$HOME/.config/autostart/amadeus.desktop" "$HOME/.local/share/amadeus/kwin/minimize-thunderbird.js" \
    "$HOME/.thunderbird/native-messaging-hosts/amadeus_bridge.json" "$HOME/.mozilla/native-messaging-hosts/amadeus_bridge.json"
  if [ -d "$HOME/.local/share/amadeus/work-guard" ]; then chmod -R u+w "$HOME/.local/share/amadeus/work-guard"; rm -rfv "$HOME/.local/share/amadeus/work-guard"; fi
  if command -v kwriteconfig6 >/dev/null; then  # the KWin rule for the small window
    rules=$(kreadconfig6 --file kwinrulesrc --group General --key rules | tr ',' '\n' | grep -vx 'amadeus-call\|amadeus-dash' | paste -sd, -)
    kwriteconfig6 --file kwinrulesrc --group General --key rules "$rules"
    kwriteconfig6 --file kwinrulesrc --group General --key count "$(tr ',' '\n' <<<"$rules" | grep -c . || true)"
    for g in amadeus-call amadeus-dash; do
      for k in Description wmclass wmclassmatch title titlematch above aboverule position positionrule noborder noborderrule \
               skiptaskbar skiptaskbarrule skippager skippagerrule skipswitcher skipswitcherrule; do
        kwriteconfig6 --file kwinrulesrc --group "$g" --key "$k" --delete 2>/dev/null || true; done; done
    qdbus6 org.kde.KWin /KWin reconfigure 2>/dev/null || true
  fi
  echo "Removed. Your data in ~/.local/share/amadeus/ and the containers are still there (see docs/INSTALL.md, Uninstall)."
  exit 0
fi
for u in amadeus-core amadeus-desktop amadeus-voice amadeus-wake amadeus-tn amadeus-leak-scan; do put "$HERE/systemd/$u.service" "$HOME/.config/systemd/user/$u.service"; done
put "$HERE/systemd/amadeus-leak-scan.timer" "$HOME/.config/systemd/user/amadeus-leak-scan.timer"
put "$HERE/bin/amadeus" "$BIN/amadeus"
put "$HERE/bin/amadeus-leak-scan" "$BIN/amadeus-leak-scan"
put "$HERE/autostart/amadeus.desktop" "$HOME/.local/share/applications/amadeus.desktop"
[ "$DRY" = "--dry-run" ] && exit 0
chmod +x "$BIN/amadeus" "$BIN/amadeus-leak-scan"
"$REPO/core/desktop-tauri/build.sh"
systemctl --user disable --now amadeus-tray 2>/dev/null || true  # the older tray icon: now part of the desktop app
rm -f "$HOME/.config/systemd/user/amadeus-tray.service"
systemctl --user daemon-reload
systemctl --user enable --now amadeus-core amadeus-desktop amadeus-leak-scan.timer
if [ -x "$HOME/.local/share/amadeus/voice/venv-lite/bin/python" ]; then
  systemctl --user enable --now amadeus-voice
  [ -d "$HOME/.local/share/amadeus/voice/models/vosk-model-small-en-us-0.15" ] && command -v parec >/dev/null && systemctl --user enable --now amadeus-wake
  [ -x "$HOME/.local/share/amadeus/voice/venv-tn/bin/python" ] && systemctl --user enable --now amadeus-tn
else
  echo "voice: not set up (see docs/INSTALL.md, optional: voice); amadeus-voice not started"
fi
if [[ "${XDG_CURRENT_DESKTOP:-}" == *KDE* ]]; then
  "$REPO/core/desktop/install-kwin-rule.sh" || echo "KWin rule skipped"
else
  echo "Not KDE Plasma: the window opens as a normal window (no automatic corner placement)"
fi
echo "Done. Open Amadeus with: amadeus"
