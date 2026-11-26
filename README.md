# IA Film Rater

A React + Flask + SQLite web app for judging the public-domain films submitted to the
Public Domain Day film contest (the films are played from archive.org).

> **Work in progress on the `major-changes` branch.** The app is being rebuilt in
> steps. Steps 1 (a clean baseline), 2 (invite and sign in by magic link), 3 (spreadsheet import
> of the new columns), 4 (distribution and progress views), 5 (the new rating screen) and 6 (rankings and the judges' pool) 7 (judge export and final screen) and 8 (dark mode) are done. Step 1 was: a new database schema, the three roles
> (admin / reviewer / judge), hard-coded rating categories, per-person film
> assignments, and the old archive.org sync, collections, criteria editor, notes and
> old logins removed. All planned steps are implemented; nothing is merged or deployed yet. Production still runs the old app from `main`.

Reviewers and judges are shown the films assigned to them one at a time (embedded
archive.org player plus the film's details), score it in three categories (Aesthetic,
Sound(track), Appeal; 1–10 each) with an optional comment, and move on. Admins import
films, manage users and roles, browse the database, export ratings as CSV, and back
up / restore the database from an admin panel inside the app.

Production runs on Railway (new deployment being set up; URL to follow).

## Features

- **Assigned films.** `GET /api/films/next` returns the person's next film: one they
  opened but didn't finish, else a random unopened one from the films assigned to
  them. Each assignment is `assigned`, `seen` or `rated`. A rating (three scores and an
  optional comment of up to 1000 characters) is final.
- **Judges' results.** After a judge's last film they see their own ranked list (highest total first, with their scores and comments) and can download it as a CSV (*My ranked films* at any time). Reviewers have no export.
- **My films.** Reviewers and judges can open a list of all their films, each a link to that film's rating page, with its status: *unseen*, *seen* or *rated* (a rated film opens read-only showing their own scores and comment). The back button works.
- **Dark mode.** A Moon / Sun button switches between light and dark; the choice is remembered in the browser, and a first visit follows the device setting.
- **Three roles**, independent checkboxes in the admin panel's Users tab: *admin*
  (manages everything, doesn't rate), *reviewer* and *judge* (both rate their own
  films). A user with no role sees no films.
- **Sign-in is by personal magic link only.** An admin invites a person by email address
  (Users tab → Invite) and passes them the link; the app sends no email. The link opens a
  page with a **Sign in** button (so chat and email apps that preview links can't use it),
  works repeatedly until the expiry date the admin chose, and is replaced or cancelled by
  the admin (which also logs that person out). There are no passwords, archive.org logins
  or GitHub login.
- **Admin panel** (shown to users with `users.is_admin = 1`), with tabs:
  - *Import* — populate the film database from a CSV spreadsheet (see below)
  - *Actions* — film count and title-lookup progress, download `ratings.csv`, empty the film database (films, assignments and ratings; asks for confirmation)
  - *Reviews* — hand the films out to reviewers (every film to 2 different reviewers, at random, once; a typed-confirmation reset starts over), the "N of M films fully reviewed" counter, a per-person table (not opened / opened / submitted, with each person's films) and a per-film table showing who still owes a review, with hand assign / remove
  - *Rankings* — every film with its average score from highest to lowest (and all its details, downloadable as `rankings.csv`); choose the **judges' pool**: preview the top N films, with a check that the cut-off isn't a tie, blocked until every film has both its reviews; confirming gives every judge all the pool films (judges never see scores)
  - *Users* — invite people, tick Admin / Reviewer / Judge, create / cancel sign-in links and change their expiry
  - *DB Browser* — table row counts and paged table dumps
  - *Backup* — download the full DB as JSON; restore from a backup file
- Cookie sessions backed by a server-side record (8-hour lifetime, `HttpOnly`,
  `SameSite=Lax`, `Secure`): logging out really ends the session, and restoring a
  backup logs everyone else out.
- **One clean schema.** `server/db.py` creates the whole schema in one go. A database
  file made by the old app is refused at startup with a message to delete it.

## Tech stack

| Part | Stack |
|------|-------|
| Client | React 18 + Vite, single file `client/src/App.jsx`, no UI library |
| Server | Flask 3 app factory; routes → services → repositories |
| Database | SQLite (WAL mode), baseline schema created at startup in `server/db.py` |
| Auth | Flask cookie sessions with a server-side record; magic-link sign-in |
| Hosting | Railway (Dockerfile build, deploys from GitHub on push to `main`); GitHub Actions CI |

## Running locally

Requires Python 3.12 (CI and Docker use 3.12) and Node 20.

### Server

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
make dev                                   # = PYTHONPATH=. python -m server.app
```

The local server listens on `127.0.0.1` only and, without `SESSION_SECRET`, uses a
random secret per run (you are logged out when you restart it).

Useful flags: `--host`, `--port`, `--debug` / `--no-debug`,
`--with-client` (runs `npm install && npm run build` in `client/` first, so Flask
serves the built UI at `/`).

If the requested port is busy the server picks the next free one and says so.
On macOS port 5000 is usually taken by AirPlay, so the server normally ends up
on **5001** — which is what the Vite dev proxy expects.

### Client (dev server with hot reload)

```bash
cd client
npm install
npm run dev        # http://localhost:5173, proxies /api → http://127.0.0.1:5001
```

To point the dev server at a different API (another port, host, or a deployed server), set the
base URL, protocol and port included, in `API_URL`:

```bash
API_URL=http://127.0.0.1:5002 npm run dev
API_URL=https://ratings.example.org npm run dev
```

or put `API_URL=...` in `client/.env.local`. The browser still only talks to the Vite server, so
sign-in cookies work. (A deployed server sets `Secure` cookies, so use `http://localhost`, not a LAN
address, to open the dev page.)

### First-time setup

1. Start the server once so it creates the database (`server/app.db` by default). If
   the file is from the old app the server refuses to start; delete it (and its
   `-wal` / `-shm` files) and start again.
2. Create the first admin (nobody can sign in without an invite). This prints their link:
   ```bash
   PUBLIC_URL=http://localhost:5173 python tools/print_db.py --invite you@example.com --admin
   ```
   Open the printed link and press **Sign in**.
3. As an admin, open the admin panel → *Import* and load the spreadsheet. Until you do,
   people see "the film database hasn't been set up yet".

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `DB_PATH` | `server/app.db` | SQLite file location |
| `SESSION_SECRET` | *(none)* | Session signing key. **Required**: the server refuses to start without it (gunicorn/Railway). Only `python -m server.app` for local development may omit it. |
| `TRUSTED_PROXY_HOPS` | `0` | Reverse proxies in front of the app (Railway: `1`, set by the Dockerfile) so the sign-in rate limit is per real client |
| `LEGACY_DB` | *(unset)* | One-time: `move-aside` renames an old-style database to `<DB_PATH>.legacy-<time>` (nothing is deleted) and starts a fresh one; see `CLAUDE.md` "Resetting production" |
| `PUBLIC_URL` | *(unset)* | Site address, used only by `tools/print_db.py --invite` to print full links |
| `LOG_LEVEL` | `INFO` | Server log level |
| `FLASK_RUN_HOST` / `FLASK_RUN_PORT` | `127.0.0.1` / `5000` | Defaults for `--host` / `--port` (local only by default) |
| `FLASK_DEBUG` | `0` | `1` enables the Werkzeug debugger (dev only) |
| `PORT` | `5000` | Port gunicorn listens on in the Docker image (Railway sets it) |
| `VITE_LOG_LEVEL` | `info` | Client console logging: `debug`, `info`, `warn`, `error`, `silent` |

## Importing films from a spreadsheet

Films come only from a spreadsheet: export it as **CSV** (Google Sheets: *File → Download →
Comma-separated values*), then open the admin panel → **Import**.

1. Choose the file. The page guesses which column holds the archive.org link, the title, the
   creator (the "by" credit), the description, the public-domain works used, the AI disclosure and
   the **Eligible (yes/no)** flag (from the cell contents and header names); change any guess with
   the dropdowns. Only an explicit **yes** is imported when the Eligible column is mapped; no, blank
   and unclear rows are skipped and listed, so nothing ineligible reaches the reviewers.
2. Check the summary. Only rows whose link is an `archive.org/details/<id>` item are imported;
   rows with YouTube links, free text or no link are skipped and listed with the reason.
3. If some films are already in the database you must choose: **skip** them or **update** them
   from the spreadsheet (blank cells never erase stored data). This is how you re-import after the
   spreadsheet changed. An import never removes films: a film already loaded whose row now says
   "no" stays (the page warns you).
4. Leave "Look up missing titles" ticked if the sheet has no title column: titles are fetched from
   archive.org in the background (progress is shown); otherwise the identifier is the title.

## Testing

```bash
pip install -r server/requirements-dev.txt
make test          # = PYTHONPATH=. pytest -q
```

Each test runs against its own temporary SQLite file; users are created directly with the helpers in `server/tests/helpers.py` (there is no password login).

## Command-line tools

| Tool | What it does |
|------|--------------|
| `tools/print_db.py` | Inspect the local DB (`--tables`, `--table`, `--where`, `--order-by`, `--limit`, `--json`, `--schema`), `--make-admin` / `--revoke-admin EMAIL`, and `--invite EMAIL [--admin] [--roles a,b] [--days N]` (create a user / re-issue their link and print it) |

The tool is also in the production image: run them on Railway with `railway ssh`
(they use the service's `DB_PATH`). Otherwise use the admin panel or the admin API
(see `API_CLIENT_SERVER.md`).

## Deployment

Railway is connected to the GitHub repo and deploys every push to `main`.
GitHub Actions (`.github/workflows/ci.yml`) runs the Python tests and a client
build on pushes and pull requests.
The multi-stage `Dockerfile` builds the client with Node 20 and runs the server on
Python 3.12 under gunicorn (one worker, eight threads); `railway.toml` sets the `/api/health` health check. The production DB
lives on a Railway volume at `/data/app.db` (`DB_PATH=/data/app.db`). The new schema can't
reuse the old production database: set `LEGACY_DB=move-aside` once and the old file is renamed aside
(not deleted) when the new version starts; then create the first admin with `--invite` and import.
Steps in `CLAUDE.md`, "Resetting production for the new schema".
See `CLAUDE.md` for the full deployment notes.

## Documentation map

| File | Contents |
|------|----------|
| `README.md` | This overview |
| `API_CLIENT_SERVER.md` | Every API endpoint with request/response shapes |
| `CLAUDE.md` | Working notes for Claude: architecture, env vars, deployment, admin API |
| `CHANGELOG.md` | Version history |
