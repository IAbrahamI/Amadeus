#!/usr/bin/env bash
# Builds the desktop app (window and tray). Rust and the build output stay in .tauri-build/ inside the repo; delete that
# folder to remove them (keep .tauri-build/target/release/amadeus-desktop if you do: it's the app the service runs).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
OUT="$ROOT/.tauri-build"
export RUSTUP_HOME="$OUT/rustup" CARGO_HOME="$OUT/cargo" CARGO_TARGET_DIR="$OUT/target" PATH="$OUT/cargo/bin:$PATH"
if [ ! -x "$OUT/cargo/bin/cargo" ]; then
  echo "Installing Rust into $OUT (about 600 MB, only for building)"
  mkdir -p "$OUT"
  curl -fsSL -o "$OUT/rustup-init" "https://static.rust-lang.org/rustup/dist/$(uname -m)-unknown-linux-gnu/rustup-init"
  chmod +x "$OUT/rustup-init"
  "$OUT/rustup-init" -y --no-modify-path --profile minimal --default-toolchain stable
fi
cd "$HERE"
nice -n 15 cargo build --release --locked
echo "Built $OUT/target/release/amadeus-desktop"
