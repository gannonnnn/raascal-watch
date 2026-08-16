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
  echo "[1/5] Creating the local Python environment..."
  python3 -m venv .venv
else
  echo "[1/5] Using the existing local Python environment."
fi

source .venv/bin/activate

echo "[2/5] Installing the current RaaScal Watch version..."
python -m pip install -e .

if [ ! -f .env ]; then
  echo "[3/5] Creating the local configuration from .env.example..."
  cp .env.example .env
else
  echo "[3/5] Preserving the existing local configuration."
fi

echo "[4/5] Synchronizing monitoring profiles and validating the configuration..."
raascal-watch sync-profiles --defaults "$PWD/config/watchlist.defaults.yaml"
raascal-watch validate-config
raascal-watch purge-demo

echo "[5/5] Starting the local dashboard..."
echo
echo "RaaScal Watch is opening at http://127.0.0.1:8000"
echo "The default dashboard shows active contracts only; historical records are under Archive."
echo "Dashboard totals and reviewer calibration load after the browser opens."
echo "Keep this window open. Press Control-C here to stop the service."
echo

( sleep 2; open http://127.0.0.1:8000 >/dev/null 2>&1 || true ) &
raascal-watch serve
