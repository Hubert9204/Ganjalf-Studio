#!/usr/bin/env bash
# Ganjalf Studio launcher for Linux, macOS and WSL.
#
# - keeps data and the Python environment in its own folder, apart from any Unsloth Studio
# - installs from this checkout on first run, and again after a `git pull` (the frontend
#   is rebuilt by the installer, so a new revision needs it)
# - on first run also copies the coding-agent skill and switches on the skill-creator
# - picks the first free port from 8890 and opens the browser once the server answers
#
# Run it as your normal user, not as root: the folder picker only offers folders under
# the home of the user Studio runs as.
#
# Optional environment:
#   GANJALF_HOME=<dir>      data and environment folder (default: ~/.ganjalf-studio)
#   GANJALF_PORT=<port>     first port to try (default: 8890)
#   GANJALF_NO_BROWSER=1    do not open the browser
#   GANJALF_AUTO_SKILLS=0   do not let the backend load the skill that fits each request
#   UNSLOTH_NO_TORCH=1      first run only: skip PyTorch (GGUF-only, much smaller install)
#   ROLLING_INSTRUCTION_PIN_GROUPS=<n>  user messages kept in the prompt when the context
#                           window rolls (default here: 2; 0 turns it off, as upstream does)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UNSLOTH_STUDIO_HOME="${GANJALF_HOME:-$HOME/.ganjalf-studio}"
FIRST_PORT="${GANJALF_PORT:-8890}"
STUDIO_BIN="$UNSLOTH_STUDIO_HOME/unsloth_studio/bin/unsloth"

# On long agent runs the oldest turns fall out of the window and small local models lose the
# task. This keeps the last substantive user instructions (capped by size) in the prompt.
export ROLLING_INSTRUCTION_PIN_GROUPS="${ROLLING_INSTRUCTION_PIN_GROUPS:-2}"

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

# Ganjalf defaults, applied once: copies the skills in studio/ganjalf_skills into the skills
# folder (a skill you already have under that name is left alone) and switches on the bundled
# skill-creator, so a model can write the skills a task needs. Delete the marker to repeat it.
seed_defaults() {
  local marker="$UNSLOTH_STUDIO_HOME/.ganjalf-defaults-seeded"
  [ -f "$marker" ] && return 0
  local skills_home="${UNSLOTH_STUDIO_SKILLS_HOME:-$HOME/.agents/skills}"
  local source_dir="$REPO_DIR/studio/ganjalf_skills"
  local dir name
  mkdir -p "$UNSLOTH_STUDIO_HOME" "$skills_home"
  if [ -d "$source_dir" ]; then
    for dir in "$source_dir"/*/; do
      [ -d "$dir" ] || continue
      name="$(basename "$dir")"
      [ -e "$skills_home/$name" ] || cp -r "$dir" "$skills_home/$name"
    done
  fi
  if [ ! -e "$UNSLOTH_STUDIO_HOME/skill-overrides.json" ]; then
    printf '{"skill-creator":true}\n' > "$UNSLOTH_STUDIO_HOME/skill-overrides.json"
  fi
  touch "$marker"
}

if [ "$(id -u)" = "0" ]; then
  echo "Warning: running as root. Studio will only offer folders under $HOME, and its tools can write anywhere." >&2
fi

# The marker holds the revision that was installed, and is written only after install.sh
# succeeds: a half-finished install already has the binary. A different revision (after a
# `git pull`) or an empty marker from an older launcher installs again.
INSTALLED_MARKER="$UNSLOTH_STUDIO_HOME/.ganjalf-installed"
REPO_REV="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
if [ "$(cat "$INSTALLED_MARKER" 2>/dev/null || true)" != "$REPO_REV" ]; then
  echo "Installing into $UNSLOTH_STUDIO_HOME (first run or new version; this can take a while)..."
  (cd "$REPO_DIR" && UNSLOTH_SKIP_AUTOSTART=1 bash ./install.sh --local)
  mkdir -p "$UNSLOTH_STUDIO_HOME"
  echo "$REPO_REV" > "$INSTALLED_MARKER"
fi
seed_defaults
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
