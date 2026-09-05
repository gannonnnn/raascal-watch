# Start RaaScal Watch v0.9.1

## First launch from a fresh repository download (Mac)

1. Install Python 3.11 or newer. Unzip the complete source project.
2. Confirm `.env.example` and `.gitignore` are next to `pyproject.toml` at the top
   level, not inside `raascal_watch/templates`.
3. Open Terminal. Type `bash ` (including the space), drag
   `start-raascal-watch.command` into Terminal, and press Return.
4. Keep Terminal open. Open `http://127.0.0.1:8000` after the server starts.

The installer creates your own `.venv`, `.env`, and database. They do not come
from GitHub. The first collection starts automatically unless disabled in your
settings. It can take minutes; the progress panel reports each source separately.
No synthetic demo data is added on normal startup.

## Every later launch

Run the same `start-raascal-watch.command` from the SAME project folder. Creating
another fresh folder also creates a separate database; it does not import prior
results or reviewer decisions.

**Run scan** starts one background job. Filters remain usable while it runs.
**Stop scan** retains saved batches. To stop the entire app, press Control+C in
Terminal and wait for the prompt. Do not delete SQLite journal/WAL files.

When processing finishes, the dashboard refreshes unless you are editing a review
or reading an expanded card. In that case, save your work and use the refresh link.
The default Review today tab is narrower than All active; a zero there is not a
claim that no relevant contracts exist.

## Recovery / read-only browsing session

From inside the project folder, with no other copy running:

```bash
RAASCAL_RUN_SCAN_ON_STARTUP=false .venv/bin/python -m raascal_watch.cli serve
```

This disables the automatic scan scheduler for that session; the manual button
still works. Do not change or share your `.env` just to troubleshoot.

## Sharing with an engineering reviewer

Commit the clean source package to GitHub. The reviewer can pull the updated code
and run the launcher. Existing `.env` and database files stay local. Test with
`python -m pytest` and `python tools/smoke_startup.py` after installing `.[dev]`.
This is still local, unauthenticated prototype software, not a hosted service.
