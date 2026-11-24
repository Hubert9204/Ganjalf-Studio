#!/usr/bin/env bash
# Installs what the check_page tool needs: Playwright in Studio's Python environment and a
# headless Chromium. check_page lets the model run the web pages and browser games it writes on
# the server (no window: a virtual display) and see their errors and a screenshot.
#
# Run it once from the Ganjalf Studio folder, then restart Studio:
#   bash scripts/ganjalf-install-page-check.sh
#
# ganjalf-launch.sh runs it on its own the first time (GANJALF_PAGE_CHECK=0 skips that).
# A Chrome or Chromium already installed on the system is used instead of downloading one.
#
# Optional environment:
#   GANJALF_HOME=<dir>            Studio's data folder (default: ~/.ganjalf-studio)
#   GANJALF_PAGE_CHECK_DEPS=1     also install Chromium's system libraries (needs root or sudo)
set -euo pipefail

STUDIO_HOME="${UNSLOTH_STUDIO_HOME:-${GANJALF_HOME:-$HOME/.ganjalf-studio}}"
PY="${GANJALF_PYTHON:-$STUDIO_HOME/unsloth_studio/bin/python}"
if [ ! -x "$PY" ]; then
  echo "Studio's Python was not found at $PY. Start Studio once with scripts/ganjalf-launch.sh first." >&2
  exit 1
fi

if ! "$PY" -c "import playwright.sync_api" >/dev/null 2>&1; then
  echo "Installing Playwright into Studio's environment..."
  "$PY" -m pip install --quiet "playwright>=1.45"
fi

system_browser=""
for name in chromium chromium-browser google-chrome google-chrome-stable; do
  if command -v "$name" >/dev/null 2>&1; then
    system_browser="$(command -v "$name")"
    break
  fi
done

if [ -n "$system_browser" ] && [ -z "${GANJALF_PAGE_CHECK_DOWNLOAD:-}" ]; then
  echo "Using the browser already installed at $system_browser."
else
  echo "Downloading a headless Chromium (about 150 MB)..."
  "$PY" -m playwright install chromium
fi

if [ "${GANJALF_PAGE_CHECK_DEPS:-0}" = "1" ]; then
  if [ "$(id -u)" = "0" ]; then
    "$PY" -m playwright install-deps chromium
  else
    sudo "$PY" -m playwright install-deps chromium
  fi
fi

# A quick run, so a missing system library shows up now and not in the middle of a chat.
if GANJALF_SYSTEM_BROWSER="$system_browser" "$PY" - <<'EOF'
import os
from playwright.sync_api import sync_playwright
with sync_playwright() as playwright:
    bundled = playwright.chromium.executable_path
    executable = None if bundled and os.path.isfile(bundled) else (os.environ.get("GANJALF_SYSTEM_BROWSER") or None)
    args = ["--no-sandbox"] if os.geteuid() == 0 else []
    browser = playwright.chromium.launch(headless = True, executable_path = executable, args = args)
    page = browser.new_page()
    page.set_content("<title>ok</title>")
    assert page.title() == "ok"
    browser.close()
EOF
then
  echo "check_page is ready. Restart Studio to offer it to the model."
else
  echo "Chromium did not start. Install its system libraries with:" >&2
  echo "  GANJALF_PAGE_CHECK_DEPS=1 bash scripts/ganjalf-install-page-check.sh" >&2
  exit 1
fi
