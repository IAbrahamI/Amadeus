#!/usr/bin/env bash
# Amadeus installer, part 1 (the services): Ollama (local LLM), private keys, Presidio (privacy filter),
# Hindsight (memory) and the Obsidian vault with the guard for work runs.
# Part 2 is core/deploy/install.sh (the assistant itself, its window and voice).
#
# Idempotent: every step checks the current state first and skips what is already done.
# It never deletes data. Anything it cannot fix safely is reported with the manual fix.
#
# Usage:
#   ./install.sh              install / repair everything
#   ./install.sh --check      read-only: prerequisites and status, changes nothing
#   ./install.sh --dry-run    print what would be done, changes nothing
#   ./install.sh --only ollama|secrets|presidio|hindsight|obsidian
#   ./install.sh --help
#
# Settings (override with environment variables, or put them in ./amadeus.env):
#   OLLAMA_MODEL           base model to pull                  (default: qwen3.5:9b)
#   OLLAMA_CTX_VARIANT     name of the larger-context variant  (default: qwen3.5-9b-48k, what Amadeus uses)
#   OLLAMA_NUM_CTX         context length for that variant     (default: 49152)
#   OLLAMA_URL             Ollama endpoint                     (default: http://127.0.0.1:11434)
#   HINDSIGHT_IMAGE        container image                     (default: ghcr.io/vectorize-io/hindsight:latest)
#   HINDSIGHT_CONTAINER    container name                      (default: hindsight)
#   HINDSIGHT_VOLUME       named volume for its data           (default: hindsight-data)
#   HINDSIGHT_LLM_MODEL    Ollama model Hindsight uses         (default: $OLLAMA_CTX_VARIANT)
#   HINDSIGHT_WORKER_ID    stable worker id                    (default: amadeus-hindsight)
#   OBSIDIAN_VAULT         absolute path of your Obsidian vault (unset: Obsidian step is skipped)
#   ASSUME_YES=1           do not prompt; non-interactive onboarding

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
[[ -f "$SCRIPT_DIR/amadeus.env" ]] && source "$SCRIPT_DIR/amadeus.env"

OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3.5:9b}"
OLLAMA_CTX_VARIANT="${OLLAMA_CTX_VARIANT:-qwen3.5-9b-48k}"
OLLAMA_NUM_CTX="${OLLAMA_NUM_CTX:-49152}"
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
HINDSIGHT_IMAGE="${HINDSIGHT_IMAGE:-ghcr.io/vectorize-io/hindsight:latest}"
HINDSIGHT_CONTAINER="${HINDSIGHT_CONTAINER:-hindsight}"
HINDSIGHT_VOLUME="${HINDSIGHT_VOLUME:-hindsight-data}"
HINDSIGHT_LLM_MODEL="${HINDSIGHT_LLM_MODEL:-$OLLAMA_CTX_VARIANT}"
HINDSIGHT_WORKER_ID="${HINDSIGHT_WORKER_ID:-amadeus-hindsight}"
HINDSIGHT_API_PORT=8888
HINDSIGHT_UI_PORT=9999
OBSIDIAN_VAULT="${OBSIDIAN_VAULT:-}"
DATA="$HOME/.local/share/amadeus"          # everything private lives here, never in the repository
SECRETS="$DATA/secrets"
OBSIDIAN_PLUGIN_VERSION="${OBSIDIAN_PLUGIN_VERSION:-0.5.0}"
ASSUME_YES="${ASSUME_YES:-0}"

MODE=install   # install | check | dry-run
ONLY=""

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
  "$@"
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

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)   MODE=check ;;
    --dry-run) MODE=dry-run ;;
    --only)    ONLY="${2:-}"; shift ;;
    -y|--yes)  ASSUME_YES=1 ;;
    -h|--help) usage ;;
    *) die "Unknown option: $1 (see --help)" ;;
  esac
  shift
done
want() { [[ -z "$ONLY" || "$ONLY" == "$1" ]]; }

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
    have python3 && ok "python3 (vault guard hook)" || err "python3 is missing; the vault guard hook needs it."
    have zstd && ok "zstd (vault snapshots)" || err "zstd is missing; vault snapshots use tar --zstd."
    if have bwrap && have socat; then ok "bubblewrap + socat (Claude Code sandbox)"
    else err "bubblewrap and socat are required for the Claude Code sandbox that locks the vault (package names: bubblewrap, socat)."; fi
  fi

  if (( ERRORS > 0 )); then
    [[ "$MODE" == install ]] && die "Fix the prerequisites above, then run this script again."
    warn "Prerequisites are incomplete; later phases may show as missing."
  fi
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

  local models; models="$(ollama list 2>/dev/null | awk 'NR>1 {print $1}')"
  if grep -qx "${OLLAMA_MODEL}:latest\|${OLLAMA_MODEL}" <<<"$models"; then
    ok "model $OLLAMA_MODEL present"
  else
    info "pulling $OLLAMA_MODEL (several GB, this takes a while)"
    run ollama pull "$OLLAMA_MODEL"
  fi

  if grep -qx "${OLLAMA_CTX_VARIANT}:latest\|${OLLAMA_CTX_VARIANT}" <<<"$models"; then
    ok "context variant $OLLAMA_CTX_VARIANT present"
  else
    local mf; mf="$(mktemp)"
    printf 'FROM %s\nPARAMETER num_ctx %s\n' "$OLLAMA_MODEL" "$OLLAMA_NUM_CTX" >"$mf"
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
    run docker build -t amadeus/presidio-analyzer:en-de "$SCRIPT_DIR/core/privacy/presidio"; fi
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
    else keys='{"<key>":"amadeus"}'; fi
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
  head_ "Obsidian vault and the guard for work runs"
  if [[ -z "$OBSIDIAN_VAULT" ]]; then
    info "OBSIDIAN_VAULT is not set; skipping. Set it in amadeus.env to enable this step."
    return
  fi
  local vault="${OBSIDIAN_VAULT%/}"
  [[ -d "$vault" ]] || { err "vault not found: $vault"; return; }
  [[ -d "$vault/.obsidian" ]] || warn "$vault has no .obsidian folder; is it really an Obsidian vault?"
  local guard_dir="$HOME/.local/share/amadeus/work-guard"
  local src="$SCRIPT_DIR/obsidian"
  local q_vault; q_vault="$(printf %q "$vault")"
  local py_vault; py_vault="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$vault")"

  # 1. Amadeus's folder in the vault: its own notes (_Amadeus) and one folder per work project (Projects).
  local d
  for d in _Amadeus Projects; do
    [[ -d "$vault/Amadeus/$d" ]] || run mkdir -p "$vault/Amadeus/$d"
  done
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

  # 2. Guard for the work runs (one Claude Code run per task, core/amadeus_core/work.py): a PreToolUse hook, deny
  #    rules and Claude Code's sandbox, in a read-only folder. Runs may use only Amadeus/Projects/ in the vault.
  [[ "$MODE" == install && -d "$guard_dir" ]] && chmod u+w "$guard_dir"
  local guard_py; guard_py="$(<"$src/vault-guard.py")"
  printf '%s\n' "${guard_py//\"@VAULT@\"/"$py_vault"}" | put_file "$guard_dir/vault-guard.py" 555
  python3 - "$vault" "$guard_dir" <<'PYS' | put_file "$guard_dir/settings.json" 444
import json, os, shlex, sys
vault, guard = sys.argv[1:3]
deny = []
for name in sorted(os.listdir(vault)):
    if name in ("Amadeus", ".trash"):
        continue
    path = os.path.join(vault, name)
    deny.append(f"Edit(/{path}/**)" if os.path.isdir(path) else f"Edit(/{path})")
deny.append(f"Edit(/{guard}/**)")
projects = os.path.join(vault, "Amadeus", "Projects")
print(json.dumps({
  "permissions": {"deny": deny},
  "hooks": {"PreToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit|Read|Grep|Glob|LS",
    "hooks": [{"type": "command", "command": shlex.quote(os.path.join(guard, "vault-guard.py"))}]}]},
  "sandbox": {"enabled": True, "allowUnsandboxedCommands": False, "failIfUnavailable": True,
    "filesystem": {"allowWrite": [projects], "allowRead": [projects],
      "denyRead": [vault, "~/.ssh", "~/.gnupg", "~/.aws", "~/.ollama", "~/.thunderbird", "~/.config/amadeus-core",
                   "~/.local/share/amadeus/core", "~/.local/share/amadeus/secrets", "~/.local/share/amadeus/backup",
                   "~/.local/share/amadeus/work-guard", "~/.claude/.credentials.json"]},
    "network": {"allowedDomains": []}}}, indent=2))
PYS
  [[ "$MODE" == install ]] && chmod a-w "$guard_dir"

  # 3. Hourly vault snapshots, so any change can be undone.
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

# ---------------------------------------------------------------- main
printf '%sAmadeus installer%s  (mode: %s%s)\n' "$C_HEAD" "$C_OFF" "$MODE" "${ONLY:+, only: $ONLY}"
phase_prereqs
want ollama    && phase_ollama
want secrets   && phase_secrets
want presidio  && phase_presidio
want hindsight && phase_hindsight
want obsidian  && phase_obsidian

head_ "Summary"
if (( ERRORS > 0 )); then
  err "$ERRORS problem(s), $WARNINGS warning(s). See the messages above."
  exit 1
fi
ok "Done with $WARNINGS warning(s)."
cat <<EOF

Next (see docs/INSTALL.md):
  Amadeus        core/deploy/install.sh   (the assistant itself, its window, voice; then run: amadeus)
  Mail           core/thunderbird/install.sh, then add the add-on in Thunderbird (optional)
  Work runs      log in once with \`claude\` (Claude Code); Amadeus starts one run per approved task (optional)
EOF
