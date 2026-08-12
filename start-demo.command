#!/bin/bash
# Backward-compatible launcher retained for people who used earlier versions.
# Version 0.3 no longer seeds synthetic demo records during normal startup.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec bash "$SCRIPT_DIR/start-raascal-watch.command"
