# RaaScal Watch v0.9.1 — responsive scanning

## What was wrong

In v0.9.0, the async scanner ran a long synchronous scoring/SQLite loop on the
web server's event loop. During a silent baseline it could run for minutes
without yielding. That prevented refreshes, filters, status checks, and shutdown
from responding. Each market also opened a separate database connection and
transaction. Unit tests with small record lists did not expose the problem.

## What changed

- Matching and database processing use a worker thread, in batches of at most
  100 records. Scoring happens before taking the write lock.
- SQLite connections remain thread-local. Writes commit in short transactions;
  readers use their own connections. Existing WAL mode is retained.
- Synchronous dashboard, filtering, analytics, feedback and Field Note routes run
  through FastAPI's threadpool rather than blocking its async event loop.
- A downloaded source can be processed without waiting for every other source.
- `POST /api/scan` returns HTTP **202 Accepted** promptly. It no longer holds the
  HTTP connection open for an entire scan. Automated clients must now poll
  `GET /api/scan/status` for completion and the summary.
- That status endpoint performs no database queries. It reports phase, elapsed
  time, last progress, per-source page/download/processed/match counts, warnings,
  errors, and whether the scan is still running.
- The browser polls for progress, disables duplicate scan requests, and refreshes
  saved results at completion while retaining the current filter URL. It does
  not reload over an edited assessment or an expanded review; a refresh link is
  offered instead.
- **Stop scan** requests cooperative cancellation. A short in-flight write batch
  finishes before the worker exits. Previously committed batches remain. An
  unfinished source is not marked as a successful baseline or advanced watermark.
- Terminal processing counts are logged periodically rather than only at the end.
- `GET /health/live` is a cheap liveness check independent of database analytics.
- Root `.env.example` / `.gitignore` checks and Git ignore behavior tests are
  included. A GitHub Actions workflow runs tests and an offline HTTP smoke check.
- The launcher validates root files and skips an unnecessary reinstall when the
  correct version is already installed from this folder.

## Installation and preservation

This package includes the v0.9.0 themes, materiality gate, Incentive Maps, reviews,
active/archive separation, Field Notes and source integrations. It changes the
scan execution and progress interface, not the risk-scoring framework.

The local updater requires an explicit existing project folder, avoiding silent
selection of an older copy. Stop all running copies before applying it. It refuses
to proceed when the default local server port (8000) is occupied; custom-port or
CLI scans must also be stopped. It saves source/config backups and, when an
existing installation is available, uses SQLite's backup API for the configured
database. Backups are in a sibling `_raascal-local-backups` directory and are
private. Do not commit those backups.

Existing `.env`, `.venv`, custom watchlist, live database, reviewer decisions,
observations and source history are not replaced. Root `.gitignore` rules are
merged. Profile synchronization runs only if the configuration fingerprint
changes; there is no forced full re-index solely for this maintenance patch.

## Validation and boundaries

The automated suite includes regression tests for responsive HTTP/status requests
while deliberately slow matching is running, duplicate-start rejection,
cancellation, subsequent restart, source-failure isolation, transaction rollback,
thread-local read/write isolation, and clean installation file layout.

A separate local test processed **100,000 generated test records** while serving
status and filtered-dashboard requests. This was a workload test, not a live
Kalshi/Polymarket scan and not a runtime promise for someone else's laptop.

A scan can still take minutes. Public APIs may fail or throttle requests. The
collectors still retain each source's downloaded records in memory before batch
processing; this is not a streaming or distributed job system. Polymarket remains
page-based; Kalshi's existing incremental policy is unchanged. Page-capped scans
carry coverage warnings and must not be described as a complete inventory. The
patch does not fill old coverage gaps or reconstruct missed historical data.

Progress counts are not threat counts. Saved results displayed during a scan may
be partial or from a prior scan. A profitable trade is not evidence of misconduct.
The application remains an unauthenticated local research prototype; do not expose
it directly to the public internet.

If cancellation occurs after a notification becomes eligible but before it is
sent, delivery is not guaranteed by an outbox/retry system. Notification delivery
hardening remains separate work.

## Engineering references

- Python asyncio: https://docs.python.org/3/library/asyncio-dev.html
- Thread offloading: https://docs.python.org/3/library/asyncio-task.html#asyncio.to_thread
- FastAPI sync/async handlers: https://fastapi.tiangolo.com/async/
- SQLite WAL concurrency: https://sqlite.org/wal.html
