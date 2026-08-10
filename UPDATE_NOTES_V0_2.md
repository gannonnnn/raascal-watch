# Applying the RaaScal Watch 0.2 update

This update is designed to preserve your local `.env`, `.venv`, and `data/raascal_watch.db` files.

## What changes

The update adds Cloudflare, YouTube, and MrBeast / Beast Industries profiles, new risk categories, clearer dashboard labels, multi-organization display chips, expanded demo fixtures, and tests.

## After applying it locally

1. Stop the running dashboard with **Control-C** in Terminal.
2. Run the updater or copy the patch files into the existing project folder.
3. Start the dashboard again with `bash start-demo.command`.
4. Let the scheduled scan run or click **Run scan** once.

Existing stored records will be evaluated for the new profiles when they are fetched again. Matches on already-known contracts are stored as historical candidates and do not create a burst of new notifications under the default settings.

## Demo-only refresh

The existing live database is intentionally preserved. To inspect the new synthetic demo examples in a separate database, use a fresh project copy or temporarily point `RAASCAL_DB_PATH` to another file before running `raascal-watch seed-demo`.
