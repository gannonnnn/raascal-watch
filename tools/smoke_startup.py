"""Offline HTTP startup/shutdown check after an actual install (no API traffic).

Run from the repository root: python tools/smoke_startup.py
Uses a temporary database, random local port, and the installed interpreter.
"""
from __future__ import annotations
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import json

ROOT = Path(__file__).resolve().parents[1]

def main() -> int:
    with tempfile.TemporaryDirectory(prefix='raascal-smoke-') as tmp:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            port = sock.getsockname()[1]
        env = dict(os.environ, RAASCAL_DB_PATH=str(Path(tmp)/'smoke.db'),
                   RAASCAL_WATCHLIST_PATH=str(ROOT/'config/watchlist.yaml'),
                   RAASCAL_RUN_SCAN_ON_STARTUP='false', RAASCAL_ENABLE_KALSHI='false',
                   RAASCAL_ENABLE_POLYMARKET='false')
        log_path=Path(tmp)/'server.log'
        with log_path.open('w') as log:
            proc=subprocess.Popen([sys.executable,'-m','raascal_watch.cli','serve','--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                if proc.poll() is not None:
                    raise RuntimeError('Server exited early')
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/health/live',timeout=1) as r:
                        health=json.load(r)
                    break
                except (OSError,ValueError):
                    time.sleep(.1)
            else:
                raise RuntimeError('Server did not become healthy')
            assert health['status']=='ok'
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/?gate=all',timeout=10) as r:
                page=r.read().decode()
            assert 'Earnings-call mention markets' in page
            assert 'scan-progress-panel' in page
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=10)
            assert proc.returncode in (0, -signal.SIGINT, 130)
            print('PASS: clean HTTP startup, dashboard rendering, and SIGINT shutdown; no external API calls.')
            return 0
        except Exception:
            print(log_path.read_text(), file=sys.stderr)
            raise
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

if __name__=='__main__':
    raise SystemExit(main())
