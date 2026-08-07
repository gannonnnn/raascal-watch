# Start RaaScal Watch

## Easiest on a Mac

Double-click `start-demo.command`.

The first launch creates a private Python environment, installs the required packages, loads the offline Spotify demo, starts the dashboard, and opens:

`http://127.0.0.1:8000`

If macOS blocks the file on first launch, Control-click it, choose **Open**, then confirm **Open**.

Keep the Terminal window open while using the dashboard. Press **Control-C** in that window to stop it.

## Manual setup

```bash
cd raascal-watch
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
raascal-watch seed-demo
raascal-watch serve
```

## Switch from demo to live public listings

1. Edit `config/watchlist.yaml` with the company, products, executives, and metrics you want to monitor.
2. Validate it with `raascal-watch validate-config`.
3. Run `raascal-watch scan`, or leave `raascal-watch serve` running for scheduled scans.
4. Add a Slack webhook, generic webhook, or SMTP settings to `.env` when you are ready for external notifications.

The first successful live scan of each source is deliberately silent. It establishes the baseline; contracts first observed afterward can trigger alerts.
