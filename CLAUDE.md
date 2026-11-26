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



React + Flask + SQLite app for rating the public-domain films submitted to the contest (spreadsheet import; the films are played from archive.org).

> **Branch `major-changes` (in progress, not on `main`).** The app is being rebuilt in steps (plan: `CHANGES_DRAFT.md` in the main checkout, untracked and never committed). **Steps 1 (clean baseline), 2 (login by invite / magic link), 3 (import of the new columns), 4 (distribution and progress views), 5 (the new rating screen), 6 (rankings and the judges' pool), 7 (judge export and final screen) and 8 (dark mode) are done: **all eight planned steps are implemented**, not yet merged or deployed. Production still runs the old app from `main`; a reset procedure must be agreed before this is deployed (an old database is refused at startup).

## Architecture

- **Client:** `client/src/App.jsx` — single-file React app, Vite, no component library; colours live in `client/src/theme.css` as CSS variables for light and dark mode (never hard-code a colour in `App.jsx`: use `var(--…)`)
- **Server:** Flask app-factory (`server/app.py`), organized as routes → services → repositories
- **DB:** SQLite at `server/app.db` (path overridable via `DB_PATH` env var)
- **Auth:** Cookie-based, server-side sessions (see below); roles (`admin`, `reviewer`, `judge`) are columns on `users` (`is_admin`, `is_reviewer`, `is_judge`)

### Server layout

```
server/
  app.py              # app factory + CLI entrypoint
  config.py           # Settings dataclass (reads env vars)
  db.py               # thin SQLite wrapper + schema migrations
  categories.py       # the three rating categories (hard-coded), score range, comment limit
  auth_session.py     # server-side login sessions
  routes/             # Flask blueprints (auth, films, admin, user)
  services/           # business logic (RatingService, SummaryService, ImportService, JobService, InternetArchiveService)
  repositories/       # DB access per entity (users, films, assignments, ratings, sessions)
  models/             # data model classes
```

## Auth and roles

**Login is by magic link only.** An admin invites a person by email (Admin → Users → Invite, `POST /api/admin/users` with email, roles and an optional expiry): the account is created and the admin gets a personal link **once** to pass on (the app sends no email). The old logins (archive.org username/password, local email/password, GitHub OAuth) and the `AUTH_SCHEME` / `GITHUB_*` settings have been **removed**. `users.password_hash` is nullable and unused (reserved in case password registration is added later).

Magic-link details (`server/services/login_link_service.py`, `server/repositories/login_link_repo.py`, `login_links` table): the link is `<origin>/signin#<secret>`. The secret is in the URL **fragment** so it never reaches server logs or Referer headers; opening the page signs nobody in: the client (`/signin` is served by an explicit route in `app.py`, because the static route at `/` 404s unknown paths) shows a **Sign in** button, and only pressing it POSTs `{token}` to `POST /api/auth/signin` (10/min and 50/hour per client, see `TRUSTED_PROXY_HOPS`), then removes the secret from the address bar. Only the SHA-256 of the secret is stored. A link is **reusable** until its `expires_at` (chosen by the admin, default 30 days, a date means end of that day UTC; checked on every use) or until cancelled; each user has at most one non-cancelled link (partial unique index). A **new link cancels the old one**, and issuing or cancelling a link **ends that person's sessions** (except the admin's own current one when acting on themselves). Admin routes: `GET /api/admin/users`, `POST /api/admin/users`, `POST|PUT|DELETE /api/admin/users/<id>/login-link`. A lost link can't be recovered: issue a new one. Unknown, cancelled and expired links all get the same 401 message.

**First admin** (nobody can sign in without an invite): `python tools/print_db.py --invite EMAIL --admin [--roles reviewer,judge] [--days 30]` creates the user (or adds roles to an existing one and re-issues their link) and prints the link; set `PUBLIC_URL` so it prints the full address (otherwise just the `/signin#…` path). It creates the database file if missing.

**Roles.** A user can hold any combination of `admin`, `reviewer` and `judge` (checkboxes in the admin panel → Users; `PUT /api/admin/users/<id>/roles` with `{"roles": [...]}`, which sets the list exactly; an admin can't remove their own admin role). Roles are independent: admin does not imply the others. Only reviewers and judges rate films (`RatingService._can_rate`; admin alone does not), and a user with no role sees no films. `/api/me` returns `is_admin`, `is_reviewer`, `is_judge` and `roles`. Role names ↔ columns live in `ROLE_COLUMNS` in `server/repositories/user_repo.py`; to add a role add a column (schema change) and an entry there. Emails are stored lower-case.

**Ratings and assignments.** The three categories (`aesthetic`, `sound`, `appeal`, each 1–10, with descriptions and 1/5/10 anchor labels) are constants in `server/categories.py`; `GET /api/categories` serves them. A person only sees films **assigned** to them (`assignments`, status `assigned` → `seen` → `rated`); `GET /api/films/next` shows a film they opened but didn't submit first, else a random unopened one. A rating (3 scores + optional comment ≤ 1000 chars) is **final**: one row per person per film, created on submit together with the move to `rated`; a second submit is 409. A person's score for a film is the sum of their category scores (3–30); a film's score will be the average of its reviewers' scores (step 6).

**Rating screen** (`client/src/App.jsx`, `App()`): title linking to the archive.org item with "by <creator>" (no identifier shown) → description → public-domain works → AI disclosure → archive.org player → one block per category (name, bold description, 1–10 buttons only, the 1/5/10 labels) → running total ("10 + 5 + 10 = 25", shown once all three are chosen) → "Comments on Film (May be used in presentation)" box (1000 chars, optional) → Submit & Next, which first asks "Are you sure? Scores cannot be changed". The old film and its scores stay on screen (controls disabled) until the next film has loaded, then film, scores and comment change in one render, so scores never flash empty. A 409 on submit (already submitted elsewhere) just moves on with a notice. No usernames or timestamps are shown. Opening `/signin#…` while signed in shows the Sign in button too (to switch accounts).

**Rankings and the judges' pool** (`server/services/ranking_service.py`, admin panel → Rankings). A film's score is the average of its reviewers' scores; only `round = 'reviewers'` ratings count (`RatingRepository.review_totals`), so judges never move the ranking. Averages are compared exactly as `Fraction(total, reviews)` (`_ranked`); equal averages share a rank (1, 2, 2, 4), alphabetical within it. Previewing or confirming the pool is blocked (409 `reviews_missing`, with the films and counts missing) until every film has ≥ 2 reviewers'-round ratings. Rule: the film at rank N must score strictly higher than rank N+1 (the preview says so and offers the nearest valid counts); the admin can't remove or swap films. Confirming sets `films.in_judges_pool` and gives **every judge every pool film** (`round = 'judges'`, `INSERT OR IGNORE`). **A judge who already reviewed a pool film keeps that assignment and rating and does not rate it again** (owner's decision): the assignment stays `round = 'reviewers'`, and the judge export/final screen (step 7) must take that judge's score for that film from it. The pool can be given again to newly added judges, cleared (unless a judge has rated), and is cleared by the distribution reset. Judges are never shown scores or averages.

**Pages (hash routes).** Reviewers and judges navigate by URL fragment (`parseRoute` in `App.jsx`): `#/` rate the next film, `#/films` **My films** (every assigned film as a link `#/film/<identifier>` with its status unseen / seen / rated; "only films I haven't rated" filter), `#/film/<id>` one particular film (opening it marks it seen; a rated film opens read-only with the person's own scores and comment), `#/results` a judge's ranked list. The top bar has Rate / My films / My ranked films buttons. Data for a page is loaded by one effect keyed on person + page (`loadedFor`); after a submit from a listed film the client carries on with the next film and returns to `#/`. The next film on `#/` is still chosen by the server (opened-but-unfinished first, else random); only login/`#/` calls `/api/films/next`, which is what marks a film seen there. `/signin` is the only real path route.

**Dark mode.** A Moon / Sun button (`ThemeToggle`, top bar and the sign-in pages) switches `data-theme` on `<html>`; the choice is kept in `localStorage` (`theme`), and a first visit follows the device (`prefers-color-scheme`). A small script in `client/index.html` sets the theme before the first paint (no flash). All colours are variables in `client/src/theme.css`; `color-scheme` is set so native controls follow the theme. The client also resets all per-person state when the signed-in person changes (opening another person's link in the same browser).

**Judge results** (`RatingService.judge_results`, `GET /api/me/results[.csv]`, judges only). One row per pool film the judge has rated (including one they rated as a reviewer): rank, title, creator, the three scores, total, comment; highest total first, equal totals share a rank and are alphabetical by title (D24). Only the caller's own data is returned. The client shows it automatically after the judge's last submit (if a pool exists) and from the top-bar "My ranked films" button, with a CSV download.

**Distribution and progress** (`server/services/distribution_service.py`, admin panel → Reviews). `POST /api/admin/distribute` gives every film to `REVIEWS_PER_FILM` (2) different users with the reviewer role: films are shuffled and each goes to the reviewers with the fewest films so far (random tie-break), so loads differ by at most one. It runs once (409 if any assignment exists); `POST /api/admin/distribute/reset` (typed `RESET`) deletes all assignments **and ratings** and clears `in_judges_pool`, because a rating without its assignment would block handing the film out again. Admins can also hand-assign / un-assign (`/api/admin/assignments`; not once rated). A film is *fully reviewed* when ≥ 2 assignments are `rated`; `GET /api/admin/progress` returns the overall counter, per-person status counts and per-film assignees (the step 6 pool preview reads the same numbers).

**Sessions.** A login creates a row in `user_sessions` (migration v9; only the SHA-256 of a random session id is stored) and puts `user_id` + `sid` in the signed cookie. A request is logged in only if that server-side session exists and is under 8 hours old (`server/auth_session.py`: `start_session` / `end_session` / `current_user_id`; every route's auth check goes through `current_user_id`). So logout really revokes a copied cookie, and a backup **restore deletes every session and magic link** (it replaces `users`, so ids could point at different people) except the restoring admin's own session when their account (same id and email) survives. Roles are read from the database on every request, never from the cookie. Cookies: `HttpOnly`, `SameSite=Lax`, `Secure` except in the local dev entrypoint. `user_sessions` and `login_links` are deliberately *not* in `_RESTORE_ORDER`, and are hidden from the DB browser, schema view and backups (`_HIDDEN_TABLES` in `routes/admin.py`).

**Request size limits.** `MAX_CONTENT_LENGTH` is 1 MB (`server/app.py`: `MAX_BODY_BYTES`); bigger bodies get 413 `{"error": "Request body is too large"}` before any parsing, even on `/api/auth/login`. The admin CSV import routes allow 16 MB and restore 64 MB (`_LARGE_BODY_LIMITS`, set per request in a `before_request`).

**CSV exports** (`ratings.csv`) pass every text cell through `csv_safe` (`server/services/csv_utils.py`): cells starting with `=`, `+`, `-`, `@`, tab or CR get a leading `'` so spreadsheet apps don't run them as formulas (film titles and comments come from outside the app).

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `server/app.db` | Path to SQLite database file |
| `SESSION_SECRET` | *(none)* | Flask session signing key — **required**: `create_app()` raises `RuntimeError` (so gunicorn won't boot) if it is unset or equals the public dev default. Only the local dev entrypoint (`python -m server.app`, `create_app(dev=True)`) may omit it: it uses a random per-process secret, so sessions reset on restart |
| `TRUSTED_PROXY_HOPS` | `0` | Number of reverse proxies in front of the app; that many hops of `X-Forwarded-For`/`-Proto` are trusted (Werkzeug `ProxyFix`) so the sign-in rate limit is per real client. The Dockerfile sets `1` for Railway. Leave `0` with no proxy, or the header could be spoofed to dodge the limit |
| `FLASK_DEBUG` | `0` | Set to `1` to enable Werkzeug debugger (dev only) |
| `RATELIMIT_STORAGE_URI` | `memory://` | Flask-Limiter storage; set to `redis://...` for multi-instance |
| `PORT` | `5000` | HTTP port gunicorn binds to in the Docker image (Railway sets it) |
| `LEGACY_DB` | *(unset)* | Set to `move-aside` once, when deploying the new schema over the old production database: an old-style `DB_PATH` file is **renamed** to `<DB_PATH>.legacy-<UTC time>` (with its `-wal`/`-shm`; never deleted) and a fresh database is created. Harmless if left set (it only acts on an old-style file); any other value is ignored and the old file is refused |
| `PUBLIC_URL` | *(unset)* | Site address (e.g. `https://ratings.example.org`) used only by `tools/print_db.py --invite` to print full links; the admin panel builds links from the browser's address |
| `LOG_LEVEL` | `INFO` | Server log level (`server/logging_config.py`) |
| `FLASK_RUN_HOST` / `FLASK_RUN_PORT` | `127.0.0.1` / `5000` | Defaults for `--host` / `--port` when running `python -m server.app`. Local only by default; `--debug` is refused on a non-local host (the Werkzeug debugger runs arbitrary code) |
| `VITE_LOG_LEVEL` | `info` | Client console log level (`client/src/logger.ts`) |

`Settings` in `server/config.py` reads env vars via `default_factory`, i.e. each time `load_settings()` / `Settings()` is called. Don't go back to plain `= os.environ.get(...)` defaults: those are frozen at import time and break per-test DBs.

## Running locally

### Server
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
make dev          # or: PYTHONPATH=. python -m server.app
                  # binds 127.0.0.1 only; no SESSION_SECRET needed locally (random per run)
```

### Client (dev, with proxy to Flask)
```bash
cd client
npm install
npm run dev
```

`client/vite.config.js` proxies `/api` to the `API_URL` environment variable (a base URL such as `http://127.0.0.1:5002` or `https://host`; also readable from `client/.env.local`), default `http://127.0.0.1:5001`. Flask defaults to 5000 but falls back to the next free port (on macOS, 5000 is usually taken by AirPlay, so it lands on 5001). `.claude/launch.json` also starts Flask on 5001.

### Client (production build, served by Flask)
```bash
python -m server.app --with-client
```

## Testing

```bash
pip install -r server/requirements-dev.txt
make test         # or: PYTHONPATH=. pytest -q
```

There is no password login, so tests create users with `server/tests/helpers.py` (`make_user(app, email, roles)` returns a logged-in test client and the user id; `seed_film`, `assign`).

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
- `SESSION_SECRET` — **required**; a missing one now stops the app booting (deploy fails its health check and Railway keeps the previous deployment). Random secret: `python3 -c "import secrets; print(secrets.token_hex(32))"`, keep private
- `TRUSTED_PROXY_HOPS` — set to `1` by the Dockerfile; don't override
- `LEGACY_DB` — one-time, only for the move to the new app; see **Resetting production for the new schema** below. Remove it afterwards.
- `DB_PATH` — `/data/app.db`
- `PORT` is provided by Railway; don't set it

If Railway's service settings offer a "wait for CI" option, enable it so a failing test run blocks the deploy.

### CI: GitHub Actions (`.github/workflows/ci.yml`)

On every push to `main` and on pull requests:

1. **test** — installs Python deps, runs `make test`
2. **build-client** — runs `npm ci && npm run build` in `client/`

The workflow has `permissions: contents: read`, and each `uses:` is pinned to a full commit SHA (the comment names the tag). To update an action, look up the new tag's commit (`git ls-remote https://github.com/actions/checkout 'refs/tags/v4*'`).

### Dockerfile

Multi-stage build to avoid Python version conflicts:

1. `node:20-slim` stage — builds the React client (`npm run build`)
2. `python:3.12-slim` stage — installs Python deps, copies server code and built client `dist/`

**The container runs as an unprivileged user (`app`, uid 10001).** It has to *start* as root so `docker-entrypoint.sh` can `chown` the Railway volume (mounted at `/data`, `DB_PATH=/data/app.db`) and then drop privileges with `setpriv`; if chown or setpriv isn't possible it logs a warning and keeps running as root rather than failing the deploy. Don't add `USER app` to the Dockerfile (the chown would stop working) or set `RAILWAY_RUN_UID`. The client is built with `npm ci` from the committed lockfile.

`tools/` is copied into the image so `print_db.py` can be run in production via `railway ssh` (they pick up `DB_PATH=/data/app.db` from the service variables).

Production runs under **gunicorn** (pinned in `server/requirements.txt`), not Flask's dev server:

```
gunicorn --workers 1 --threads 8 --timeout 0 --bind 0.0.0.0:${PORT:-5000} "server.app:create_app()"
```

- **Keep `--workers 1`.** SQLite writes and the Flask-Limiter `memory://` store assume a single process; more workers would give each its own rate-limit counters and more lock contention. Scale with `--threads`.
- **`--timeout 0`** stops gunicorn killing a worker during long requests; the title lookup after an import can take minutes (it runs in a background thread, so the request itself returns at once).
- `python -m server.app` (with its port-fallback and `--with-client` conveniences) is for local development only. Under gunicorn, settings come from env vars only.

### Resetting production for the new schema (one time)

The new app refuses an old-style database (`LegacyDatabaseError`), and Railway then keeps the previous deployment running. To switch over **without deleting anything**:

1. In the old app's admin panel, download a **Backup** (JSON) while the old version still runs, and keep it safe (it contains old user data).
2. In Railway, set the service variable `LEGACY_DB=move-aside` and `PUBLIC_URL=https://<the site>`.
3. Deploy `main` (after the owner agrees to merge `major-changes`). On first start the app renames `/data/app.db` (+ `-wal`, `-shm`) to `/data/app.db.legacy-<time>` and creates a fresh database. The old data stays on the volume; delete the `.legacy-*` files later with `railway ssh` when it is certain they are not needed (they take volume space).
4. Create the first admin: `railway ssh`, then `setpriv --reuid=app --regid=app --init-groups python tools/print_db.py --invite NAME@example.com --admin` (run as `app`, see below). It prints the sign-in link; open it and press **Sign in**.
5. Remove the `LEGACY_DB` variable (optional; it does nothing once the database is new). Then import the spreadsheet (Import tab), invite reviewers and judges (Users tab), and press **Distribute films** (Reviews tab).

### Redeploy and production shell

Push to `main` → Railway rebuilds. To redeploy without a code change, use **Redeploy** on the latest deployment in the Railway dashboard.

For one-off production DB work (e.g. creating the first admin), use the Railway CLI's SSH and the bundled tools:

```bash
brew install railway               # or: npm install -g @railway/cli
railway login && railway link      # pick the ia-ratings project and the web service
railway ssh
# inside the container (cwd /app, DB_PATH already set):
python tools/print_db.py --table users
python tools/print_db.py --make-admin NAME@example.com
```

The `railway ssh` shell is root, but the server runs as `app`. Run anything that **writes** the database as `app` too, or SQLite's `-wal`/`-shm` files end up root-owned and the server can't write until the next restart re-chowns them:

```bash
setpriv --reuid=app --regid=app --init-groups python tools/print_db.py --make-admin NAME@example.com
```

## Database

**One clean baseline schema** (`server/db.py`, `SCHEMA_VERSION = 1`); the old migrations v1–v9 were deleted. A new database file gets the schema at startup. An **old-style database is refused**: `Database()` raises `LegacyDatabaseError` (the app won't boot; `python -m server.app` prints the message) when the file has `criteria` / `film_notes` / `app_settings`, no `schema_migrations`, a schema version other than the current one, or an old `users` layout. The message says to delete the file (and `-wal` / `-shm`). To change the schema later, bump `SCHEMA_VERSION` and add an upgrade step for the previous version.

Tables:

| Table | Holds |
|-------|-------|
| `schema_migrations` | `version` rows (just `1` for now) |
| `users` | `email` (unique, lower-case), nullable `password_hash` (unused), `is_admin`, `is_reviewer`, `is_judge`, `created_at` |
| `login_links` | Magic links: `token_hash` (SHA-256 only), `user_id`, `created_at`, `expires_at`, `revoked_at`; a partial unique index allows one non-revoked link per user |
| `user_sessions` | Server-side login sessions (SHA-256 of the id) |
| `films` | `ia_identifier` (unique), `title`, `creator`, `description`, `public_domain_works`, `ai_disclosure`, `in_judges_pool`, `updated_at` |
| `assignments` | Primary key `(user_id, film_id)`; `round` `reviewers`/`judges` (CHECK); `status` `assigned`/`seen`/`rated` (CHECK), `assigned_at`, `seen_at`, `rated_at` |
| `ratings` | One row per `(user_id, film_id)`, created on submit; `comment` (CHECK ≤ 1000 chars), `created_at` |
| `rating_scores` | `(rating_id, category)` → `score` (CHECK 1–10); `category` is a key from `server/categories.py` |

There are **no seed rows**, no collections and no criteria table. When adding a table, add it to `_RESTORE_ORDER` in `routes/admin.py` (and to `_DEPENDENT_TABLES` if it points at users/films) so backups restore it, unless it is internal like `user_sessions`/`login_links` (then add it to `_HIDDEN_TABLES`). Backups use `BACKUP_FORMAT_VERSION = 2` and refuse a different `schema_version`.

Films come **only** from the admin's CSV import (`server/services/import_service.py`; admin panel → Import); there is no archive.org sync and no collection setting. The importer accepts **only** `archive.org/details|embed|download/<id>` links (exact host `archive.org`/`www.archive.org`); rows without one are skipped and reported; a film is identified by its identifier alone. The column mapping (by column *index*; `MAPPING_FIELDS` in the importer) covers link, title, creator, description, public-domain works, AI disclosure and an optional **eligible** column: with it mapped only explicit "yes" rows are imported (no / blank / unclear are skipped and reported, ineligible rows are never loaded); an import never deletes films, so a loaded film whose row now says no stays and is flagged as `ineligible_in_database`. Re-importing uses the usual skip/update choice (blank cells never erase stored data). Missing titles can be looked up from archive.org by a background job (`JobService.start_job("titles", …)`, status at `GET /api/admin/jobs/status`); one background job runs at a time, and `import`/`empty` return 409 while one runs. Film data is **never loaded automatically** (not at startup): with zero films, `GET /api/films/next` answers 404 `code: "no_films"`. The job status is in-process memory, which is why production keeps `--workers 1`.

## Key API endpoints

Full request/response shapes are in `API_CLIENT_SERVER.md`.

### Public
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check (used by Railway) |
| POST | `/api/auth/signin` | Sign in with a magic link's secret `{"token"}` (rate-limited; 401 if invalid, cancelled or expired) |
| POST | `/api/auth/logout` | Logout |

### Logged-in users
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/me` | Current user info and roles |
| GET | `/api/categories` | The three fixed rating categories |
| GET | `/api/films/next` | The person's next assigned film (opened-but-unfinished first, else random); 404 with `code` `no_role`/`no_films`/`no_assignments`/`all_rated` |
| GET | `/api/me/results` (+ `.csv`) | **Judge only** (403 otherwise): the caller's own ranked pool films with their scores, total and comment (`complete` when all rated); `my_ratings.csv` export |
| GET | `/api/me/films` | The caller's assigned films with status (`assigned`/`seen`/`rated`), alphabetical; 403 without the reviewer/judge role; doesn't mark anything seen |
| GET | `/api/films/<id>` | One of the person's own films by IA identifier |
| POST | `/api/films/<id>/ratings` | Submit final scores and comment (`{"scores": {"aesthetic": int, "sound": int, "appeal": int}, "comment": str}`); 409 if already submitted |

### Admin only (`is_admin=1` required)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/jobs/status` | Background job progress (title lookup): `state` idle/running/done/error, `done`/`total`, `film_count` |
| POST | `/api/admin/import/preview` | Read a CSV (`{"csv_text"}`): headers, row count, sample rows, suggested column mapping. Saves nothing |
| POST | `/api/admin/import` | Import films from a CSV with a column `mapping`; `dry_run` reports only; real import needs `on_existing` `"skip"`/`"update"`; optional `lookup_titles`; only archive.org item links are imported |
| GET | `/api/admin/progress` | Overall counter (fully reviewed / still needing reviews), per-person assigned/seen/rated counts, per-film assignees with status |
| POST | `/api/admin/distribute` | Give every film to 2 different reviewers at random (even load); once only: 409 `already_distributed` / `no_films` / `too_few_reviewers` |
| POST | `/api/admin/distribute/reset` | **Destructive.** Delete all assignments, ratings and scores and clear the judges' pool; body `{"confirm": "RESET"}` |
| POST | `/api/admin/assignments` | Hand one film to a reviewer or judge `{"user_id", "identifier"}` |
| DELETE | `/api/admin/assignments/<user_id>/<identifier>` | Take an unrated film off a person's list (409 if rated) |
| GET | `/api/admin/rankings` | Every film with its reviewers' average (exact `total`/`reviews`, display `average`), rank and all details; `.csv` variant `rankings.csv` |
| GET | `/api/admin/judges-pool/preview?count=N` | Ranked top N for the judges' pool with the tie check; 409 `reviews_missing` (lists films missing reviews) until every film has both reviews |
| POST | `/api/admin/judges-pool` | Confirm the pool `{"count"}`: sets `in_judges_pool`, gives every film to every judge; 409 `tie_at_cutoff` / `pool_already_set` / `reviews_missing` |
| GET/DELETE | `/api/admin/judges-pool` | Pool + judges' progress / clear it (409 `judges_have_rated`) |
| POST | `/api/admin/judges-pool/assign` | Give the pool to every judge again (idempotent) |
| POST | `/api/admin/db/empty` | **Destructive.** Delete all films, assignments and ratings (keeps users); body `{"confirm": "EMPTY"}`; 409 while a job runs |
| GET | `/api/admin/ratings.csv` | Export all submitted ratings (scores, total, comment) |
| GET | `/api/admin/db/tables` | Table row counts |
| GET | `/api/admin/db/schema` | CREATE TABLE statements |
| GET | `/api/admin/db/<table>` | Dump table rows (`order_by`, `limit`, `offset` params) |
| GET | `/api/admin/db/backup` | Download full DB as versioned JSON |
| POST | `/api/admin/db/restore` | Restore DB from a backup JSON |
| GET | `/api/admin/users` | Users with roles and sign-in link state (none / active / expired) |
| POST | `/api/admin/users` | Invite: `{"email", "roles", "expires_at"?}` → 201 with the link (shown once) |
| POST | `/api/admin/users/<id>/login-link` | New link (cancels the old one, ends the person's logins) |
| PUT | `/api/admin/users/<id>/login-link` | Change the active link's expiry `{"expires_at"}` |
| DELETE | `/api/admin/users/<id>/login-link` | Cancel the link and end their logins |
| PUT | `/api/admin/users/<id>/roles` | Set a user's roles exactly (`{"roles": ["admin","reviewer","judge"]}`) |
| POST | `/api/admin/users/<id>/make-admin` | Promote user to admin |
| POST | `/api/admin/users/<id>/revoke-admin` | Revoke admin from user |

## Admin tools

`tools/print_db.py` — local CLI for inspecting/modifying the SQLite DB directly:

```bash
python tools/print_db.py --table users
python tools/print_db.py --table films --limit 10 --order-by "id DESC"
python tools/print_db.py --make-admin user@example.com   # the user must already exist
```

`--invite EMAIL [--admin] [--roles a,b] [--days N]` — create a user / re-issue their magic link and print it (the way to create the first admin; see Auth and roles).


> Note: `railway run` executes locally with Railway env vars injected but **cannot** access the Railway volume (`/data/app.db`). Use the admin UI/API, or `railway ssh` + `tools/print_db.py` (see Deployment) for the production database.

## Documentation files

| File | Purpose |
|------|---------|
| `README.md` | Human-facing overview, local setup, config |
| `API_CLIENT_SERVER.md` | Binding API contract — update with any route change |
| `CHANGELOG.md` | Version history |
