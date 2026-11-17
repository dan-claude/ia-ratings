# IA Film Rater

A React + Flask + SQLite web app for judging films from the Internet Archive
collection **`2026-public-domain-day-film-contest`**.

Judges log in, are shown one unrated film at a time (embedded archive.org player
plus the film's description), score it against a set of criteria, and move on to
the next film. Admins sync the collection from archive.org, manage criteria and
users, browse the database, export ratings as CSV, and back up / restore the
whole database — all from an admin panel inside the app.

Production runs on Railway (new deployment being set up; URL to follow).

## Features

- **One film at a time.** `GET /api/films/next` returns a random film the
  current user hasn't rated yet. Scores are entered in a criteria grid with
  per-criterion validation and quick-pick buttons.
- **Two login modes** (`AUTH_SCHEME`):
  - `ia` *(default)* — log in with an archive.org username and password. The
    server checks them against archive.org and creates a local account on first
    login. No registration step.
  - `local` — email + password accounts stored locally (werkzeug password
    hashing), with self-registration.
- **Continue with GitHub** *(optional, in addition to either mode)* — set
  `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` and the login screen gains a
  GitHub button. Setup steps: [`docs/GITHUB_LOGIN.md`](docs/GITHUB_LOGIN.md).
- **Admin panel** (shown to users with `users.is_admin = 1`), with tabs:
  - *Actions* — sync the IA collection (runs in the background with a progress display; nothing syncs automatically at startup), empty the film database (films + ratings; asks for confirmation), download `ratings.csv`
  - *Criteria* — add, edit, reorder and deactivate rating criteria
  - *Users* — promote / revoke admins
  - *DB Browser* — table row counts and paged table dumps
  - *Backup* — download the full DB as JSON; restore from a backup file
- Cookie sessions (8-hour lifetime, `HttpOnly`, `SameSite=Lax`, `Secure` when a
  real `SESSION_SECRET` is set) and rate-limited login/register endpoints.

## Tech stack

| Part | Stack |
|------|-------|
| Client | React 18 + Vite, single file `client/src/App.jsx`, no UI library |
| Server | Flask 3 app factory; routes → services → repositories |
| Database | SQLite (WAL mode), schema + migrations applied at startup in `server/db.py` |
| Auth | Flask cookie sessions; archive.org `xauthn` or local accounts, plus optional GitHub OAuth |
| Hosting | Railway (Dockerfile build, deploys from GitHub on push to `main`); GitHub Actions CI |

## Running locally

Requires Python 3.12 (CI and Docker use 3.12) and Node 20.

### Server

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
make dev                                   # = PYTHONPATH=. python -m server.app
# or, with local email/password accounts instead of archive.org login:
PYTHONPATH=. python -m server.app --auth-scheme local
```

Useful flags: `--host`, `--port`, `--debug` / `--no-debug`, `--auth-scheme ia|local`,
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

If your Flask server is on a different port, change the proxy target in
`client/vite.config.js`.

### First-time setup

1. Start the server once so it creates the database (`server/app.db` by default).
2. Log in once (creates your user row).
3. Make yourself an admin:
   ```bash
   python tools/print_db.py --make-admin you@example.com
   # IA-auth users are stored with the email <username>@users.archive.org
   python tools/print_db.py --make-admin yourname@users.archive.org
   ```
4. Log out and back in, open the admin panel → *Actions* → **Sync Collection**.
   Until you do, raters see "the film database hasn't been set up yet".
   (Or sync from the command line: `python tools/sync.py`.)

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `DB_PATH` | `server/app.db` | SQLite file location |
| `SESSION_SECRET` | insecure dev value | Session signing key. **Set this in production.** While unset, the server warns at startup and session cookies are not marked `Secure`. |
| `AUTH_SCHEME` | `ia` | `ia` or `local` (the `--auth-scheme` flag overrides it) |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | *(unset)* | Enable GitHub login when **both** are set — see [`docs/GITHUB_LOGIN.md`](docs/GITHUB_LOGIN.md) |
| `GITHUB_REDIRECT_URI` | *(unset)* | Rarely needed; overrides which registered callback URL GitHub uses |
| `LOG_LEVEL` | `INFO` | Server log level |
| `FLASK_RUN_HOST` / `FLASK_RUN_PORT` | `0.0.0.0` / `5000` | Defaults for `--host` / `--port` |
| `FLASK_DEBUG` | `0` | `1` enables the Werkzeug debugger (dev only) |
| `PORT` | `5000` | Port gunicorn listens on in the Docker image (Railway sets it) |
| `VITE_LOG_LEVEL` | `info` | Client console logging: `debug`, `info`, `warn`, `error`, `silent` |

The film collection slug is fixed in `server/config.py`.

## Testing

```bash
pip install -r server/requirements-dev.txt
make test          # = PYTHONPATH=. pytest -q
```

Tests run against a temporary SQLite file with `AUTH_SCHEME=local`.

## Command-line tools

| Tool | What it does |
|------|--------------|
| `tools/print_db.py` | Inspect the local DB (`--tables`, `--table`, `--where`, `--order-by`, `--limit`, `--json`, `--schema`) and `--make-admin` / `--revoke-admin EMAIL` |
| `tools/sync.py` | Sync the IA collection into a DB from the command line (`--db`, `--workers`, `--collection`, `--force`) |

Both tools are also in the production image: run them on Railway with `railway ssh`
(they use the service's `DB_PATH`). Otherwise use the admin panel or the admin API
(see `API_CLIENT_SERVER.md`).

## Deployment

Railway is connected to the GitHub repo and deploys every push to `main`.
GitHub Actions (`.github/workflows/ci.yml`) runs the Python tests and a client
build on pushes and pull requests.
The multi-stage `Dockerfile` builds the client with Node 20 and runs the server on
Python 3.12 under gunicorn (one worker, eight threads); `railway.toml` sets the `/api/health` health check. The production DB
lives on a Railway volume at `/data/app.db` (`DB_PATH=/data/app.db`). To make
the first production admin, `railway ssh` into the service and run
`python tools/print_db.py --make-admin <email>` (details in `CLAUDE.md`).
See `CLAUDE.md` for the full deployment notes.

## Documentation map

| File | Contents |
|------|----------|
| `README.md` | This overview |
| `API_CLIENT_SERVER.md` | Every API endpoint with request/response shapes |
| `docs/GITHUB_LOGIN.md` | Creating and configuring the GitHub OAuth app |
| `CLAUDE.md` | Working notes for Claude: architecture, env vars, deployment, admin API |
| `CHANGELOG.md` | Version history |
| `RECREATE_WITH_CLAUDE.txt` | Full from-scratch rebuild spec (embeds the server source) |
