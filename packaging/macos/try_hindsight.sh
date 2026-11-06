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
cat > "$W/seal.sb" <<EOF
(version 1)
(allow default)
(deny network*)
(allow network* (local ip "localhost:*"))
(allow network* (remote ip "localhost:*"))
(allow network* (local unix-socket))
(allow network* (remote unix-socket))
(deny file-write*)
(allow file-write* (subpath "$(cd "$W" && pwd -P)") (subpath "/private/tmp") (subpath "/private/var/folders") (literal "/dev/null") (literal "/dev/dtracehelper"))
EOF
echo "--- sealed"
t=$SECONDS
HF_HUB_OFFLINE=1 sandbox-exec -f "$W/seal.sb" "$V/bin/hindsight-api" >"$W/sealed.log" 2>&1 &
PID=$!
wait_up 150 && echo "sealed start: healthy after $((SECONDS-t))s" || { echo "sealed start FAILED"; tail -40 "$W/sealed.log"; exit 1; }
t=$SECONDS; api /memories/recall '{"query":"what bicycle does the user have","max_tokens":500}' | cut -c1-400; echo "sealed finding: $((SECONDS-t))s"
t=$SECONDS; api /memories '{"items":[{"content":"The user likes green tea."}]}' | cut -c1-200; echo "sealed saving: $((SECONDS-t))s"
ps -o rss=,command= -p "$PID" | cut -c1-70; ps -axo rss=,command= | grep -E '[p]ostgres' | head -2 | cut -c1-70
for code in "import socket; socket.create_connection(('1.1.1.1',53),timeout=4)" "import urllib.request; urllib.request.urlopen('http://example.com',timeout=6)" "open('$W/../x','w').write('x')"; do
  sandbox-exec -f "$W/seal.sb" "$V/bin/python" -c "$code" >/dev/null 2>&1 && echo "BAD not blocked: ${code:0:40}" || echo "blocked: ${code:0:40}"
done
kill "$PID"; pkill -f 'ollama serve' || true
tail -5 "$W/sealed.log" | cut -c1-160
echo done
