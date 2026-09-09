#!/usr/bin/env bash
# Starts both demo servers (Python on :5001, Node on :5002) so the shared dashboard
# can switch between them live. Requires each has a .env with API_URL set - see
# python/.env.example and node/.env.example.
#
# Usage: ./run.sh

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for lang in python node; do
  if [ ! -f "$DIR/$lang/.env" ]; then
    echo "Warning: $lang/.env not found. Copy $lang/.env.example to $lang/.env and set API_URL first." >&2
  fi
done

pids=()
cleaned_up=0
cleanup() {
  [ "$cleaned_up" -eq 1 ] && return
  cleaned_up=1
  echo ""
  echo "Stopping demo servers..."
  for pid in "${pids[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
}
# Trap INT/TERM explicitly (Ctrl+C, or a plain `kill`) as well as EXIT - cleanup is
# idempotent so it's safe if both fire for the same shutdown.
trap cleanup EXIT INT TERM

# Both app.py and server.js resolve their own directory from __file__/__dirname, so
# they can be launched with absolute paths with no `cd` needed. That matters here:
# backgrounding a subshell (e.g. `(cd dir && cmd) &`) makes $! the subshell's PID,
# not the server's, and separately breaks this script's own signal-interrupted
# `wait` below - backgrounding the plain command directly avoids both problems.
python3 "$DIR/python/app.py" &
pids+=($!)

node "$DIR/node/server.js" &
pids+=($!)

sleep 1
echo ""
echo "Both backends are up:"
echo "  Python: http://localhost:5001"
echo "  Node:   http://localhost:5002"
echo ""
echo "Open either URL - the dashboard has a Backend selector to switch between them live."
echo "Press Ctrl+C to stop both."
echo ""

wait
