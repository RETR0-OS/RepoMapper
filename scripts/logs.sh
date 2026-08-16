#!/usr/bin/env bash
# Follow the Repository Map logs that VS Code writes while the extension runs.
#
#   scripts/logs.sh           follow both logs
#   scripts/logs.sh service   follow the bundled Python service only
#   scripts/logs.sh client    follow the extension host (TypeScript side) only
#
# VS Code writes a file for each output channel. This finds the newest window and
# follows it, so no log path must be typed. Stop with Ctrl+C.
#
# Set CODE_LOG_ROOT for VS Code Insiders or a portable install.

set -u

LOG_ROOT="${CODE_LOG_ROOT:-$HOME/AppData/Roaming/Code/logs}"
CHANNEL="hack-hydra.hydra-repository-observability"
MODE="${1:-both}"

if [ ! -d "$LOG_ROOT" ]; then
  echo "VS Code log directory not found: $LOG_ROOT" >&2
  echo "Set CODE_LOG_ROOT to the correct path." >&2
  exit 1
fi

service_dir() {
  # Strip any trailing slash so the path joins the same way in every shell.
  ls -td "$LOG_ROOT"/*/window*/exthost/"$CHANNEL" 2>/dev/null | head -1 | sed 's:/*$::'
}

echo "Waiting for the Repository Map service channel…"
for _ in $(seq 1 60); do
  DIR="$(service_dir)"
  [ -n "$DIR" ] && [ -f "$DIR/Repository Map Service.log" ] && break
  sleep 1
done

DIR="$(service_dir)"
if [ -z "$DIR" ] || [ ! -f "$DIR/Repository Map Service.log" ]; then
  echo "No Repository Map channel yet." >&2
  echo "Open the Repository Map view in VS Code once, then run this again." >&2
  exit 1
fi

SERVICE_LOG="$DIR/Repository Map Service.log"
CLIENT_LOG="$(dirname "$DIR")/exthost.log"

echo "service  $SERVICE_LOG"
echo "client   $CLIENT_LOG"
echo "---"

FOLLOW_PIDS=()
cleanup() {
  for pid in "${FOLLOW_PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

case "$MODE" in
  service) tail -n 40 -f "$SERVICE_LOG" ;;
  client)  tail -n 40 -f "$CLIENT_LOG" | grep -i --line-buffered "hydra\|repository map\|error" ;;
  both)
    tail -n 40 -f "$SERVICE_LOG" | sed -u 's/^/[service] /' &
    FOLLOW_PIDS+=("$!")
    tail -n 40 -f "$CLIENT_LOG" | grep -i --line-buffered "hydra\|repository map" | sed -u 's/^/[client]  /' &
    FOLLOW_PIDS+=("$!")
    wait
    ;;
  *) echo "Usage: scripts/logs.sh [service|client|both]" >&2; exit 1 ;;
esac
