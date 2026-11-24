#!/usr/bin/env bash
# Run every test and summarize. Each file is a standalone script that prints
# its own checks and ends with ALL PASS, so this reports per file rather than
# collecting assertions.
#
# fldigi must be running: four of these drive the real application through a
# pseudo-terminal and read the screen back, which needs a modem to talk to.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${HERE}/.." && pwd)"
cd "$PROJECT_DIR" || exit 1

# **`pyte` before fldigi**, because without it fourteen files fail at the
# import and are reported FAILED exactly as a real break would be -- which
# cost a session in 2026-11 before anyone read the traceback. It lives in the
# `cyberdeck-dev` environment; see environment.yml, which also pins python to
# the 3.13 the deck runs rather than whatever the system has.
if ! python3 -c "import pyte" 2>/dev/null; then
  cat >&2 <<'MSG'
pyte is missing, so the pseudo-terminal tests cannot run. They would be
reported as FAILED rather than skipped, which is worse than stopping here.

    conda env create -f environment.yml     # first time
    conda activate cyberdeck-dev
MSG
  exit 1
fi

# The python the tests will actually use, printed rather than assumed: the
# deck runs 3.13 and the system python here is further ahead, so a suite that
# passes says less than it looks like it does when they differ.
echo "python $(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')  (the deck runs 3.13.5)"

if ! python3 -c "
import xmlrpc.client, sys
try:
    xmlrpc.client.ServerProxy('http://127.0.0.1:7362/').fldigi.name_version()
except Exception:
    sys.exit(1)
" 2>/dev/null; then
  echo "fldigi is not answering on 127.0.0.1:7362 — start it with tools/dev-fldigi.sh" >&2
  exit 1
fi

failed=0
total=0
for t in tests/test_*.py; do
  out="$(python3 "$t" 2>&1)"
  checks=$(grep -c 'PASS' <<<"$out")
  if grep -q 'ALL PASS' <<<"$out"; then
    printf '  %-28s ALL PASS (%d)\n' "$t" "$((checks - 1))"
    total=$((total + checks - 1))
  else
    printf '  %-28s FAILED\n' "$t"
    grep -iE '^  FAIL' <<<"$out" | sed 's/^/      /'
    failed=$((failed + 1))
  fi
done

echo
if (( failed )); then
  echo "${failed} file(s) failed"
  exit 1
fi
echo "${total} checks, all passing"
