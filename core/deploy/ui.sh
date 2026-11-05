# What the installer looks like: colours, steps, messages, menus and quiet progress. Sourced by install.sh.
# Colours and menus only on a real terminal; piped or in a script it stays plain text and never waits for a key.
if [[ -t 1 && -z "${NO_COLOR:-}" && "${TERM:-dumb}" != dumb ]]; then
  C_OK=$'\e[38;5;78m'; C_WARN=$'\e[38;5;214m'; C_ERR=$'\e[38;5;203m'; C_HEAD=$'\e[38;5;80m'; C_BOLD=$'\e[1m'; C_DIM=$'\e[2m'; C_OFF=$'\e[0m'
  C_PICK=$'\e[1;38;5;16;48;5;80m'; FANCY=1
else
  C_OK=""; C_WARN=""; C_ERR=""; C_HEAD=""; C_BOLD=""; C_DIM=""; C_OFF=""; C_PICK=""; FANCY=0
fi
ERRORS=0; WARNINGS=0; PROBLEMS=(); NOTES=(); STEP_LABEL=""; VERBOSE="${VERBOSE:-0}"
ui_width() { local w="${COLUMNS:-}"; [[ -n "$w" ]] || w="$(tput cols 2>/dev/null || echo 80)"; (( w > 84 )) && w=84; echo "$w"; }

# a message wrapped to the terminal, with the lines after the first one lined up under the text
say() {  # say "mark with colours" "text"
  local width first=1 line; width=$(( $(ui_width) - 6 ))
  while IFS= read -r line; do
    if (( first )); then printf '  %s %s\n' "$1" "$line"; first=0; else printf '    %s\n' "$line"; fi
  done < <(printf '%s\n' "$2" | fold -s -w "$width")
}
banner() {
  printf '\n  %s%s◆ AMADEUS%s  %syour own private assistant%s\n' "$C_BOLD" "$C_HEAD" "$C_OFF" "$C_DIM" "$C_OFF"
  [[ -z "${1:-}" ]] || printf '  %s%s%s\n' "$C_DIM" "$1" "$C_OFF"
}
head_() {
  printf '\n  %s%s%s%s%s\n' "$C_BOLD" "$C_HEAD" "${STEP_LABEL:+$STEP_LABEL  }" "$*" "$C_OFF"
  STEP_LABEL=""
}
ok()   { say "${C_OK}✓${C_OFF}" "$*"; }
info() { say "${C_DIM}·${C_OFF}" "${C_DIM}$*${C_OFF}"; }
warn() { WARNINGS=$((WARNINGS+1)); NOTES+=("$*"); say "${C_WARN}${C_BOLD}!${C_OFF}" "${C_WARN}$*${C_OFF}"; }
err()  { ERRORS=$((ERRORS+1)); PROBLEMS+=("$*"); say "${C_ERR}${C_BOLD}✗${C_OFF}" "${C_ERR}${C_BOLD}$*${C_OFF}"; }
die()  { err "$*"; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
box() {  # box colour title line...: stands out without shouting
  local colour="$1" title="$2" line; shift 2
  printf '\n  %s┃%s %s%s%s%s\n' "$colour" "$C_OFF" "$C_BOLD" "$colour" "$title" "$C_OFF"
  for line in "$@"; do
    while IFS= read -r part; do printf '  %s┃%s %s\n' "$colour" "$C_OFF" "$part"; done < <(printf '%s\n' "$line" | fold -s -w $(( $(ui_width) - 6 )))
  done
}

# ---------- quiet progress: long commands show one line; everything they print goes to the log ----------
LOG="${AMADEUS_LOG:-$HOME/.local/share/amadeus/install.log}"
label_of() {
  case "$*" in
    "docker build"*) echo "Building the privacy filter (a few minutes)" ;;
    "docker network"*) echo "Creating the private network" ;;
    "docker create"*) echo "Creating a privacy filter container" ;;
    "docker run"*) echo "Downloading and starting the memory (a few minutes)" ;;
    "docker start"*) echo "Starting the memory" ;;
    "ollama create"*) echo "Setting up the model" ;;
    *"apt-get update"*) echo "Reading the package lists" ;;
    *"apt-get install"*|*"pacman -S"*|*"dnf install"*) echo "Installing packages" ;;
    *"systemctl enable"*) echo "Starting the service" ;;
    *usermod*) echo "Adding you to the docker group" ;;
    *"-m venv"*) echo "Preparing voice" ;;
    *"pip"*) echo "Installing speech recognition (a few minutes)" ;;
    "curl"*) echo "Downloading" ;;
    *deploy/install.sh*) echo "Installing the app (the first time also builds it, a few minutes)" ;;
    *thunderbird/install.sh*) echo "Setting up the Thunderbird bridge" ;;
    *) echo "$1 ${2:-}" ;;
  esac
}
# run CMD...: execute unless in check/dry-run mode
run() {
  if [[ "$MODE" != install ]]; then
    say "${C_DIM}→${C_OFF}" "${C_DIM}would run: $*${C_OFF}"
    return 0
  fi
  local rc=0
  # what shows its own progress, or everything with --verbose
  if [[ "$VERBOSE" == 1 || "$1 ${2:-}" == "ollama pull" ]]; then
    say "${C_DIM}→${C_OFF}" "${C_DIM}$*${C_OFF}"
    "$@" || rc=$?
    (( rc == 0 )) || err "That didn't work: $*"
    return "$rc"
  fi
  local label; label="$(label_of "$@")"
  [[ "$1" != sudo ]] || sudo -v  # asked here, in the open, not hidden behind the progress line
  mkdir -p "$(dirname "$LOG")"
  printf '\n--- %s: %s\n' "$(date '+%F %T')" "$*" >>"$LOG"
  "$@" >>"$LOG" 2>&1 </dev/null &
  local pid=$! n=0 start=$SECONDS frames='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
  if (( FANCY )); then
    while kill -0 "$pid" 2>/dev/null; do
      printf '\r  %s%s%s %s %s%ss%s\e[K' "$C_HEAD" "${frames:n++%10:1}" "$C_OFF" "$label" "$C_DIM" "$((SECONDS-start))" "$C_OFF"
      sleep 0.12
    done
    printf '\r\e[K'
  else
    printf '  · %s\n' "$label"
  fi
  wait "$pid" || rc=$?
  if (( rc == 0 )); then
    ok "$label" | sed -E 's/ \((a few minutes|the first time[^)]*)\)//'
  else
    err "That didn't work: $label"
    tail -n 12 "$LOG" | cut -c1-$(( $(ui_width) - 6 )) | sed "s/^/    ${C_DIM}/; s/\$/${C_OFF}/"
    info "The full output is in $LOG"
  fi
  return "$rc"
}

# ---------- questions ----------
# confirm "question" [yes]: yes or no with the arrow keys, y / n, or Enter for the highlighted one. Without a terminal: no.
confirm() {
  local question="$1" pick=1; [[ "${2:-no}" == yes ]] && pick=0  # 0 = Yes, 1 = No
  [[ "$ASSUME_YES" == 1 ]] && return 0
  [[ -t 0 ]] || return 1
  local draw key rest
  draw() {
    local y=" Yes " n=" No "
    if (( pick == 0 )); then y="${C_PICK} Yes ${C_OFF}"; else n="${C_PICK} No ${C_OFF}"; fi
    if (( FANCY )); then printf '\r  %s?%s %s%s%s  %s %s\e[K' "$C_HEAD" "$C_OFF" "$C_BOLD" "$question" "$C_OFF" "$y" "$n"; fi
  }
  if (( ! FANCY )); then
    local reply; read -r -p "  ? $question [$([[ $pick == 0 ]] && echo Y/n || echo y/N)] " reply || return 1
    [[ -z "$reply" ]] && return "$pick"
    [[ "$reply" =~ ^[Yy] ]]; return
  fi
  while true; do
    draw
    IFS= read -rsn1 key || { pick=1; break; }
    if [[ "$key" == $'\e' ]]; then
      IFS= read -rsn2 -t 0.05 rest || true
      case "$rest" in '[C'|'[B'|'OC'|'OB') pick=1 ;; '[D'|'[A'|'OD'|'OA') pick=0 ;; esac
    else
      case "$key" in
        ""|$'\n'|$'\r') break ;;
        y|Y) pick=0; break ;;
        n|N) pick=1; break ;;
        h) pick=0 ;; l) pick=1 ;;
        $'\t') pick=$((1-pick)) ;;
      esac
    fi
  done
  printf '\r\e[K  %s?%s %s  %s%s%s\n' "$C_HEAD" "$C_OFF" "$question" "$C_HEAD" "$([[ $pick == 0 ]] && echo Yes || echo No)" "$C_OFF"
  return "$pick"
}
# ask "question" default: a line of text, Enter keeps the suggestion
ask() {
  local reply
  read -r -p "  ${C_HEAD}?${C_OFF} ${C_BOLD}$1${C_OFF} ${C_DIM}($2)${C_OFF} " reply || true
  printf '%s' "${reply:-$2}"
}
