# IA Film Rater

A React + Flask + SQLite web application for rating films from the Internet Archive
collection **2026-public-domain-day-film-contest**.

## Overview

- Users log in and rate **one film at a time**
- Films are scored across multiple criteria using a table/grid UI
- Admin users can sync the Internet Archive collection and export ratings as CSV
- Authentication is **session-based** (cookies), not token-based


## Tech Stack

- Client: React + Vite
- Server: Flask (Blueprints)
- Database: SQLite
- Auth: Cookie-based sessions

## Authentication

### Login / Logout

- `POST /api/auth/login`
- `POST /api/auth/logout`
- `POST /api/auth/register`
- `GET /api/me`

Sessions are stored via cookies. Client requests must include:
```js
fetch(url, { credentials: "include" })
```

### Admin Users

Admins are users with `users.is_admin = true` in the database.

There is no environment variable, token, or header for admin access.

## Rating Flow

1. Client requests next unrated film:
   - `GET /api/films/next`
2. Client loads criteria:
   - `GET /api/criteria`
3. User enters scores in a criteria grid
4. Client submits:
   - `POST /api/films/<identifier>/ratings`
   - Payload:
     ```json
     {
       "scores": { "criterion_key": 1 }
     }
     ```
5. On success, next film is automatically loaded

## Admin Endpoints

- `POST /api/admin/sync`
  - Syncs films from the Internet Archive collection
- `GET /api/admin/ratings.csv`
  - Exports all ratings

## Running Locally

### Server

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m server.app
```

### Client

```bash
cd client
npm install
npm run dev
```

The client dev server proxies API requests to the Flask server.

## Notes

- The rater UI is intentionally **single-film, single-user**
- There is no batch rating or multi-film comparison UI
- Canonical project instructions live in `RECREATE_WITH_CHATGPT.txt`