#!/usr/bin/env bash
# Start fldigi headless for development, and leave it running.
#
# fldigi has no headless mode: it is an FLTK application, so it runs against a
# virtual X server that is never displayed (platform_design.md §4.1). It also
# crashes on a genuinely empty configuration directory — an assertion failure
# during first-run setup, reproduced twice — so a working config is seeded from
# the developer's own install rather than generated (§14).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${HERE}/.." && pwd)"
CONFIG_DIR="${PROJECT_DIR}/fldigi-config"
DISPLAY_NUM="${CYBERDECK_DISPLAY:-:99}"
PORT="${CYBERDECK_XMLRPC_PORT:-7362}"

stop_all() {
  pkill -f "fldigi --config-dir ${CONFIG_DIR}" 2>/dev/null || true
  pkill -f "Xvfb ${DISPLAY_NUM}" 2>/dev/null || true
}

# "stop" is not just tidiness: an open capture device reports zero input
# channels rather than an error, so audio enumeration (configure_fldigi.py
# --list-audio / --auto-audio) sees the radio as capture-less while fldigi
# holds it.
if [[ "${1:-}" == "stop" ]]; then
  stop_all
  sleep 1
  echo "fldigi and Xvfb ${DISPLAY_NUM} stopped."
  exit 0
fi

if [[ ! -d "$CONFIG_DIR" ]]; then
  if [[ -d "$HOME/.fldigi" ]]; then
    echo "Seeding ${CONFIG_DIR} from ~/.fldigi (fldigi will not start on an empty one)."
    cp -a "$HOME/.fldigi" "$CONFIG_DIR"
  else
    echo "No ~/.fldigi to seed from. Run fldigi once on a desktop first." >&2
    exit 1
  fi
fi

stop_all
sleep 1

Xvfb "$DISPLAY_NUM" -screen 0 1024x768x16 >/dev/null 2>&1 &
sleep 2
DISPLAY="$DISPLAY_NUM" fldigi --config-dir "$CONFIG_DIR" \
  --xmlrpc-server-address 127.0.0.1 --xmlrpc-server-port "$PORT" \
  > "${CONFIG_DIR}/fldigi.log" 2>&1 &

echo "fldigi starting on ${DISPLAY_NUM}, XML-RPC on 127.0.0.1:${PORT}"
for i in $(seq 1 30); do
  if python3 -c "
import sys,xmlrpc.client
try: xmlrpc.client.ServerProxy('http://127.0.0.1:${PORT}/').fldigi.name_version()
except Exception: sys.exit(1)
" 2>/dev/null; then
    echo "ready after ${i}s"; exit 0
  fi
  sleep 1
done
echo "fldigi did not answer XML-RPC within 30s; see ${CONFIG_DIR}/fldigi.log" >&2
exit 1
