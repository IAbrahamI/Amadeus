#!/usr/bin/env bash
# Does Hindsight run on a Mac without Docker, sealed off? Only for trying it on a build machine, on a throwaway home.
set -uo pipefail
ROOT="$PWD"
W="$(mktemp -d)"; export HOME="$W"
V="$W/venv"
python3 -m venv "$V"
t=$SECONDS; "$V/bin/pip" install --quiet "hindsight-api${HINDSIGHT_VERSION:+==$HINDSIGHT_VERSION}" 2>&1 | tail -3; echo "pip: $((SECONDS-t))s, size $(du -sh "$V" | cut -f1)"
ls "$V/bin" | grep -i hind
"$V/bin/pip" list 2>/dev/null | grep -iE '^(hindsight|torch|sentence|pg0)' 
KEY=testkey123
cat > "$W/env.sh" <<EOF
export PYTHONPATH="$ROOT/core/hindsight_ext"
export HINDSIGHT_API_TENANT_EXTENSION=amadeus_ext.keymap:KeyMapTenantExtension
export HINDSIGHT_API_TENANT_KEYS='{"$KEY":"amadeus"}'
export HINDSIGHT_API_HOST=127.0.0.1
export HINDSIGHT_API_PORT=8888
export HINDSIGHT_API_WORKER_ID=amadeus-hindsight
export HINDSIGHT_API_LLM_PROVIDER=ollama
export HINDSIGHT_API_LLM_BASE_URL=http://127.0.0.1:11434
export HINDSIGHT_API_LLM_MODEL=${MODEL:-qwen3.5:0.8b}
export HINDSIGHT_API_EMBEDDINGS_PROVIDER=local
EOF
. "$W/env.sh"
curl -fsSL -o "$W/o.zip" https://ollama.com/download/Ollama-darwin.zip && ditto -x -k "$W/o.zip" "$W/o" 
"$W/o/Ollama.app/Contents/Resources/ollama" serve >"$W/ollama.log" 2>&1 &
sleep 5; t=$SECONDS; curl -s -X POST http://127.0.0.1:11434/api/pull -d "{\"model\":\"${MODEL:-qwen3.5:0.8b}\",\"stream\":false}" | cut -c1-80; echo "model pull: $((SECONDS-t))s"
wait_up() { for _ in $(seq "$1"); do curl -sf -m 3 http://127.0.0.1:8888/health >/dev/null && return 0; sleep 2; done; return 1; }
api() { curl -sS -m "${3:-180}" -H "authorization: Bearer $KEY" -H 'content-type: application/json' "http://127.0.0.1:8888/v1/default/banks/amadeus-private$1" -d "$2"; echo; }
t=$SECONDS
"$V/bin/hindsight-api" >"$W/first.log" 2>&1 &
PID=$!
wait_up 300 && echo "first start: healthy after $((SECONDS-t))s" || { echo "first start FAILED"; tail -40 "$W/first.log"; exit 1; }
du -sh "$W" | cut -f1; du -sh "$W/.pg0" 2>/dev/null | cut -f1; ls -a "$W" | tr '\n' ' '; echo
t=$SECONDS; api /memories '{"items":[{"content":"The user has a blue bicycle called Rosie."}]}' | cut -c1-300; echo "saving: $((SECONDS-t))s"
sleep 20
t=$SECONDS; api /memories/recall '{"query":"what bicycle does the user have","max_tokens":500}' | cut -c1-500; echo "finding: $((SECONDS-t))s"
kill "$PID"; sleep 8; pgrep -fl postgres | head -3 | cut -c1-100
REAL="$(cd "$W" && pwd -P)"
NET='(deny network*)
(allow network* (local ip "localhost:*"))
(allow network* (remote ip "localhost:*"))
(allow network* (local unix-socket))
(allow network* (remote unix-socket))'
FILES="(deny file-write*)
(allow file-write* (subpath \"$REAL\") (subpath \"/private/tmp\") (subpath \"/private/var/folders\") (literal \"/dev/null\") (literal \"/dev/dtracehelper\") (literal \"/dev/tty\"))"
printf '(version 1)\n(allow default)\n' > "$W/none.sb"
printf '(version 1)\n(allow default)\n%s\n' "$NET" > "$W/net.sb"
printf '(version 1)\n(allow default)\n%s\n' "$FILES" > "$W/files.sb"
printf '(version 1)\n(allow default)\n%s\n%s\n' "$NET" "$FILES" > "$W/seal.sb"
pg_stop() { pkill -f 'bin/postgres' 2>/dev/null; sleep 3; }
for name in none net files seal; do
  echo "--- $name"; pg_stop
  t=$SECONDS
  HF_HUB_OFFLINE=1 sandbox-exec -f "$W/$name.sb" "$V/bin/hindsight-api" >"$W/$name.log" 2>&1 &
  PID=$!
  if wait_up 45; then echo "healthy after $((SECONDS-t))s"; t=$SECONDS; api /memories/recall '{"query":"what bicycle does the user have","max_tokens":500}' | cut -c1-160; echo "finding: $((SECONDS-t))s"
    [ "$name" = seal ] && { t=$SECONDS; api /memories '{"items":[{"content":"The user likes green tea."}]}' | cut -c1-120; echo "saving: $((SECONDS-t))s"; ps -axo rss=,command= | grep -E '[h]indsight-api|bin/[p]ostgres -' | head -3 | cut -c1-70; }
  else echo "FAILED"; grep -E 'pg0|rror|denied' "$W/$name.log" | tail -5 | cut -c1-200; fi
  kill "$PID" 2>/dev/null; sleep 6
done
find "$W/.pg0" -name '*.log' | head -3; find "$W/.pg0" -maxdepth 2 | head -12 | cut -c60-
for f in $(find "$W/.pg0" -name '*.log' | head -2); do tail -6 "$f" | cut -c1-170; done
log show --last 5m --predicate 'eventMessage CONTAINS "deny" AND eventMessage CONTAINS "postgres"' --style compact 2>/dev/null | tail -8 | cut -c1-170
"$V/bin/python" -c "import pg0,inspect;print(pg0.__file__)" 2>&1 | tail -1 | cut -c60-
pkill -f 'ollama serve' || true
echo done
