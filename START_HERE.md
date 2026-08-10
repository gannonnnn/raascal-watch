# Start RaaScal Watch

## Easiest method on a Mac

Double-click `start-demo.command`.

The first launch creates a private Python environment, installs the project, loads the offline demonstration data, starts the dashboard, and opens:

`http://127.0.0.1:8000`

If macOS blocks the file, Control-click it, choose **Open**, and confirm. Keep the Terminal window open while using the dashboard. Press **Control-C** in that window to stop the service.

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

## Switch from demo data to live public listings

1. Edit `config/watchlist.yaml` with the company, products, executives, and metrics to monitor.
2. Run `raascal-watch validate-config`.
3. Run `raascal-watch scan`, or leave `raascal-watch serve` running for scheduled scans.
4. Add Slack, generic webhook, or SMTP settings to `.env` when ready for external notifications.

The first successful live scan of each source is intentionally silent. It establishes a baseline so already-existing contracts do not create an initial alert flood.
