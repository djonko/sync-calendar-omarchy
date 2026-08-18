#!/usr/bin/env bash
# One-command install for the Calendar Sync Clock plugin.
#
# Installs/enables promaa.clock and removes the built-in omarchy.clock it
# replaces, so the bar shows a single clock + calendar. Safe to re-run:
# every step is idempotent.

set -euo pipefail

ID="promaa.clock"
OLD_ID="omarchy.clock"
REPO_URL="${1:-https://github.com/promaaa/sync-calendar-omarchy.git}"
SHELL_CONFIG="$HOME/.config/omarchy/shell.json"

err() { echo "install: $*" >&2; exit 1; }

command -v omarchy >/dev/null 2>&1 || err "omarchy CLI not found on PATH"
command -v jq >/dev/null 2>&1 || err "jq is required; install it with: omarchy pkg add jq"

installed() {
  omarchy plugin list --json | jq -e --arg id "$1" 'any(.[]; .id == $id)' >/dev/null 2>&1
}

enabled() {
  omarchy plugin list --json | jq -e --arg id "$1" 'any(.[]; .id == $id and .enabled == true)' >/dev/null 2>&1
}

# 1. Install and enable the plugin (idempotent).
if installed "$ID"; then
  enabled "$ID" || omarchy plugin enable "$ID"
else
  omarchy plugin add "$REPO_URL" --enable --yes
fi

# 2. Remove the built-in clock/calendar this replaces.
enabled "$OLD_ID" && omarchy plugin disable "$OLD_ID"

# 3. Point the bar's center anchor at the new widget (a fresh bar centers on
#    the old clock by default).
if [[ -f "$SHELL_CONFIG" ]] && jq -e --arg id "$OLD_ID" '.bar.centerAnchor == $id' "$SHELL_CONFIG" >/dev/null 2>&1; then
  tmp="${SHELL_CONFIG}.tmp.$$"
  jq --arg id "$ID" '.bar.centerAnchor = $id' "$SHELL_CONFIG" > "$tmp"
  mv "$tmp" "$SHELL_CONFIG"
fi

echo "Done: $ID installed and set to replace $OLD_ID."
