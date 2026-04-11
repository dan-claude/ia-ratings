# IA Film Rater

React + Flask + SQLite app for rating public-domain films from the Internet Archive collection `2026-public-domain-day-film-contest`.

## Architecture

- **Client:** `client/src/App.jsx` — single-file React app, Vite, no component library
- **Server:** Flask app-factory (`server/app.py`), organized as routes → services → repositories
- **DB:** SQLite at `server/app.db` (path overridable via `DB_PATH` env var)
- **Auth:** Cookie-based sessions; admin access is determined by `users.is_admin` column (no tokens or env vars)

### Server layout

```
server/
  app.py              # app factory + entrypoint
  config.py           # Settings dataclass (env vars: DB_PATH, SESSION_SECRET)
  db.py               # thin SQLite wrapper
  routes/             # Flask blueprints (auth, films, admin, user)
  services/           # business logic (AuthService, RatingService, SummaryService, InternetArchiveService)
  repositories/       # DB access per entity (users, films, criteria, ratings)
  models/             # data model classes
```

## Running locally

### Server
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
make dev          # or: PYTHONPATH=. python -m server.app
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

## Key API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/login` | Login |
| POST | `/api/auth/register` | Register |
| POST | `/api/auth/logout` | Logout |
| GET | `/api/me` | Current user |
| GET | `/api/films/next` | Next unrated film for current user |
| POST | `/api/films/<id>/ratings` | Submit scores (`{"scores": {"key": int}}`) |
| GET | `/api/criteria` | Rating criteria list |
| POST | `/api/admin/sync` | Sync films from Internet Archive |
| GET | `/api/admin/ratings.csv` | Export all ratings |
