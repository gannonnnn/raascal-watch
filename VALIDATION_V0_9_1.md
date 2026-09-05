# v0.9.1 validation record

This report concerns the packaged source, not a live user's private repository.

## Automated suite

**107 tests passed**, including the 97 existing tests and 10 added regressions.
The added tests cover responsive API/dashboard access during deliberately slow
matching; duplicate-start rejection; cancellation and restart; cancellation
without advancing the baseline; isolated collector errors; atomic batch rollback;
thread-local transaction isolation; processing a fast source before a slow source
finishes downloading; progress UI safeguards; and correct root setup-file/ignore
behavior.

## Larger processing test

- Input: **100,000 generated fixture records**, with 1,000 matching Spotify records.
- Storage: temporary SQLite database; actual scoring, matching, snapshot and write
  code was used. No real Kalshi or Polymarket API was called.
- Concurrent requests: 199 scan-status polls plus filtered dashboard requests.
- Total processing/test time on this Linux container: **53.276 seconds**.
- Slowest measured status response: **0.0314 seconds**.
- Slowest measured filtered-dashboard response: **1.9045 seconds**.
- Result: all 100,000 records stored; 1,000 matches; no baseline notifications.

This is not a prediction of a Mac's runtime. Source download time, real record
size, CPU, disk, database history, rate limiting, and other workloads differ.

## Startup and UI

An actual local HTTP server with a temporary database passed startup, dashboard
rendering, and SIGINT shutdown checks with automatic external collection disabled.
The shipped `tools/smoke_startup.py` reproduces that check.

A headless Chromium UI harness checked live progress rendering, filter submission,
Stop scan, a visible refresh link, and preservation of an expanded review, with
no JavaScript errors. The harness used a local HTTP bridge because this execution
environment blocks browser navigation to loopback addresses. The HTTP route tests
and the DOM tests are therefore complementary, not a claim of a full live-source
browser test on macOS.

## Updater integration

A temporary v0.9.0 installation was upgraded to v0.9.1. The test confirmed:

- a SQLite backup was created from a custom database path;
- the original market and reviewer note were retained;
- `.env` contents were unchanged;
- a custom watchlist alias and custom ignore rule survived;
- the upgraded HTTP app started and stopped successfully.

The temporary environment reused this container's installed dependencies. It did
not test downloading every dependency on a completely offline or restricted Mac.
GitHub CI is included for clean installation with dependency resolution, but that
remote workflow has not run until the user commits it to their repository.

## Remaining limits

No live-provider uptime, market coverage, security certification, or production
service guarantee is implied. Page caps and source failures remain possible.
Cancellation retains committed work but may leave notification delivery pending;
there is not yet a durable notification outbox. The app remains local-only and
has no user authentication.
