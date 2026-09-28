#!/usr/bin/env bash
# The whole suite: the rules and the schema under node, the helper under python.
set -uo pipefail

cd "$(dirname "$0")" || exit 1

status=0

if command -v node >/dev/null 2>&1; then
  echo "== core (node)"
  node --test tests/*.test.mjs || status=1
else
  echo "node not found: cannot run tests/*.test.mjs" >&2
  status=1
fi

echo
echo "== state helper (python)"
python3 -B tests/test_state_helper.py || status=1

echo
if [ "$status" -eq 0 ]; then
  echo "all tests passed"
else
  echo "TESTS FAILED" >&2
fi
exit "$status"
