#!/usr/bin/env bash
# Amadeus installer: everything in one go. It offers to install what's missing (Ollama, Docker, system packages), tests
# this PC's speed and suggests three models. The first run asks a few questions (projects, mail, voice) and keeps the
# answers in ./amadeus.env. Then it sets up Ollama (local LLM), private keys, Presidio (privacy filter), Hindsight
# (memory), the projects folder with the guard for work runs, voice, the assistant itself (core/deploy/install.sh:
# services, window, tray) and the Thunderbird bridge.
#
# Idempotent: every step checks the current state first and skips what is already done.
# It never deletes data. Anything it cannot fix safely is reported with the manual fix.
#
# Usage:
#   ./install.sh              install / repair everything (asks the setup questions the first time)
#   ./install.sh --setup      ask the setup questions again
#   ./install.sh --update     get the latest version (git pull), then install / repair and restart (= amadeus update)
#   ./install.sh --check      read-only: prerequisites and status, changes nothing
#   ./install.sh --dry-run    print what would be done, changes nothing
#   ./install.sh --benchmark  test this PC's speed again and pick another model
#   ./install.sh --only ollama|secrets|presidio|hindsight|obsidian|work|voice|app|mail
#   ./install.sh --help
#
# Settings (override with environment variables, or put them in ./amadeus.env):
#   OLLAMA_MODEL           base model to pull                  (default: the one you pick from the suggestions)
#   OLLAMA_CTX_VARIANT     name of the larger-context variant  (default: qwen3.5-9b-48k, what Amadeus uses)
#   OLLAMA_NUM_CTX         context length for that variant     (default: 49152)
#   OLLAMA_URL             Ollama endpoint                     (default: http://127.0.0.1:11434)
#   HINDSIGHT_IMAGE        container image                     (default: ghcr.io/vectorize-io/hindsight:0.10.2, the tested version)
#   HINDSIGHT_CONTAINER    container name                      (default: hindsight)
#   HINDSIGHT_VOLUME       named volume for its data           (default: hindsight-data)
#   HINDSIGHT_LLM_MODEL    Ollama model Hindsight uses         (default: $OLLAMA_CTX_VARIANT)
#   HINDSIGHT_WORKER_ID    stable worker id                    (default: amadeus-hindsight)
#   OBSIDIAN_VAULT         absolute path of your Obsidian vault (optional; normally connected later under Settings → Connectors)
#   AMADEUS_PROJECTS       folder for Claude Code projects, outside the vault (default asked: ~/Amadeus/Projects)
#   AMADEUS_MAIL=1         set up the Thunderbird bridge (mail)
#   AMADEUS_VOICE=1        set up voice: speech recognition and the wake word (about 1 GB, runs on the CPU)
#   ASSUME_YES=1           do not prompt; non-interactive onboarding

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
ENV_FILE="$SCRIPT_DIR/amadeus.env"  # installed as a package the program's folder is read-only: yours goes in your config
[[ -w "$SCRIPT_DIR" ]] || ENV_FILE="$HOME/.config/amadeus-core/amadeus.env"
[[ -f "$ENV_FILE" ]] && source "$ENV_FILE"

MODEL_CHOSEN="${OLLAMA_MODEL:+1}"  # set by you or an earlier run: no need to ask
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3.5:9b}"
OLLAMA_CTX_VARIANT="${OLLAMA_CTX_VARIANT:-qwen3.5-9b-48k}"
OLLAMA_NUM_CTX="${OLLAMA_NUM_CTX:-49152}"
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
HINDSIGHT_IMAGE="${HINDSIGHT_IMAGE:-ghcr.io/vectorize-io/hindsight:0.10.2}"
HINDSIGHT_CONTAINER="${HINDSIGHT_CONTAINER:-hindsight}"
HINDSIGHT_VOLUME="${HINDSIGHT_VOLUME:-hindsight-data}"
HINDSIGHT_LLM_MODEL="${HINDSIGHT_LLM_MODEL:-$OLLAMA_CTX_VARIANT}"
HINDSIGHT_WORKER_ID="${HINDSIGHT_WORKER_ID:-amadeus-hindsight}"
HINDSIGHT_API_PORT=8888
HINDSIGHT_UI_PORT=9999
OBSIDIAN_VAULT="${OBSIDIAN_VAULT:-}"
AMADEUS_MAIL="${AMADEUS_MAIL:-}"
AMADEUS_PROJECTS="${AMADEUS_PROJECTS:-}"
AMADEUS_VOICE="${AMADEUS_VOICE:-}"
VOICE="$HOME/.local/share/amadeus/voice"
VOSK_MODEL=vosk-model-small-en-us-0.15
# not set: keep what an earlier install already set up (the vault in Amadeus' config, voice, the mail bridge)
if [[ -z "$OBSIDIAN_VAULT" ]]; then  # (connected in its config, or an older install's ~/Documents/Obsidian Vault/Amadeus)
  OBSIDIAN_VAULT="$(python3 -c 'import json,os,sys; v=json.load(open(sys.argv[1])).get("vault_dir","") if os.path.exists(sys.argv[1]) else ""; v=v or os.path.expanduser("~/Documents/Obsidian Vault/Amadeus"); p=os.path.dirname(v.rstrip("/")); print(p if os.path.isdir(os.path.join(p,".obsidian")) else "")' "$HOME/.config/amadeus-core/config.json" 2>/dev/null || true)"
fi
[[ -z "$AMADEUS_VOICE" && -x "$VOICE/venv-lite/bin/python" ]] && AMADEUS_VOICE=1
[[ -z "$AMADEUS_MAIL" && -f "$HOME/.thunderbird/native-messaging-hosts/amadeus_bridge.json" ]] && AMADEUS_MAIL=1
DATA="$HOME/.local/share/amadeus"          # everything private lives here, never in the repository
SECRETS="$DATA/secrets"
OBSIDIAN_PLUGIN_VERSION="${OBSIDIAN_PLUGIN_VERSION:-0.5.0}"
ASSUME_YES="${ASSUME_YES:-0}"

MODE=install   # install | check | dry-run
ONLY=""; SETUP=0; UPDATE=0

# ---------------------------------------------------------------- output helpers
if [[ -t 1 ]]; then
  C_OK=$'\e[32m'; C_WARN=$'\e[33m'; C_ERR=$'\e[31m'; C_HEAD=$'\e[1;36m'; C_DIM=$'\e[2m'; C_OFF=$'\e[0m'
else
  C_OK=""; C_WARN=""; C_ERR=""; C_HEAD=""; C_DIM=""; C_OFF=""
fi
ERRORS=0; WARNINGS=0
head_()  { printf '\n%s== %s ==%s\n' "$C_HEAD" "$*" "$C_OFF"; }
ok()     { printf '  %s✓%s %s\n' "$C_OK" "$C_OFF" "$*"; }
info()   { printf '  %s·%s %s\n' "$C_DIM" "$C_OFF" "$*"; }
warn()   { printf '  %s!%s %s\n' "$C_WARN" "$C_OFF" "$*"; WARNINGS=$((WARNINGS+1)); }
err()    { printf '  %s✗%s %s\n' "$C_ERR" "$C_OFF" "$*"; ERRORS=$((ERRORS+1)); }
die()    { err "$*"; exit 1; }
have()   { command -v "$1" >/dev/null 2>&1; }

# run CMD...: execute unless in check/dry-run mode
run() {
  if [[ "$MODE" != install ]]; then
    printf '  %s→ would run:%s %s\n' "$C_DIM" "$C_OFF" "$*"
    return 0
  fi
  printf '  %s→%s %s\n' "$C_DIM" "$C_OFF" "$*"
  local rc=0; "$@" || rc=$?
  (( rc == 0 )) || err "That didn't work: $1 $2"
  return "$rc"
}

confirm() {
  [[ "$ASSUME_YES" == 1 ]] && return 0
  [[ -t 0 ]] || return 1
  local reply; read -r -p "  ? $* [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]]
}

wait_http() { # url seconds
  local url="$1" secs="${2:-60}" i
  for ((i=0; i<secs; i++)); do
    curl -fsS -o /dev/null --max-time 2 "$url" 2>/dev/null && return 0
    sleep 1
  done
  return 1
}

usage() { sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

ORIGINAL_ARGS=("$@")
while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)   MODE=check ;;
    --dry-run) MODE=dry-run ;;
    --only)    ONLY="${2:-}"; shift ;;
    --setup)   SETUP=1 ;;
    --benchmark) ONLY=ollama; MODEL_CHOSEN=""; BENCHMARK=1 ;;
    --update)  UPDATE=1 ;;
    --updated) UPDATE=2 ;;  # internal: the new installer after an update (pull already done)
    -y|--yes)  ASSUME_YES=1 ;;
    -h|--help) usage ;;
    *) die "Unknown option: $1 (see --help)" ;;
  esac
  shift
done
want() { [[ -z "$ONLY" || "$ONLY" == "$1" ]]; }

# ---------------------------------------------------------------- what's missing gets installed, after asking
PKG=""; have pacman && PKG=pacman; have apt-get && PKG=apt; have dnf && PKG=dnf
pkg_install() {  # pkg_install NAME...: with the distribution's package manager
  case "$PKG" in
    pacman) run sudo pacman -S --needed --noconfirm "$@" ;;
    apt)    run sudo apt-get update -qq; run sudo apt-get install -y "$@" ;;
    dnf)    run sudo dnf install -y "$@" ;;
  esac
}
offer() {  # offer "what" "commands shown": yes in a real install when you agree; a dry run just shows it
  info "$1 is missing. To install it: $2"
  [[ "$MODE" == dry-run ]] && return 0
  [[ "$MODE" == install ]] && confirm "Install $1 now? (uses sudo)"
}
phase_deps() {
  [[ "$MODE" != check ]] || return 0
  [[ -n "$PKG" ]] || { info "Unknown package manager: install what's reported below by hand (docs/INSTALL.md)."; return 0; }
  # the desktop app's system packages (a package brings the app ready-built)
  if want app && [[ -f "$SCRIPT_DIR/core/desktop-tauri/src/main.rs" ]]; then
    local need=()
    have python3 && python3 -c 'import venv, ensurepip' 2>/dev/null || need+=(python)
    have gcc && have pkg-config || need+=(build)
    pkg-config --exists webkit2gtk-4.1 gtk+-3.0 2>/dev/null || need+=(gui)
    have curl || need+=(curl)
    if (( ${#need[@]} )); then
      local pkgs=() n
      for n in "${need[@]}"; do case "$PKG:$n" in
        pacman:python) pkgs+=(python) ;; apt:python) pkgs+=(python3 python3-venv) ;; dnf:python) pkgs+=(python3) ;;
        pacman:build) pkgs+=(base-devel pkgconf) ;; apt:build) pkgs+=(build-essential pkg-config) ;; dnf:build) pkgs+=(gcc pkgconf) ;;
        pacman:gui) pkgs+=(gtk3 webkit2gtk-4.1) ;; apt:gui) pkgs+=(libgtk-3-dev libwebkit2gtk-4.1-dev) ;; dnf:gui) pkgs+=(gtk3-devel webkit2gtk4.1-devel) ;;
        *:curl) pkgs+=(curl) ;;
      esac; done
      if offer "${pkgs[*]}" "the $PKG packages for the window and tray"; then pkg_install "${pkgs[@]}"; fi
    fi
  fi
  # Ollama runs the model
  if { want ollama || want hindsight; } && ! have ollama; then
    local ollama_pkg=ollama; have nvidia-smi && ollama_pkg=ollama-cuda
    if [[ "$PKG" == pacman ]]; then
      if offer Ollama "sudo pacman -S $ollama_pkg"; then pkg_install "$ollama_pkg"; run sudo systemctl enable --now ollama; fi
    elif offer Ollama "Ollama's own installer from https://ollama.com/install.sh"; then
      if [[ "$MODE" == install ]]; then curl -fsSL https://ollama.com/install.sh | sh; else printf '  → would run: curl -fsSL https://ollama.com/install.sh | sh\n'; fi
    fi
  fi
  if { want ollama || want hindsight; } && have ollama && [[ "$MODE" == install ]] && ! curl -fsS --max-time 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    if confirm "Ollama isn't running. Start it now? (uses sudo)"; then run sudo systemctl enable --now ollama; wait_http "$OLLAMA_URL/api/tags" 30 || true; fi
  fi
  # Docker runs the memory and the privacy filter
  if want hindsight || want presidio; then
    if ! have docker; then
      local docker_pkg=docker; [[ "$PKG" == apt ]] && docker_pkg=docker.io; [[ "$PKG" == dnf ]] && docker_pkg=moby-engine
      if offer Docker "the $docker_pkg package, its service, and your user in the docker group"; then
        pkg_install "$docker_pkg"; run sudo systemctl enable --now docker; run sudo usermod -aG docker "$USER"
      fi
    elif [[ "$MODE" == install ]] && ! docker info >/dev/null 2>&1; then
      if confirm "Docker isn't usable by $USER yet. Start it and add you to the docker group? (uses sudo)"; then
        run sudo systemctl enable --now docker; run sudo usermod -aG docker "$USER"
      fi
    fi
    # the new group only counts in a new session: carry on in one, instead of asking you to log out first
    if [[ "$MODE" == install && -z "${AMADEUS_IN_DOCKER_GROUP:-}" ]] && have docker && have sg && ! docker info >/dev/null 2>&1; then
      export AMADEUS_IN_DOCKER_GROUP=1
      exec sg docker -c "$(printf '%q ' "$0" "${ORIGINAL_ARGS[@]}")"
    fi
  fi
}

# ---------------------------------------------------------------- prerequisites
phase_prereqs() {
  head_ "Prerequisites"
  [[ "$(uname -s)" == Linux ]] || die "Linux is required (tested on Arch/CachyOS; any systemd distro should work)."
  [[ $EUID -ne 0 ]] || die "Run as your normal user, not root. Services are installed per user."

  have curl && ok "curl" || err "curl is missing. Install it with your package manager."
  if have systemctl && systemctl --user show-environment >/dev/null 2>&1; then
    ok "systemd user session"
  else
    err "systemd user session not available (systemctl --user). Amadeus runs as user services."
  fi

  if have nvidia-smi; then
    ok "NVIDIA GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1)"
  else
    warn "nvidia-smi not found. Ollama will fall back to CPU (slow). 12 GB VRAM is the tested target."
  fi

  if want ollama || want hindsight; then
    if have ollama; then ok "ollama $(ollama --version 2>/dev/null | grep -oE '[0-9]+\.[0-9.]+' | head -1)"
    else err "ollama is missing. Install: https://ollama.com/download (or your distro package), then enable it: sudo systemctl enable --now ollama"; fi
  fi

  if want hindsight || want presidio; then
    if ! have docker; then
      err "docker is missing. Install Docker Engine and run: sudo systemctl enable --now docker"
    elif ! docker info >/dev/null 2>&1; then
      err "docker is installed but not usable by $USER. Start it (sudo systemctl enable --now docker) and add yourself to the docker group (sudo usermod -aG docker $USER, then log out and back in)."
    else
      ok "docker $(docker version --format '{{.Server.Version}}' 2>/dev/null)"
    fi
  fi

  if want obsidian && [[ -n "$OBSIDIAN_VAULT" ]]; then
    have zstd && ok "zstd (vault snapshots)" || err "zstd is missing; vault snapshots use tar --zstd."
  fi
  if want work; then
    have python3 && ok "python3 (work-run guard)" || err "python3 is missing; the work-run guard needs it."
    if have bwrap && have socat; then ok "bubblewrap + socat (Claude Code sandbox)"
    else warn "bubblewrap and socat are needed for work runs with Claude Code (package names: bubblewrap, socat); without them runs refuse to start."; fi
  fi

  if (( ERRORS > 0 )); then
    [[ "$MODE" == install ]] && die "Fix the prerequisites above, then run this script again."
    [[ "$MODE" == check && -n "$PKG" ]] && info "./install.sh offers to install what's missing here (it asks before using sudo)."
    warn "Prerequisites are incomplete; later phases may show as missing."
  fi
}

# ---------------------------------------------------------------- which model: speed test and three suggestions
phase_pick_model() {
  [[ -z "$MODEL_CHOSEN" ]] || return 0
  ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "${OLLAMA_CTX_VARIANT}:latest\|${OLLAMA_CTX_VARIANT}" && [[ "${BENCHMARK:-}" != 1 ]] && return 0
  if [[ "$MODE" != install ]]; then info "would test this PC's speed and suggest three models"; return 0; fi
  head_ "Which model fits this PC"
  local out; out="$(mktemp)"
  local auto=(); [[ "$ASSUME_YES" == 1 ]] && auto=(--auto)
  local rc=0; python3 "$SCRIPT_DIR/core/deploy/pick_model.py" "$out" "${auto[@]}" || rc=$?
  if (( rc )); then
    rm -f "$out"; NO_MODEL=1
    err "No model yet, so Amadeus can't answer. Fix what's shown above, then run: ./install.sh --benchmark"
    return 0
  fi
  local pick; mapfile -t pick <"$out"; rm -f "$out"
  OLLAMA_MODEL="${pick[0]}"; OLLAMA_CTX_VARIANT="${pick[1]}"; OLLAMA_NUM_CTX="${pick[2]}"; HINDSIGHT_LLM_MODEL="${pick[1]}"
  env_set OLLAMA_MODEL "$OLLAMA_MODEL"; env_set OLLAMA_CTX_VARIANT "$OLLAMA_CTX_VARIANT"; env_set OLLAMA_NUM_CTX "$OLLAMA_NUM_CTX"; env_set HINDSIGHT_LLM_MODEL "$HINDSIGHT_LLM_MODEL"
  python3 - "$OLLAMA_CTX_VARIANT" <<'PYC'
import json, os, sys
p = os.path.expanduser("~/.config/amadeus-core/config.json")
c = json.load(open(p)) if os.path.exists(p) else {}
c["default_model"] = sys.argv[1]
os.makedirs(os.path.dirname(p), exist_ok=True)
json.dump(c, open(p, "w"), indent=2)
PYC
  ok "model: $OLLAMA_MODEL (Amadeus uses $OLLAMA_CTX_VARIANT)"
}

# ---------------------------------------------------------------- Ollama models
phase_ollama() {
  head_ "Local LLM: Ollama"
  have ollama || { err "ollama not installed; skipping."; return; }

  if ! curl -fsS --max-time 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    err "Ollama is not answering at $OLLAMA_URL. Start it: sudo systemctl enable --now ollama"
    return
  fi
  ok "Ollama API reachable at $OLLAMA_URL"

  phase_pick_model
  [[ "${NO_MODEL:-}" != 1 ]] || return 0
  local models; models="$(ollama list 2>/dev/null | awk 'NR>1 {print $1}')"
  if grep -qx "${OLLAMA_MODEL}:latest\|${OLLAMA_MODEL}" <<<"$models"; then
    ok "model $OLLAMA_MODEL present"
  else
    info "pulling $OLLAMA_MODEL (several GB, this takes a while)"
    if ! run ollama pull "$OLLAMA_MODEL"; then
      err "Couldn't download $OLLAMA_MODEL. Fix what's shown above, then run: ./install.sh --benchmark"
      return 0
    fi
  fi

  # the variant Amadeus uses: a larger context, and at most a quarter of the CPU threads (the model runs on the GPU;
  # with every core busy the desktop stutters while it writes, and more threads aren't faster)
  local threads=$(( $(nproc) / 4 )); (( threads < 2 )) && threads=2
  if grep -qx "${OLLAMA_CTX_VARIANT}:latest\|${OLLAMA_CTX_VARIANT}" <<<"$models" \
     && ollama show "$OLLAMA_CTX_VARIANT" --modelfile 2>/dev/null | grep -q '^PARAMETER num_thread'; then
    ok "context variant $OLLAMA_CTX_VARIANT present"
  else
    local mf; mf="$(mktemp)"
    printf 'FROM %s\nPARAMETER num_ctx %s\nPARAMETER num_thread %s\nPARAMETER temperature 0.2\n' "$OLLAMA_MODEL" "$OLLAMA_NUM_CTX" "$threads" >"$mf"
    run ollama create "$OLLAMA_CTX_VARIANT" -f "$mf"
    rm -f "$mf"
  fi
}

# ---------------------------------------------------------------- private keys (never in git)
# hindsight-keys.json: the memory's API key; canaries.json: random markers that must never leave the PC
# (the privacy filter holds any text that contains one); denylist.txt: your own words that must never leave.
phase_secrets() {
  head_ "Private keys and markers ($SECRETS)"
  if [[ "$MODE" != install ]]; then info "would create missing files in $SECRETS"; return; fi
  mkdir -p "$SECRETS"; chmod 700 "$DATA" "$SECRETS" 2>/dev/null || true
  local f="$SECRETS/hindsight-keys.json"
  if [[ -f "$f" ]]; then ok "memory key exists"
  else (umask 077; python3 -c 'import json,secrets;print(json.dumps({"amadeus":secrets.token_urlsafe(32)}))' >"$f"); ok "created the memory key"; fi
  f="$SECRETS/canaries.json"
  if [[ -f "$f" ]]; then ok "canary markers exist"
  else (umask 077; python3 -c 'import json,secrets;print(json.dumps({"vault":"CANARY-"+secrets.token_hex(8)}))' >"$f"); ok "created a canary marker"; fi
  f="$SECRETS/denylist.txt"
  if [[ -f "$f" ]]; then ok "deny-list exists"
  else (umask 077; printf '# One word or phrase per line that must never leave this PC (names, addresses, projects).\n' >"$f"); ok "created an empty deny-list ($f)"; fi
}

# ---------------------------------------------------------------- Presidio (privacy filter)
# Two containers on a private Docker network without internet access: the analyzer (English + German names,
# places, groups) and the anonymizer. Amadeus starts them on demand and stops them when idle.
phase_presidio() {
  head_ "Privacy filter: Presidio in Docker"
  have docker && docker info >/dev/null 2>&1 || { err "docker not usable; skipping."; return; }
  if docker network inspect amadeus-private >/dev/null 2>&1; then ok "network amadeus-private exists"
  else run docker network create --internal --subnet 172.30.77.0/24 amadeus-private; fi
  if docker image inspect amadeus/presidio-analyzer:en-de >/dev/null 2>&1; then ok "analyzer image built"
  else info "building the analyzer image with the German model (a few minutes)"
    run docker build -t amadeus/presidio-analyzer:en-de "$SCRIPT_DIR/core/privacy/presidio" || return 0; fi
  if docker container inspect presidio-analyzer >/dev/null 2>&1; then ok "container presidio-analyzer exists"
  else run docker create --name presidio-analyzer --restart unless-stopped --network amadeus-private --ip 172.30.77.10 \
    amadeus/presidio-analyzer:en-de; fi
  if docker container inspect presidio-anonymizer >/dev/null 2>&1; then ok "container presidio-anonymizer exists"
  else run docker create --name presidio-anonymizer --restart unless-stopped --network amadeus-private --ip 172.30.77.11 \
    mcr.microsoft.com/presidio-anonymizer:latest; fi
}

# ---------------------------------------------------------------- Hindsight memory
phase_hindsight() {
  head_ "Memory: Hindsight in Docker"
  have docker && docker info >/dev/null 2>&1 || { err "docker not usable; skipping."; return; }

  if docker container inspect "$HINDSIGHT_CONTAINER" >/dev/null 2>&1; then
    local state; state="$(docker inspect -f '{{.State.Status}}' "$HINDSIGHT_CONTAINER")"
    ok "container $HINDSIGHT_CONTAINER exists ($state); leaving its configuration untouched"
    if [[ "$state" != running ]]; then run docker start "$HINDSIGHT_CONTAINER"; fi
  else
    docker volume inspect "$HINDSIGHT_VOLUME" >/dev/null 2>&1 \
      && ok "volume $HINDSIGHT_VOLUME exists (existing memories will be reused)" \
      || info "volume $HINDSIGHT_VOLUME will be created"
    # Host networking so the container can reach Ollama on 127.0.0.1; the *_HOST
    # variables bind the API and UI to loopback only, so nothing is exposed on the LAN.
    # Every request needs the key from secrets/hindsight-keys.json (the small extension in core/hindsight_ext maps
    # it to its own database schema); requests without a known key are rejected.
    local ext="$DATA/hindsight-ext" keys
    if [[ "$MODE" == install ]]; then
      mkdir -p "$ext"; cp -r "$SCRIPT_DIR/core/hindsight_ext/amadeus_ext" "$ext/"
      [[ -f "$SECRETS/hindsight-keys.json" ]] || die "The memory key is missing: run ./install.sh --only secrets first."
      keys="$(python3 -c 'import json,sys;k=json.load(open(sys.argv[1]));print(json.dumps({v:n for n,v in k.items()}))' "$SECRETS/hindsight-keys.json")"
      # the web page (port 9999) uses Amadeus' own key, so it shows the banks Amadeus remembers into
      uikey="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["amadeus"])' "$SECRETS/hindsight-keys.json")"
    else keys='{"<key>":"amadeus"}'; uikey='<key>'; fi
    run docker run -d \
      --name "$HINDSIGHT_CONTAINER" \
      --restart unless-stopped \
      --network host \
      -v "$HINDSIGHT_VOLUME:/home/hindsight/.pg0" \
      -v "$ext:/opt/amadeus-ext:ro" \
      -e PYTHONPATH=/opt/amadeus-ext \
      -e HINDSIGHT_API_TENANT_EXTENSION=amadeus_ext.keymap:KeyMapTenantExtension \
      -e HINDSIGHT_API_TENANT_KEYS="$keys" \
      -e HINDSIGHT_API_HOST=127.0.0.1 \
      -e HINDSIGHT_CP_HOSTNAME=127.0.0.1 \
      -e HINDSIGHT_CP_DATAPLANE_API_KEY="$uikey" \
      -e HINDSIGHT_API_WORKER_ID="$HINDSIGHT_WORKER_ID" \
      -e HINDSIGHT_API_LLM_PROVIDER=ollama \
      -e HINDSIGHT_API_LLM_BASE_URL="$OLLAMA_URL" \
      -e HINDSIGHT_API_LLM_MODEL="$HINDSIGHT_LLM_MODEL" \
      -e HINDSIGHT_API_EMBEDDINGS_PROVIDER=local \
      "$HINDSIGHT_IMAGE"
  fi

  [[ "$MODE" == install ]] || { info "health check skipped in $MODE mode"; check_hindsight_health; return; }
  info "waiting for Hindsight API (first start downloads embedding models)"
  if wait_http "http://127.0.0.1:$HINDSIGHT_API_PORT/health" 300; then
    ok "Hindsight API http://127.0.0.1:$HINDSIGHT_API_PORT  ·  UI http://127.0.0.1:$HINDSIGHT_UI_PORT"
  else
    err "Hindsight did not become healthy. Check: docker logs $HINDSIGHT_CONTAINER"
  fi
}
check_hindsight_health() {
  curl -fsS -o /dev/null --max-time 3 "http://127.0.0.1:$HINDSIGHT_API_PORT/health" 2>/dev/null \
    && ok "Hindsight API healthy on :$HINDSIGHT_API_PORT" \
    || warn "Hindsight API not answering on :$HINDSIGHT_API_PORT"
}

# ---------------------------------------------------------------- Obsidian integration
# put_file DEST MODE < content : write DEST only when content differs (sets CHANGED=1).
CHANGED=0
put_file() {
  local dest="$1" mode="$2" tmp; tmp="$(mktemp)"; cat >"$tmp"
  if [[ -f "$dest" ]] && cmp -s "$tmp" "$dest"; then rm -f "$tmp"; ok "up to date: ${dest/#$HOME/\~}"; return 0; fi
  CHANGED=1
  if [[ "$MODE" != install ]]; then rm -f "$tmp"; printf '  %s→ would write:%s %s\n' "$C_DIM" "$C_OFF" "$dest"; return 0; fi
  mkdir -p "$(dirname "$dest")"
  [[ -e "$dest" ]] && chmod u+w "$dest"
  install -m "$mode" "$tmp" "$dest"; rm -f "$tmp"
  info "wrote ${dest/#$HOME/\~}"
}

phase_obsidian() {
  [[ -n "$OBSIDIAN_VAULT" ]] || return 0  # optional: connected under Settings → Connectors
  head_ "Obsidian vault"
  local vault="${OBSIDIAN_VAULT%/}"
  [[ -d "$vault" ]] || { err "vault not found: $vault"; return; }
  [[ -d "$vault/.obsidian" ]] || warn "$vault has no .obsidian folder; is it really an Obsidian vault?"
  local src="$SCRIPT_DIR/obsidian"
  local q_vault; q_vault="$(printf %q "$vault")"

  # 1. Amadeus's folder in the vault: your ToDo.md and Notes.md, and its own notes (_Amadeus).
  [[ -d "$vault/Amadeus/_Amadeus" ]] || run mkdir -p "$vault/Amadeus/_Amadeus"
  if [[ -f "$vault/Amadeus/README.md" ]]; then ok "vault folder Amadeus/ present"
  else put_file "$vault/Amadeus/README.md" 644 <"$src/vault-README.md"; fi
  # tell Amadeus where the vault is (its config; other settings in it are kept)
  if [[ "$MODE" == install ]]; then
    python3 - "$vault/Amadeus" <<'PYC'
import json, os, sys
p = os.path.expanduser("~/.config/amadeus-core/config.json")
c = json.load(open(p)) if os.path.exists(p) else {}
if c.get("vault_dir") != sys.argv[1]:
    c["vault_dir"] = sys.argv[1]
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(c, open(p, "w"), indent=2)
    print("  · Amadeus config: vault_dir =", sys.argv[1])
PYC
  fi

  # 2. Hourly vault snapshots, so any change can be undone.
  local snap; snap="$(<"$src/amadeus-vault-snapshot")"
  printf '%s\n' "${snap//\"@VAULT@\"/"$q_vault"}" | put_file "$HOME/.local/bin/amadeus-vault-snapshot" 755
  local udir="$HOME/.config/systemd/user" u
  for u in amadeus-vault-snapshot.service amadeus-vault-snapshot.timer; do
    put_file "$udir/$u" 644 <"$src/systemd/$u"
  done
  (( CHANGED )) && run systemctl --user daemon-reload
  if systemctl --user is-enabled --quiet amadeus-vault-snapshot.timer 2>/dev/null; then ok "amadeus-vault-snapshot.timer enabled"
  else run systemctl --user enable --now amadeus-vault-snapshot.timer; fi
}

# ---------------------------------------------------------------- setup questions (first run, or --setup)
env_set() {  # env_set KEY VALUE: write KEY="VALUE" into amadeus.env, keeping everything else in it
  local f="$ENV_FILE"
  mkdir -p "$(dirname "$f")"
  [[ -f "$f" ]] || cp "$SCRIPT_DIR/amadeus.env.example" "$f"
  python3 - "$f" "$1" "$2" <<'PYS'
import re, shlex, sys
f, k, v = sys.argv[1:]
lines = open(f).read().splitlines()
new = f"{k}={shlex.quote(v)}"
for i, l in enumerate(lines):
    if re.match(rf"\s*#?\s*{k}=", l):
        lines[i] = new
        break
else:
    lines.append(new)
open(f, "w").write("\n".join(lines) + "\n")
PYS
}
ask() {  # ask "question" default -> the answer (Enter = default)
  local reply; read -r -p "  ? $1 [${2}] " reply; printf '%s' "${reply:-$2}"
}
phase_setup() {
  [[ "$MODE" == install && -t 0 && "$ASSUME_YES" != 1 ]] || return 0
  [[ "$SETUP" == 1 || ! -f "$ENV_FILE" ]] || return 0
  head_ "Setup (Enter keeps the suggestion; the answers go into amadeus.env)"
  # (Obsidian is optional and connected later, under Settings → Connectors)
  # 1. where Claude Code projects live: its own folder, never in the vault
  local cur; cur="$(python3 -c 'import json,os,sys; print(json.load(open(sys.argv[1])).get("projects_dir","") if os.path.exists(sys.argv[1]) else "")' "$HOME/.config/amadeus-core/config.json" 2>/dev/null || true)"
  info "Claude Code projects get their own folder, so a work run never sees your notes."
  local pr; pr="$(ask "Folder for projects" "${AMADEUS_PROJECTS:-${cur:-$HOME/Amadeus/Projects}}")"
  pr="${pr/#\~/$HOME}"; AMADEUS_PROJECTS="$pr"; env_set AMADEUS_PROJECTS "$pr"; ok "projects: $pr"
  # 2. mail through Thunderbird
  local m="n"; have thunderbird && m="y"
  info "Mail is optional. You can connect accounts directly later (Mail → + Add account), or read them through Thunderbird."
  m="$(ask "Set up Thunderbird for that? (y/n)" "$m")"
  [[ "$m" =~ ^[Yy] ]] && AMADEUS_MAIL=1 || AMADEUS_MAIL=0; env_set AMADEUS_MAIL "$AMADEUS_MAIL"
  # 3. voice
  local s; s="$(ask "Talk to it: speech recognition and wake word, about 1 GB? (y/n)" "y")"
  [[ "$s" =~ ^[Yy] ]] && AMADEUS_VOICE=1 || AMADEUS_VOICE=0; env_set AMADEUS_VOICE "$AMADEUS_VOICE"
}

# ---------------------------------------------------------------- the projects folder and the guard for work runs
phase_work() {
  head_ "Work runs: the projects folder and its guard"
  local cfg="$HOME/.config/amadeus-core/config.json"
  if [[ -n "$AMADEUS_PROJECTS" && "$MODE" == install ]]; then  # tell Amadeus (other settings in its config are kept)
    python3 - "$cfg" "$AMADEUS_PROJECTS" <<'PYC'
import json, os, sys
p, d = sys.argv[1], os.path.realpath(os.path.expanduser(sys.argv[2]))
c = json.load(open(p)) if os.path.exists(p) else {}
if c.get("projects_dir") != d:
    c["projects_dir"] = d
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(c, open(p, "w"), indent=2)
    print("  · Amadeus config: projects_dir =", d)
PYC
  fi
  local out where vault  # the effective projects folder and the vault, one per line (paths may have spaces)
  mapfile -t out < <(python3 - "$cfg" "$AMADEUS_PROJECTS" <<'PYW'
import json, os, sys
c = json.load(open(sys.argv[1])) if os.path.exists(sys.argv[1]) else {}
older = os.path.expanduser("~/Documents/Obsidian Vault/Amadeus")  # older installs have it there without saying so
v = c.get("vault_dir") or (older if os.path.isdir(older) else os.path.expanduser("~/.local/share/amadeus/notes"))
print(os.path.realpath(os.path.expanduser(sys.argv[2] or c.get("projects_dir") or os.path.join(v, "Projects"))))
print(os.path.dirname(v.rstrip("/")) if os.path.isdir(v) else "")
PYW
  )
  where="${out[0]}"; vault="${out[1]:-}"
  case "$where/" in "${vault:-/nonexistent}"/*) warn "projects are inside your vault ($where): run ./install.sh --setup to give them their own folder";; *) ok "projects folder: $where";; esac
  if [[ "$MODE" == install ]]; then python3 "$SCRIPT_DIR/core/amadeus_core/workguard.py" "$where" "$vault"
  else python3 "$SCRIPT_DIR/core/amadeus_core/workguard.py" "$where" "$vault" --check; fi
  have claude && ok "Claude Code installed" || info "Claude Code isn't installed: work runs stay off until you install it and log in once (claude)"
}

# ---------------------------------------------------------------- update (amadeus update)
phase_update() {
  head_ "Update"
  if [[ ! -d "$SCRIPT_DIR/.git" ]]; then
    [[ -w "$SCRIPT_DIR" ]] && warn "not a git checkout: download the new version yourself, then run ./install.sh" \
      || info "installed as a package: updates come through your system's package manager"
    return
  fi
  if [[ -n "$(git -C "$SCRIPT_DIR" status --porcelain --untracked-files=no)" ]]; then
    warn "you changed files in the repository, so nothing is pulled (git status shows them); installing the version you have"
    return
  fi
  local before; before="$(git -C "$SCRIPT_DIR" rev-parse --short HEAD)"
  # on main (or a release already): the newest release; anywhere else you're developing, so just pull
  local branch tag; branch="$(git -C "$SCRIPT_DIR" branch --show-current)"
  run git -C "$SCRIPT_DIR" fetch --quiet --tags origin || { warn "git fetch failed; installing the version you have"; return; }
  tag="$(git -C "$SCRIPT_DIR" tag --list 'v*' --sort=-v:refname | head -1)"
  if [[ -n "$tag" && ( "$branch" == main || -z "$branch" ) ]]; then
    run git -C "$SCRIPT_DIR" checkout --quiet --detach "$tag" || { warn "couldn't switch to $tag; installing the version you have"; return; }
  else
    run git -C "$SCRIPT_DIR" pull --ff-only --quiet || { warn "git pull failed; installing the version you have"; return; }
  fi
  local after; after="$(git -C "$SCRIPT_DIR" rev-parse --short HEAD)"
  if [[ "$before" == "$after" ]]; then ok "already the latest version ($after)"
  else ok "updated $before → $after"; git -C "$SCRIPT_DIR" log --oneline "$before..$after" | sed 's/^/    /' | head -20
    [[ "$MODE" == install ]] && exec "$SCRIPT_DIR/install.sh" --updated -y "${PASSTHRU[@]}"  # the new installer does the rest
  fi
}

# ---------------------------------------------------------------- voice (optional)
phase_voice() {
  head_ "Voice: speech recognition and the wake word"
  if [[ "$AMADEUS_VOICE" != 1 ]]; then info "off (AMADEUS_VOICE=1 in amadeus.env, or ./install.sh --setup)"; return; fi
  have python3 || { err "python3 is missing"; return; }
  have parec || warn "parec (pulseaudio-utils) is missing: everything works except the wake word, which stays off"
  if [[ -x "$VOICE/venv-lite/bin/python" ]] && "$VOICE/venv-lite/bin/python" -c "import faster_whisper, vosk, soundfile" 2>/dev/null; then
    ok "speech recognition installed"
  else
    run python3 -m venv "$VOICE/venv-lite"
    run "$VOICE/venv-lite/bin/pip" install --quiet faster-whisper soundfile vosk
  fi
  if [[ -d "$VOICE/models/$VOSK_MODEL" ]]; then ok "wake-word model installed"
  else
    run mkdir -p "$VOICE/models"
    run curl -fsSL -o "$VOICE/models/$VOSK_MODEL.zip" "https://alphacephei.com/vosk/models/$VOSK_MODEL.zip"
    run python3 -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$VOICE/models/$VOSK_MODEL.zip" "$VOICE/models"
    run rm -f "$VOICE/models/$VOSK_MODEL.zip"
  fi
  # speech normalization (NeMo): numbers, money, units and dates said as words. It needs pynini, which needs Python 3.12,
  # so it gets its own environment through uv (uv downloads that Python once). About 900 MB; optional.
  if [[ -x "$VOICE/venv-tn/bin/python" ]] && "$VOICE/venv-tn/bin/python" -c "import nemo_text_processing" 2>/dev/null; then
    ok "speech normalization (NeMo) installed"
  elif have uv; then
    run uv venv -q --python 3.12 "$VOICE/venv-tn"
    run uv pip install -q --python "$VOICE/venv-tn/bin/python" nemo_text_processing
  else
    info "speech normalization skipped: install uv to have numbers and units said as words (Amadeus' own rules cover times and dates)"
  fi
  info "Whisper downloads its model on first use. Voices for reading aloud: Settings → Voice."
}

# ---------------------------------------------------------------- the assistant itself
phase_app() {
  head_ "The assistant: services, window, tray"
  if ! pkg-config --exists webkit2gtk-4.1 gtk+-3.0 2>/dev/null; then
    err "GTK 3 with WebKit2GTK 4.1 is missing, or its development files (./install.sh offers to install them; see also docs/INSTALL.md, What you need)"; return
  fi
  if [[ "$MODE" != install ]]; then "$SCRIPT_DIR/core/deploy/install.sh" --dry-run | sed 's/^/  /'; return; fi
  "$SCRIPT_DIR/core/deploy/install.sh" | sed 's/^/  /'
  if [[ "$UPDATE" != 0 ]]; then
    run systemctl --user restart amadeus-core amadeus-desktop
    systemctl --user is-enabled --quiet amadeus-voice 2>/dev/null && run systemctl --user restart amadeus-voice
    systemctl --user is-enabled --quiet amadeus-wake 2>/dev/null && run systemctl --user restart amadeus-wake
  fi
}

# ---------------------------------------------------------------- mail (optional)
phase_mail() {
  head_ "Mail: the Thunderbird bridge"
  if [[ "$AMADEUS_MAIL" != 1 ]]; then info "off (AMADEUS_MAIL=1 in amadeus.env, or ./install.sh --setup)"; return; fi
  have thunderbird || warn "Thunderbird isn't installed: install it from your distribution (not Flatpak) and add your accounts there"
  if [[ "$MODE" != install ]]; then info "would register the bridge and build the add-on"; return; fi
  "$SCRIPT_DIR/core/thunderbird/install.sh" | sed 's/^/  /'
}

# ---------------------------------------------------------------- main
printf '%sAmadeus installer%s  (mode: %s%s)\n' "$C_HEAD" "$C_OFF" "$MODE" "${ONLY:+, only: $ONLY}"
PASSTHRU=(); [[ -n "$ONLY" ]] && PASSTHRU=(--only "$ONLY")
[[ "$UPDATE" == 1 ]] && phase_update
# the setup questions and most steps below need Python, so it comes first
if ! have python3 && [[ "$MODE" != check && -n "$PKG" ]]; then
  case "$PKG" in pacman) py=python ;; *) py=python3 ;; esac
  if offer "$py" "the $PKG package"; then pkg_install "$py"; fi
fi
phase_deps    # what's missing comes first: installing Docker can restart this script
phase_setup
phase_prereqs
# one step failing doesn't stop the others; the summary lists everything that went wrong
step() { want "$1" || return 0; "phase_$1" || true; }
step ollama
step secrets
step presidio
step hindsight
step obsidian
step work
step voice
step app
step mail

head_ "Summary"
if (( ERRORS > 0 )); then
  err "$ERRORS problem(s), $WARNINGS warning(s). See the messages above."
  if [[ "$MODE" == check && -n "$PKG" && -t 0 ]] && confirm "Install what's missing now?"; then exec "$0"; fi
  [[ "$MODE" != install ]] || info "Fix these, then run ./install.sh again: what already worked is skipped. If you see \"no such host\", this PC's DNS isn't working for Ollama and Docker (check /etc/resolv.conf)."
  exit 1
fi
ok "Done with $WARNINGS warning(s)."
[[ "$MODE" == install ]] || exit 0
have amadeus || warn "$HOME/.local/bin isn't in your PATH yet: open a new terminal, or run $HOME/.local/bin/amadeus"
printf '\nOpen it with: %samadeus%s   ·   update later with: %samadeus update%s\n' "$C_HEAD" "$C_OFF" "$C_HEAD" "$C_OFF"
left=()
[[ "$AMADEUS_MAIL" == 1 ]] && left+=("Mail: in Thunderbird, Add-ons and Themes → gear icon → Install Add-on From File… → ~/.local/share/amadeus/amadeus-bridge.xpi")
! have claude && left+=("Work runs (optional): install Claude Code and log in once by running: claude")
left+=("Phone (optional): see docs/INSTALL.md, The phone app")
printf '\nStill to do by hand:\n'; printf '  · %s\n' "${left[@]}"
