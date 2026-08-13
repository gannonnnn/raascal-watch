# Start RaaScal Watch

## Easiest method on a Mac

Run `start-raascal-watch.command`.

The first launch creates a private Python environment, installs the project, synchronizes newly shipped organization profiles into the local watchlist, re-evaluates stored markets when that watchlist changes, removes any synthetic records left by older versions, starts the dashboard, and opens:

`http://127.0.0.1:8000`

If macOS blocks the file, use Terminal:

```bash
bash "/path/to/raascal-watch/start-raascal-watch.command"
```

Keep the Terminal window open while using the dashboard. Press **Control-C** in that window to stop the service.

The old `start-demo.command` filename still works for compatibility, but normal startup no longer loads synthetic demo data.

## Manual setup

```bash
cd raascal-watch
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
raascal-watch sync-profiles --defaults ./config/watchlist.defaults.yaml
raascal-watch validate-config
raascal-watch purge-demo
raascal-watch serve
```


## Organization profile synchronization

Every enabled organization and monitored theme appears in the profile filter, including profiles with zero current matches. The number beside each profile is the active or archived contract count for the selected view.

When a release adds a profile, RaaScal Watch merges it into the existing `config/watchlist.yaml`, preserves custom organizations and local terms, creates a timestamped backup, and re-evaluates stored market records. A fingerprint prevents the large re-index from repeating on every launch.

Run the synchronization manually with:

```bash
raascal-watch sync-profiles --defaults ./config/watchlist.defaults.yaml
```

Add `--force` only when you intentionally want to re-evaluate the stored library again.


## Flight-cancellation monitoring

Use the profile filter in two ways:

- Select **Flight cancellation markets — theme** to see qualifying cancellation contracts without assigning them to one data provider.
- Select **FlightAware** to see direct, verified, or linked FlightAware relationships only.

A known FlightAware-dependent contract can carry both profiles while appearing once in the dashboard. The review panel explains whether the relationship is direct, verified, linked, or theme-only.

The Kalshi collector directly queries series referenced by dependency rules, so the weekly `KXUSFLYCAN` family and discovered `KXFLYCANC...` airport series are not dependent on their position in the broad market pagination.

## Active queue and archive

The default page shows only active contracts. Closed or expired contracts are retained under the separate **Archive** tab and have no review controls. Filters update automatically when a selection changes; there is no Apply button. Related thresholds and dates are grouped beneath a collapsible series.

## Contract-specific review guidance

Open **Review this active contract** on a current result to see the likely organization role, why it surfaced, questions to answer, suggested owners, and first review steps tailored to that contract's title, rules, source, probability, volume, and close time.

To regenerate this guidance for records already in the local database without another API scan:

```bash
raascal-watch refresh-guidance
```

## Live-only behavior

- Dashboard totals and results exclude synthetic `demo` records by default.
- The standard launcher permanently removes old demo records from the local database.
- Kalshi and Polymarket history is preserved.
- The first successful live scan of each source remains a silent baseline.

## Explicit developer demo

```bash
raascal-watch seed-demo
```

Then open:

`http://127.0.0.1:8000/?source=demo&include_demo=true`

## Kalshi source note

RaaScal Watch first uses Kalshi's documented `external-api` production host. If that host returns HTTP 403/404 or cannot be reached, it automatically retries through Kalshi's supported `api.elections` compatibility host.

## Refreshing existing contract guidance

The updater refreshes stored matches automatically after it copies the new code. To run it manually:

```bash
raascal-watch refresh-guidance
```

This updates the role, review questions, and contract-specific next steps without deleting live history or requiring another API pull.
