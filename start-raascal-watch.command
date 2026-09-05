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

# Fail clearly BEFORE installation if a browser upload put dotfiles in a subfolder.
for required in .env.example .gitignore; do
  if [ ! -f "$required" ]; then
    echo "Missing $required at the project root ($PWD)."
    echo "Download the complete package or repair the repository layout; do not paste credentials here."
    exit 1
  fi
done

if [ ! -d .venv ]; then
  echo "[1/5] Creating the local Python environment..."
  python3 -m venv .venv
else
  echo "[1/5] Using the existing local Python environment."
fi

source .venv/bin/activate

echo "[2/5] Checking the local installation..."
if python - <<'CHECK'
from importlib.metadata import version
from pathlib import Path
import sys, tomllib
spec = tomllib.loads(Path('pyproject.toml').read_text())
try:
    import raascal_watch, fastapi, httpx, jinja2, yaml, dotenv, uvicorn
    correct = version('raascal-watch') == spec['project']['version']
    correct = correct and Path(raascal_watch.__file__).resolve().parent.parent == Path.cwd().resolve()
except Exception:
    correct = False
raise SystemExit(0 if correct else 1)
CHECK
then
  echo "      This version is already installed; skipping unnecessary reinstall."
else
  python -m pip install -e .
fi

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
echo "Scan progress appears above the dashboard. Stop scan retains committed batches."
echo "Keep this window open. Press Control-C here to stop the service."
echo

( sleep 2; open http://127.0.0.1:8000 >/dev/null 2>&1 || true ) &
exec python -m raascal_watch.cli serve
