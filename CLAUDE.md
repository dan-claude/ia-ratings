# IA Film Rater

## Instructions for Claude

Before finishing any task that touches any of the following, check whether `CLAUDE.md` needs updating and update it if so:
- API routes (any file under `server/routes/`)
- Configuration or environment variables (`server/config.py`)
- Auth scheme or login flow (`server/services/auth_service.py`, `server/routes/auth.py`)
- Deployment config (`Dockerfile`, `railway.toml`, `.github/workflows/`)
- Database schema or migrations (`server/db.py`)
- Admin tooling (`tools/`, `server/routes/admin.py`)

When an API route changes, also update `API_CLIENT_SERVER.md` (the binding API contract) and add a `CHANGELOG.md` entry.



React + Flask + SQLite app for rating public-domain films from the Internet Archive collection `2026-public-domain-day-film-contest`.

## Architecture

- **Client:** `client/src/App.jsx` — single-file React app, Vite, no component library
- **Server:** Flask app-factory (`server/app.py`), organized as routes → services → repositories
- **DB:** SQLite at `server/app.db` (path overridable via `DB_PATH` env var)
- **Auth:** Cookie-based sessions; two schemes (see below); roles (`admin`, `judge`) are columns on `users` (`is_admin`, `is_judge`)

### Server layout

```
server/
  app.py              # app factory + CLI entrypoint
  config.py           # Settings dataclass (reads env vars)
  db.py               # thin SQLite wrapper + schema migrations
  routes/             # Flask blueprints (auth, films, admin, user)
  services/           # business logic (AuthService, RatingService, SummaryService, InternetArchiveService)
  repositories/       # DB access per entity (users, films, criteria, ratings)
  models/             # data model classes
```

## Auth schemes

Controlled by the `AUTH_SCHEME` env var (or `--auth-scheme` CLI flag). Default: `ia`.

| Scheme | Login flow | Register |
|--------|-----------|----------|
| `ia` | Username + password proxied to `archive.org/services/xauthn/`; account auto-created on first login with synthesised email `{username}@users.archive.org`, `ia_username` set, and `password_hash='IA_AUTH'` | Not supported (400) |
| `local` | Email + password stored locally (werkzeug `generate_password_hash`) | Supported via `/api/auth/register` |

**GitHub OAuth** is an optional extra on top of either scheme: it is enabled when both `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` are set, and `GET /api/config` then lists `"github"` in `oauth_providers` so the client shows "Continue with GitHub". Flow (`server/routes/auth.py` + `server/services/github_auth_service.py`): `GET /api/auth/github/login` stores a random single-use `state` in the session and redirects to GitHub → `GET /api/auth/github/callback` checks the state, exchanges the code, reads the public profile (no scopes requested), find-or-creates the user keyed on `users.github_id` (synthetic email `{id}+{login}@users.noreply.github.com`, `password_hash='GITHUB_AUTH'`), rotates the session and redirects to `/` (failures redirect to `/?auth_error=<code>`). Accounts from different login methods are never merged. Setup instructions: `docs/GITHUB_LOGIN.md`.

**Roles.** A user can hold any combination of `admin` and `judge` (checkboxes in the admin panel → Users; `PUT /api/admin/users/<id>/roles` with `{"roles": [...]}`, which sets the list exactly; an admin can't remove their own admin role). Roles are independent: admin does not imply judge. `/api/me` returns `is_admin`, `is_judge` and `roles`. Role names ↔ columns live in `ROLE_COLUMNS` in `server/repositories/user_repo.py`; to add a role add a column (migration) and an entry there. **Judges** can read and add free-text notes on films (`GET/POST /api/films/<id>/notes`, judge-only; non-judges get 403, so notes are invisible to everyone else, admins included). Notes live in `film_notes` (many per film, attached to `films.id`, so they survive re-syncs but are deleted by "empty database"); the client shows them at the bottom of the film page in a Who / When / Note table with an "Add note" popup. Author shown = `ia_username`, else `github_username`, else email. Max 5000 characters.

Login body is `{username, password}` in `ia` mode and `{email, password}` in `local` mode. `/api/auth/login` and `/api/auth/register` are rate-limited (10/min, 50/hour per IP). Sessions: 8-hour lifetime, `HttpOnly`, `SameSite=Lax`, `Secure` unless the dev default secret is in use.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `server/app.db` | Path to SQLite database file |
| `SESSION_SECRET` | *(insecure dev default)* | Flask session signing key — **must be set in production**. With the default the server only warns, and cookies are not `Secure` |
| `AUTH_SCHEME` | `ia` | Auth scheme: `ia` or `local` |
| `FLASK_DEBUG` | `0` | Set to `1` to enable Werkzeug debugger (dev only) |
| `RATELIMIT_STORAGE_URI` | `memory://` | Flask-Limiter storage; set to `redis://...` for multi-instance |
| `PORT` | `5000` | HTTP port gunicorn binds to in the Docker image (Railway sets it) |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | *(unset)* | GitHub OAuth app credentials; GitHub login is enabled only when both are set (see `docs/GITHUB_LOGIN.md`). Secret — set only in Railway variables / local shell |
| `GITHUB_REDIRECT_URI` | *(unset)* | Optional; sent to GitHub only if set (normally the callback URL registered on the OAuth app is used) |
| `LOG_LEVEL` | `INFO` | Server log level (`server/logging_config.py`) |
| `FLASK_RUN_HOST` / `FLASK_RUN_PORT` | `0.0.0.0` / `5000` | Defaults for `--host` / `--port` when running `python -m server.app` |
| `VITE_LOG_LEVEL` | `info` | Client console log level (`client/src/logger.ts`) |

`Settings` in `server/config.py` reads env vars via `default_factory`, i.e. each time `load_settings()` / `Settings()` is called. Don't go back to plain `= os.environ.get(...)` defaults: those are frozen at import time and break per-test DBs.

## Running locally

### Server
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
make dev          # or: PYTHONPATH=. python -m server.app --auth-scheme local
```

### Client (dev, with proxy to Flask)
```bash
cd client
npm install
npm run dev
```

`client/vite.config.js` proxies `/api` to `http://127.0.0.1:5001`. Flask defaults to 5000 but falls back to the next free port (on macOS, 5000 is usually taken by AirPlay, so it lands on 5001). `.claude/launch.json` also starts Flask on 5001.

### Client (production build, served by Flask)
```bash
python -m server.app --with-client
```

## Testing

```bash
pip install -r server/requirements-dev.txt
make test         # or: PYTHONPATH=. pytest -q
```

Tests run with `AUTH_SCHEME=local` (set in `conftest.py`).

Each test gets its own temp DB (`tmp_path/test.db`); `server/tests/test_isolation.py` guards this.

## Deployment

### Hosting: Railway

Deploys come from Railway's **GitHub integration**: the Railway service is connected to `dan-claude/ia-ratings` and builds every push to `main`. GitHub Actions does not deploy (there is no `RAILWAY_TOKEN`).

- **Project:** `ia-ratings` on [railway.com](https://railway.com) (Railway account signed in with GitHub as `dan-claude`; set up fresh 2026-11)
- **Production URL:** *(set when the new Railway domain is generated — update here and in README.md)*
- **Builder:** Dockerfile (multi-stage — Node builds client, Python runs server)
- **Volume:** mounted at `/data`; `DB_PATH=/data/app.db` points the app at it. Without the volume the DB is wiped on every deploy.
- **Config file:** `railway.toml` — Dockerfile builder, healthcheck at `/api/health`, restart on failure

Railway service variables:
- `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` — optional, enable GitHub login (`docs/GITHUB_LOGIN.md`)
- `SESSION_SECRET` — random secret (`python3 -c "import secrets; print(secrets.token_hex(32))"`), keep private
- `DB_PATH` — `/data/app.db`
- `AUTH_SCHEME` — `ia`
- `PORT` is provided by Railway; don't set it

If Railway's service settings offer a "wait for CI" option, enable it so a failing test run blocks the deploy.

### CI: GitHub Actions (`.github/workflows/ci.yml`)

On every push to `main` and on pull requests:

1. **test** — installs Python deps, runs `make test`
2. **build-client** — installs Node deps, runs `npm run build` in `client/`

### Dockerfile

Multi-stage build to avoid Python version conflicts:

1. `node:20-slim` stage — builds the React client (`npm run build`)
2. `python:3.12-slim` stage — installs Python deps, copies server code and built client `dist/`

`tools/` is copied into the image so `print_db.py` and `sync.py` can be run in production via `railway ssh` (they pick up `DB_PATH=/data/app.db` from the service variables).

Production runs under **gunicorn** (pinned in `server/requirements.txt`), not Flask's dev server:

```
gunicorn --workers 1 --threads 8 --timeout 0 --bind 0.0.0.0:${PORT:-5000} "server.app:create_app()"
```

- **Keep `--workers 1`.** SQLite writes and the Flask-Limiter `memory://` store assume a single process; more workers would give each its own rate-limit counters and more lock contention. Scale with `--threads`.
- **`--timeout 0`** stops gunicorn killing a worker during long requests; a sync can take minutes (it now runs in a background thread, so the request itself returns at once).
- `python -m server.app` (with its `--auth-scheme`, port-fallback and `--with-client` conveniences) is for local development only. Under gunicorn, settings come from env vars only.

### Redeploy and production shell

Push to `main` → Railway rebuilds. To redeploy without a code change, use **Redeploy** on the latest deployment in the Railway dashboard.

For one-off production DB work (e.g. creating the first admin), use the Railway CLI's SSH and the bundled tools:

```bash
brew install railway               # or: npm install -g @railway/cli
railway login && railway link      # pick the ia-ratings project and the web service
railway ssh
# inside the container (cwd /app, DB_PATH already set):
python tools/print_db.py --table users
python tools/print_db.py --make-admin NAME@users.archive.org
```

## Database

Schema and migrations live in `server/db.py` and are applied on every startup (`CREATE TABLE IF NOT EXISTS` plus column-existence checks). Tables: `users`, `films`, `criteria`, `ratings`, `rating_scores`, `film_notes`, `app_settings`, `schema_migrations`. Migrations recorded in `schema_migrations`:

| Version | Change |
|---------|--------|
| 1 | `users.is_admin` |
| 2 | `ratings.updated_at` |
| 3 | `films.description` |
| 4 | `users.ia_username` + partial unique index `idx_users_ia_username` |
| 5 | `users.github_id` + `users.github_username` + partial unique index `idx_users_github_id` |
| 6 | New table `app_settings(key PRIMARY KEY, value, updated_at)` — holds the admin-chosen film `collection` |
| 7 | `films` is unique per `(ia_identifier, collection)` instead of per `ia_identifier` (table rebuilt in place, ids and ratings preserved; all-or-nothing). The same archive.org item can be in several collections, each with its own row and ratings |
| 8 | `users.is_judge` + new table `film_notes(id, film_id, user_id, body, created_at)` (judges' notes; in backup/restore order) |

The **active film collection** is a runtime admin setting (`app_settings` row `collection`, read through `AppSettingsRepository.get_collection`; falls back to `Settings.collection`, the built-in default). `FilmRepository`, `InternetArchiveService` and `SummaryService` take that getter, so a change applies immediately everywhere: raters only see films whose `collection` matches, and sync/import tag films with it. `tools/sync.py` defaults to the collection stored in the target DB. `app_settings` is in `_RESTORE_ORDER`, so backups/restores carry it.

Films can come from two places: the archive.org sync, or a CSV import (`server/services/import_service.py`; admin panel → Import). Because films are unique per `(ia_identifier, collection)`, "already exists" in an import means already in the *target* collection, and `FilmRepository.get_by_identifier`, sync upserts, title lookups and `update` imports are all scoped to a collection (the active one unless stated). The import request carries a `collection` (default: the active one; validated by `AppSettingsRepository.validate_collection`) that the films are filed under, and optional `activate_collection` to make it the active collection — the Import tab asks the admin for it and says it must match an archive.org collection name. The importer accepts **only** `archive.org/details|embed|download/<id>` links (exact host `archive.org`/`www.archive.org`) — rows without an archive.org source are skipped and reported. The column mapping is by column *index*; optional extra columns go to `films.metadata_json` (admin-only, never returned by `/api/films/*`). Missing titles can be looked up from archive.org by a background job (`SyncService.start_job("titles", …)`); one background job (sync or title lookup) runs at a time, and `import`/`sync`/`empty` return 409 while one runs.

Film data is **never synced automatically** (not at startup): a fresh database has zero films until an admin runs a sync (admin panel → Actions, or `tools/sync.py`). With zero films, `GET /api/films/next` answers 404 `code: "no_films"` and the client shows "the film database hasn't been set up yet". The background sync lives in `server/services/sync_service.py`; its status is in-process memory, which is why production keeps `--workers 1`.

Seed criteria (`INSERT OR IGNORE`): `originality`, `use_of_archive_materials`. When adding a migration, add a row here and, if it creates a new table, add that table to `_RESTORE_ORDER` in `routes/admin.py` so backups restore it.

## Key API endpoints

Full request/response shapes are in `API_CLIENT_SERVER.md`.

### Public
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check (used by Railway) |
| GET | `/api/config` | Returns `{"auth_scheme": "ia"\|"local", "oauth_providers": ["github"]?}` |
| POST | `/api/auth/login` | Login |
| POST | `/api/auth/register` | Register (local auth only) |
| GET | `/api/auth/github/login` | Start GitHub OAuth (302 to GitHub; 404 if not configured) |
| GET | `/api/auth/github/callback` | GitHub OAuth return (302 to `/`, or `/?auth_error=<code>`) |
| POST | `/api/auth/logout` | Logout |
| GET | `/api/me` | Current user info |
| GET | `/api/criteria` | Rating criteria list |
| GET | `/api/films/next` | Random unrated film for current user |
| GET | `/api/films/<id>` | One film by IA identifier |
| POST | `/api/films/<id>/ratings` | Submit scores (`{"scores": {"key": int}}`) |
| GET | `/api/films/<id>/notes` | Notes on a film, oldest first (**judge only**) |
| POST | `/api/films/<id>/notes` | Add a note `{"text": str}` → 201 (**judge only**) |

### Admin only (`is_admin=1` required)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/admin/sync` | Start an Internet Archive sync in the background (202; 409 if one is running) |
| GET | `/api/admin/sync/status` | Sync progress: `state` idle/running/done/error, `phase`, `done`/`total`, `film_count` |
| GET | `/api/admin/settings` | Active film collection, the built-in default, and every collection that has films (with counts) |
| PUT | `/api/admin/settings/collection` | Set the active collection (`{"collection": "slug"}`; validated; 409 while a background job runs) |
| POST | `/api/admin/import/preview` | Read a CSV (`{"csv_text"}`): headers, row count, sample rows, suggested column mapping. Saves nothing |
| POST | `/api/admin/import` | Import films from a CSV with a column `mapping`; `dry_run` reports only; real import needs `on_existing` `"skip"`/`"update"`; optional `lookup_titles`; only archive.org item links are imported |
| POST | `/api/admin/db/empty` | **Destructive.** Delete all films + ratings (keeps users/criteria); body `{"confirm": "EMPTY"}`; 409 while syncing |
| GET | `/api/admin/ratings.csv` | Export all ratings |
| GET | `/api/admin/criteria` | List all criteria (incl. inactive) |
| POST | `/api/admin/criteria` | Create criterion |
| PUT | `/api/admin/criteria/<id>` | Update criterion |
| GET | `/api/admin/db/tables` | Table row counts |
| GET | `/api/admin/db/schema` | CREATE TABLE statements |
| GET | `/api/admin/db/<table>` | Dump table rows (`order_by`, `limit`, `offset` params) |
| GET | `/api/admin/db/backup` | Download full DB as versioned JSON |
| POST | `/api/admin/db/restore` | Restore DB from a backup JSON |
| PUT | `/api/admin/users/<id>/roles` | Set a user's roles exactly (`{"roles": ["admin","judge"]}`) |
| POST | `/api/admin/users/<id>/make-admin` | Promote user to admin |
| POST | `/api/admin/users/<id>/revoke-admin` | Revoke admin from user |

## Admin tools

`tools/print_db.py` — local CLI for inspecting/modifying the SQLite DB directly:

```bash
python tools/print_db.py --table users
python tools/print_db.py --table films --limit 10 --order-by "id DESC"
python tools/print_db.py --make-admin user@example.com   # local DB only
python tools/print_db.py --make-admin name@users.archive.org   # IA-auth user
```

`tools/sync.py` — sync the IA collection into a DB from the command line (async description fetches via `aiohttp`, threaded fallback):

```bash
python tools/sync.py                    # only fetch descriptions that are missing
python tools/sync.py --workers 20 --force --db server/app.db
```


> Note: `railway run` executes locally with Railway env vars injected but **cannot** access the Railway volume (`/data/app.db`). Use the admin UI/API, or `railway ssh` + `tools/print_db.py` (see Deployment) for the production database.

## Documentation files

| File | Purpose |
|------|---------|
| `README.md` | Human-facing overview, local setup, config |
| `API_CLIENT_SERVER.md` | Binding API contract — update with any route change |
| `CHANGELOG.md` | Version history |
| `docs/GITHUB_LOGIN.md` | Step-by-step GitHub OAuth app setup (dev + production) |
| `RECREATE_WITH_CLAUDE.txt` | Rebuild spec that embeds server source verbatim — regenerate the `FILE:` sections when server files change |
