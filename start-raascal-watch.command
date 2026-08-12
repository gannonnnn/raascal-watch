#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.11 or newer is required. Install it from python.org, then run this file again."
  read -r -p "Press Return to close..."
  exit 1
fi

if ! python3 - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
then
  echo "Python 3.11 or newer is required. Your current python3 is too old."
  read -r -p "Press Return to close..."
  exit 1
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install -e .

if [ ! -f .env ]; then
  cp .env.example .env
fi

raascal-watch validate-config
# Version 0.3 is live-only by default. Remove any synthetic records left by
# earlier builds while preserving all Kalshi and Polymarket history.
raascal-watch purge-demo
# Refresh role-aware, contract-specific guidance for matches already stored locally.
raascal-watch refresh-guidance
# Version 0.4 calculates lifecycle dynamically: expired contracts leave the
# current queue immediately but remain available in the historical archive.
raascal-watch lifecycle-summary

echo
echo "RaaScal Watch is opening at http://127.0.0.1:8000"
echo "The default dashboard shows active contracts only; historical records are under Archive."
echo "Keep this window open. Press Control-C here to stop the service."
echo

( sleep 2; open http://127.0.0.1:8000 >/dev/null 2>&1 || true ) &
raascal-watch serve
