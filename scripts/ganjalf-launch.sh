#!/usr/bin/env bash
# Ganjalf Studio launcher for Linux, macOS and WSL.
#
# - keeps data and the Python environment in its own folder, apart from any Unsloth Studio
# - installs from this checkout on first run, and again after a `git pull` (the frontend
#   is rebuilt by the installer, so a new revision needs it)
# - keeps the skills in studio/ganjalf_skills in your skills folder: copied when missing,
#   updated when you have not edited them, left alone when you have
# - switches on the bundled skill-creator once, so a model can write the skills it needs
# - picks the first free port from 8888 and opens the browser once the server answers;
#   LAN access (Settings) serves the network on that same port
#
# Started as root through sudo / sudo -i / doas / pkexec, it keeps working for the user who
# asked: that user's home, Studio data, skills and downloaded models (never /root), and files
# it creates there are handed back to that user, so a later normal launch still works.
#
# Optional environment:
#   GANJALF_HOME=<dir>      data and environment folder (default: ~/.ganjalf-studio)
#   GANJALF_PORT=<port>     first port to try (default: 8888)
#   GANJALF_HOST=<address>  address to listen on (default: 127.0.0.1, this computer only).
#                           0.0.0.0 lets other devices on the network (a phone) open the same
#                           server at http://<this computer's IP>:<port>. Every device must use
#                           one server: chats running in another server cannot be followed live.
#   GANJALF_NO_BROWSER=1    do not open the browser
#   GANJALF_AGENT_THINKING_BUDGET=<n>  tokens each agent round may think when the Thinking
#                           Budget is on Auto (default 6144; 0 leaves it to the model)
#   GANJALF_AUTO_SKILLS=0   do not let the backend load the skill that fits each request
#   GANJALF_PAGE_CHECK=0    do not install or offer check_page (headless Chromium for web pages)
#   UNSLOTH_NO_TORCH=1      first run only: skip PyTorch (GGUF-only, much smaller install)
#   ROLLING_INSTRUCTION_PIN_GROUPS=<n>  user messages kept in the prompt when the context
#                           window rolls (default here: 2; 0 turns it off, as upstream does)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Root started for someone else (sudo -i sets HOME=/root): find that user.
REAL_USER=""
if [ "$(id -u)" = "0" ]; then
  if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
    REAL_USER="$SUDO_USER"
  elif [ -n "${DOAS_USER:-}" ] && [ "${DOAS_USER}" != "root" ]; then
    REAL_USER="$DOAS_USER"
  elif [ -n "${PKEXEC_UID:-}" ] && [ "${PKEXEC_UID}" != "0" ]; then
    REAL_USER="$(id -nu "$PKEXEC_UID" 2>/dev/null || true)"
  else
    # sudo -i then su, or a root shell: the owner of this checkout, if it is not root.
    owner="$(stat -c %U "$REPO_DIR" 2>/dev/null || true)"
    [ -n "$owner" ] && [ "$owner" != "root" ] && [ "$owner" != "UNKNOWN" ] && REAL_USER="$owner"
  fi
fi
if [ -n "$REAL_USER" ]; then
  REAL_HOME="$(getent passwd "$REAL_USER" 2>/dev/null | cut -d: -f6 || true)"
  if [ -n "$REAL_HOME" ] && [ -d "$REAL_HOME" ]; then
    REAL_UID="$(id -u "$REAL_USER")"
    REAL_GID="$(id -g "$REAL_USER")"
    export HOME="$REAL_HOME"
    export USER="$REAL_USER" LOGNAME="$REAL_USER"
    # Root's own XDG folders would send caches and models back under /root.
    for var in XDG_CONFIG_HOME XDG_CACHE_HOME XDG_DATA_HOME XDG_STATE_HOME HF_HOME \
               HF_HUB_CACHE HUGGINGFACE_HUB_CACHE TRANSFORMERS_CACHE UV_CACHE_DIR; do
      case "${!var:-}" in /root|/root/*) unset "$var" ;; esac
    done
    [ -d "/run/user/$REAL_UID" ] && export XDG_RUNTIME_DIR="/run/user/$REAL_UID"
    # git refuses another user's checkout when run as root ("dubious ownership").
    export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0="$REPO_DIR"
  else
    REAL_USER=""
  fi
fi

# Files root created in the user's folders go back to the user (only root-owned ones).
give_back_to_user() {
  [ -n "$REAL_USER" ] || return 0
  local dir
  for dir in "$@"; do
    [ -e "$dir" ] && chown -R --from=0:0 "$REAL_UID:$REAL_GID" "$dir" 2>/dev/null || true
  done
}
user_folders() {
  give_back_to_user "$UNSLOTH_STUDIO_HOME" "$HOME/.cache" "$HOME/.agents" "$HOME/.unsloth" \
    "$HOME/.local/share/unsloth" "$REPO_DIR"
}

export UNSLOTH_STUDIO_HOME="${GANJALF_HOME:-$HOME/.ganjalf-studio}"
FIRST_PORT="${GANJALF_PORT:-8888}"
HOST="${GANJALF_HOST:-127.0.0.1}"
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
  # As root the browser belongs to the user's desktop session, so open it as that user.
  if [ -n "$REAL_USER" ] && command -v xdg-open >/dev/null 2>&1 && command -v runuser >/dev/null 2>&1; then
    runuser -u "$REAL_USER" -- env DISPLAY="${DISPLAY:-:0}" XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-}" \
      WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}" \
      DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$REAL_UID/bus" \
      xdg-open "$1" >/dev/null 2>&1 || echo "Open $1 in your browser."
    return
  fi
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$1" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then
    open "$1" >/dev/null 2>&1 || true
  else
    echo "Open $1 in your browser."
  fi
}

# Hash of a folder's files (names and contents), the same on Linux and macOS.
dir_hash() {
  local hasher="sha256sum"
  command -v sha256sum >/dev/null 2>&1 || hasher="shasum -a 256"
  (cd "$1" && find . -type f | LC_ALL=C sort | tr '\n' '\0' | xargs -0 $hasher | $hasher | cut -d' ' -f1)
}
# Hashes of earlier shipped versions of a skill, so an untouched copy made before the stamps
# existed is still recognised and updated.
legacy_skill_hashes() {
  case "$1" in
    coding-agent) echo "a29910d48871b9e93f0341bdf74705f04fbac1634e9c795bb30d27856e82ac3e" ;;
  esac
}
seed_skills() {
  local skills_home="${UNSLOTH_STUDIO_SKILLS_HOME:-$HOME/.agents/skills}"
  local source_dir="$REPO_DIR/studio/ganjalf_skills"
  local dir name dest stamp shipped installed known
  [ -d "$source_dir" ] || return 0
  mkdir -p "$UNSLOTH_STUDIO_HOME" "$skills_home"
  for dir in "$source_dir"/*/; do
    [ -d "$dir" ] || continue
    name="$(basename "$dir")"
    dest="$skills_home/$name"
    stamp="$UNSLOTH_STUDIO_HOME/.seeded-$name"
    shipped="$(dir_hash "$dir")"
    if [ ! -e "$dest" ]; then
      cp -r "$dir" "$dest"
      echo "$shipped" > "$stamp"
      echo "Installed the $name skill."
      continue
    fi
    installed="$(dir_hash "$dest")"
    if [ "$installed" = "$shipped" ]; then
      echo "$shipped" > "$stamp"
      continue
    fi
    known="$(cat "$stamp" 2>/dev/null || true) $(legacy_skill_hashes "$name")"
    case " $known " in
      *" $installed "*)
        rm -rf "$dest"
        cp -r "$dir" "$dest"
        echo "$shipped" > "$stamp"
        echo "Updated the $name skill to the version in this checkout."
        ;;
      *)
        echo "The $name skill was edited here, so it was left as it is."
        ;;
    esac
  done
}

# skill-creator is switched on once, and only if there is no overrides file yet: after that the
# toggles in the Skills window decide.
seed_overrides() {
  local file="$UNSLOTH_STUDIO_HOME/skill-overrides.json"
  local marker="$UNSLOTH_STUDIO_HOME/.ganjalf-defaults-seeded"
  mkdir -p "$UNSLOTH_STUDIO_HOME"
  if [ ! -e "$file" ] && [ ! -f "$marker" ]; then
    printf '{"skill-creator":true}\n' > "$file"
  fi
  touch "$marker"
}

seed_defaults() {
  seed_skills
  seed_overrides
}

if [ -n "$REAL_USER" ]; then
  echo "Running as root for $REAL_USER: home, data and models stay in $HOME. The agent's tools run as root and can write anywhere." >&2
elif [ "$(id -u)" = "0" ]; then
  echo "Warning: running as root with no other user found, so data and models go under $HOME." >&2
fi

# The marker records what the installation was built from and is written only after install.sh
# succeeds: a half-finished install already has the binary. That is the frontend source tree and
# pyproject.toml; the backend is installed editable, so changes to it, to skills or to this
# script need no reinstall. A different value (after a `git pull` that touched the frontend)
# or an empty marker from an older launcher installs again.
INSTALLED_MARKER="$UNSLOTH_STUDIO_HOME/.ganjalf-installed"
REPO_REV="$(git -C "$REPO_DIR" rev-parse HEAD:studio/frontend HEAD:pyproject.toml 2>/dev/null | tr '\n' ' ' || true)"
[ -n "${REPO_REV// /}" ] || REPO_REV="unknown"
if [ "$(cat "$INSTALLED_MARKER" 2>/dev/null || true)" != "$REPO_REV" ]; then
  echo "Installing into $UNSLOTH_STUDIO_HOME (first run, or the frontend or dependencies changed; this can take a while)..."
  (cd "$REPO_DIR" && UNSLOTH_SKIP_AUTOSTART=1 bash ./install.sh --local)
  mkdir -p "$UNSLOTH_STUDIO_HOME"
  echo "$REPO_REV" > "$INSTALLED_MARKER"
fi
seed_defaults
user_folders
# check_page (headless Chromium for the model's web pages and games). A reinstall can rebuild
# Studio's Python environment and drop Playwright, so it is checked on every launch and set up
# again at most once per revision; GANJALF_PAGE_CHECK=0 skips it.
PAGE_CHECK_MARKER="$UNSLOTH_STUDIO_HOME/.ganjalf-page-check-tried"
STUDIO_PY="$UNSLOTH_STUDIO_HOME/unsloth_studio/bin/python"
page_check_ready() {
  [ -x "$STUDIO_PY" ] || return 1
  "$STUDIO_PY" - >/dev/null 2>&1 <<'PYEOF'
import os, shutil, sys
from playwright.sync_api import sync_playwright
with sync_playwright() as playwright:
    bundled = playwright.chromium.executable_path
system = any(shutil.which(n) for n in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"))
sys.exit(0 if (bundled and os.path.isfile(bundled)) or system else 1)
PYEOF
}
if [ "${GANJALF_PAGE_CHECK:-1}" != "0" ] && ! page_check_ready; then
  if [ "$(cat "$PAGE_CHECK_MARKER" 2>/dev/null || true)" != "$REPO_REV" ]; then
    echo "$REPO_REV" > "$PAGE_CHECK_MARKER"
    (cd "$REPO_DIR" && bash scripts/ganjalf-install-page-check.sh) \
      || echo "check_page could not be set up; Studio works without it. See scripts/ganjalf-install-page-check.sh." >&2
  else
    echo "Note: check_page is not available, so the model cannot run the web pages and games it writes." >&2
    echo "      Run: bash scripts/ganjalf-install-page-check.sh  (then restart Studio)" >&2
  fi
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
if [ "$HOST" != "127.0.0.1" ]; then
  LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  echo "Other devices on the network: http://${LAN_IP:-THIS-PC-IP}:$PORT"
fi
"$STUDIO_BIN" studio -H "$HOST" -p "$PORT" &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true; user_folders' INT TERM EXIT

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
