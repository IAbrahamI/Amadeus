#!/usr/bin/env bash
# Makes the key the Mac app's updates are signed with. Run it once, yourself (it asks for a password and never shows
# the key):
#   1. the private key goes to ~/.tauri/amadeus-updater.key (back it up, like the package signing key: without it no
#      installed Mac can be updated again, only reinstalled),
#   2. it and its password become the GitHub secrets TAURI_SIGNING_PRIVATE_KEY and TAURI_SIGNING_PRIVATE_KEY_PASSWORD,
#   3. the public half goes to packaging/macos/updater.pub, which is built into the app (commit it).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
KEY="$HOME/.tauri/amadeus-updater.key"
PUB="$ROOT/packaging/macos/updater.pub"
command -v gh >/dev/null || { echo "Needs the GitHub CLI (gh), signed in: gh auth login" >&2; exit 1; }
command -v npx >/dev/null || { echo "Needs Node.js (npx)" >&2; exit 1; }
if [ -e "$KEY" ]; then
  echo "$KEY already exists. A new key would cut off every installed Mac from updates, so nothing was changed." >&2
  echo "To set the secrets from it again: gh secret set TAURI_SIGNING_PRIVATE_KEY < \"$KEY\"" >&2
  exit 1
fi
mkdir -p "$(dirname "$KEY")"
echo "Choose a password for the update key (asked twice):"
npx --yes @tauri-apps/cli@2.12.4 signer generate -w "$KEY"
chmod 600 "$KEY"
cd "$ROOT"
gh secret set TAURI_SIGNING_PRIVATE_KEY < "$KEY"
echo "The same password once more, for the GitHub secret:"
gh secret set TAURI_SIGNING_PRIVATE_KEY_PASSWORD
cp "$KEY.pub" "$PUB"
echo
echo "Done. Back up $KEY and its password, then commit packaging/macos/updater.pub."
