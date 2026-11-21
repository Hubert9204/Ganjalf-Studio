#!/usr/bin/env bash
# Ganjalf Studio launcher for Linux, macOS and WSL.
#
# - keeps data and the Python environment in its own folder, apart from any Unsloth Studio
# - installs from this checkout on first run, then just starts the server
# - picks the first free port from 8890 and opens the browser once the server answers
#
# Run it as your normal user, not as root: the folder picker only offers folders under
# the home of the user Studio runs as.
#
# Optional environment:
#   GANJALF_HOME=<dir>      data and environment folder (default: ~/.ganjalf-studio)
#   GANJALF_PORT=<port>     first port to try (default: 8890)
#   GANJALF_NO_BROWSER=1    do not open the browser
#   UNSLOTH_NO_TORCH=1      first run only: skip PyTorch (GGUF-only, much smaller install)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UNSLOTH_STUDIO_HOME="${GANJALF_HOME:-$HOME/.ganjalf-studio}"
FIRST_PORT="${GANJALF_PORT:-8890}"
STUDIO_BIN="$UNSLOTH_STUDIO_HOME/unsloth_studio/bin/unsloth"

# True when something already accepts connections on the port.
port_in_use() {
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

find_free_port() {
  local port
  for port in $(seq "$FIRST_PORT" $((FIRST_PORT + 50))); do
    if ! port_in_use "$port"; then
      echo "$port"
      return 0
    fi
  done
  return 1
}

open_browser() {
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$1" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then
    open "$1" >/dev/null 2>&1 || true
  else
    echo "Open $1 in your browser."
  fi
}

if [ "$(id -u)" = "0" ]; then
  echo "Warning: running as root. Studio will only offer folders under $HOME, and its tools can write anywhere." >&2
fi

# Written only after install.sh succeeds: a half-finished install already has the binary.
INSTALLED_MARKER="$UNSLOTH_STUDIO_HOME/.ganjalf-installed"
if [ ! -f "$INSTALLED_MARKER" ]; then
  echo "First run: installing into $UNSLOTH_STUDIO_HOME (this can take a while)..."
  (cd "$REPO_DIR" && UNSLOTH_SKIP_AUTOSTART=1 bash ./install.sh --local)
  touch "$INSTALLED_MARKER"
fi
if [ ! -x "$STUDIO_BIN" ]; then
  STUDIO_BIN="$(command -v unsloth || true)"
fi
if [ -z "$STUDIO_BIN" ]; then
  echo "Could not find the 'unsloth' command after installing. Check the installer output above." >&2
  exit 1
fi

PORT="$(find_free_port)" || { echo "No free port between $FIRST_PORT and $((FIRST_PORT + 50))." >&2; exit 1; }
URL="http://127.0.0.1:$PORT"

echo "Starting Ganjalf Studio on $URL"
"$STUDIO_BIN" studio -p "$PORT" &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' INT TERM EXIT

# Up to two minutes for the server to start answering.
for _ in $(seq 1 240); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "The server stopped before it was ready." >&2
    exit 1
  fi
  if port_in_use "$PORT"; then
    break
  fi
  sleep 0.5
done

if [ -z "${GANJALF_NO_BROWSER:-}" ]; then
  open_browser "$URL"
fi
wait "$SERVER_PID"
