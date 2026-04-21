# IA Film Rater

React + Flask + SQLite app for rating public-domain films from the Internet Archive collection `2026-public-domain-day-film-contest`.

## Architecture

- **Client:** `client/src/App.jsx` — single-file React app, Vite, no component library
- **Server:** Flask app-factory (`server/app.py`), organized as routes → services → repositories
- **DB:** SQLite at `server/app.db` (path overridable via `DB_PATH` env var)
- **Auth:** Cookie-based sessions; two schemes (see below); admin access via `users.is_admin` column

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
| `ia` | Username + password proxied to `archive.org/services/xauthn/`; account auto-created on first login with synthesised email `{username}@users.archive.org` | Not supported |
| `local` | Email + bcrypt password stored locally | Supported via `/api/auth/register` |

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `server/app.db` | Path to SQLite database file |
| `SESSION_SECRET` | *(insecure dev default)* | Flask session signing key — **must be set in production** |
| `AUTH_SCHEME` | `ia` | Auth scheme: `ia` or `local` |
| `FLASK_DEBUG` | `0` | Set to `1` to enable Werkzeug debugger (dev only) |
| `RATELIMIT_STORAGE_URI` | `memory://` | Flask-Limiter storage; set to `redis://...` for multi-instance |
| `PORT` | `5000` | HTTP port (used by Railway via Dockerfile CMD) |

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

## Deployment

### Hosting: Railway

- **Project:** `ia-ratings` on [railway.app](https://railway.app)
- **Production URL:** `https://web-production-4edf1.up.railway.app`
- **Builder:** Dockerfile (multi-stage — Node builds client, Python runs server)
- **Volume:** `/data` mounted at Railway; `DB_PATH=/data/app.db` env var points the app at it
- **Config file:** `railway.toml` — specifies Dockerfile builder, healthcheck at `/api/health`

Key Railway env vars to set in the Railway dashboard:
- `SESSION_SECRET` — random secret, keep private
- `DB_PATH` — `/data/app.db` (matches the mounted volume)
- `AUTH_SCHEME` — `ia` (production default)

### CI/CD: GitHub Actions (`.github/workflows/ci.yml`)

On every push to `main` and on pull requests:

1. **test** — installs Python deps, runs `make test`
2. **build-client** — installs Node deps, runs `npm run build` in `client/`
3. **deploy** *(main branch pushes only)* — runs `railway up --detach` using the `RAILWAY_TOKEN` repository secret

To enable auto-deploy, add `RAILWAY_TOKEN` as a GitHub Actions secret:
- Railway dashboard → Project settings → Tokens → Create token
- GitHub repo → Settings → Secrets → Actions → `RAILWAY_TOKEN`

### Dockerfile

Multi-stage build to avoid Python version conflicts:

1. `node:20-slim` stage — builds the React client (`npm run build`)
2. `python:3.12-slim` stage — installs Python deps, copies server code and built client `dist/`

### Manual redeploy

Push to `main` triggers CI → auto-deploy via Railway. To force a redeploy without a code change:

```bash
railway up --detach   # from repo root, with RAILWAY_TOKEN or railway login
```

## Key API endpoints

### Public
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check (used by Railway) |
| GET | `/api/config` | Returns `{"auth_scheme": "ia"\|"local"}` |
| POST | `/api/auth/login` | Login |
| POST | `/api/auth/register` | Register (local auth only) |
| POST | `/api/auth/logout` | Logout |
| GET | `/api/me` | Current user info |
| GET | `/api/criteria` | Rating criteria list |
| GET | `/api/films/next` | Next unrated film for current user |
| POST | `/api/films/<id>/ratings` | Submit scores (`{"scores": {"key": int}}`) |

### Admin only (`is_admin=1` required)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/admin/sync` | Sync films from Internet Archive |
| GET | `/api/admin/ratings.csv` | Export all ratings |
| GET | `/api/admin/criteria` | List all criteria (incl. inactive) |
| POST | `/api/admin/criteria` | Create criterion |
| PUT | `/api/admin/criteria/<id>` | Update criterion |
| GET | `/api/admin/db/tables` | Table row counts |
| GET | `/api/admin/db/schema` | CREATE TABLE statements |
| GET | `/api/admin/db/<table>` | Dump table rows (`order_by`, `limit`, `offset` params) |
| GET | `/api/admin/db/backup` | Download full DB as versioned JSON |
| POST | `/api/admin/db/restore` | Restore DB from a backup JSON |
| POST | `/api/admin/users/<id>/make-admin` | Promote user to admin |
| POST | `/api/admin/users/<id>/revoke-admin` | Revoke admin from user |

## Admin tools

`tools/print_db.py` — local CLI for inspecting/modifying the SQLite DB directly:

```bash
python tools/print_db.py --table users
python tools/print_db.py --table films --limit 10 --order-by "id DESC"
python tools/print_db.py --make-admin user@example.com   # local DB only
```

> Note: `railway run` executes locally with Railway env vars injected but **cannot** access the Railway volume (`/data/app.db`). Use the admin API endpoints or the admin UI to inspect/modify the production database.
