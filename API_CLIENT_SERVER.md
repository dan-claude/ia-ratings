# Client–Server API Contract (Binding)

This document defines the **binding API contract** between the client (React/Vite)
and the server (Flask). A change is invalid if the implementation diverges from
this contract without updating this file.

All endpoints are rooted at `/api` and use **session cookies** (`credentials: include`).

## Conventions (Binding)

- All JSON is UTF-8.
- Error responses use JSON: `{ "error": "message" }` with an appropriate HTTP status.
- Film objects ALWAYS include `description` (empty string if unknown/missing).
- The client MUST treat description as **plain text** (no HTML rendering).

---

## Health

### GET /api/health
Response 200:
```json
{ "ok": true }
```

---

## Auth (session-based)

### POST /api/auth/register
Creates a user and logs them in (sets session cookie).

Request JSON:
```json
{ "email": "string", "password": "string" }
```

Response 200:
```json
{ "ok": true }
```

Errors:
- 400 `{ "error": "..." }` (validation)
- 409 `{ "error": "..." }` (already exists)

### POST /api/auth/login
Logs in (sets session cookie).

Request JSON:
```json
{ "email": "string", "password": "string" }
```

Response 200:
```json
{ "ok": true }
```

Errors:
- 400 `{ "error": "..." }` (validation)
- 401 `{ "error": "..." }` (bad credentials)

### POST /api/auth/logout
Clears the session.

Response 200:
```json
{ "ok": true }
```

### GET /api/me
Returns the currently authenticated user.

Response 200:
```json
{
  "id": 1,
  "email": "judge1@example.com",
  "created_at": "2026-01-01T00:00:00Z",
  "is_admin": false
}
```

Errors:
- 401 `{ "error": "Not logged in" }`

---

## Criteria

### GET /api/criteria
Returns active scoring criteria for the logged-in user.

Response 200:
```json
[
  { "key": "originality", "label": "Originality", "min": 1, "max": 5, "sortOrder": 10, "active": 1 }
]
```

Errors:
- 401 `{ "error": "Not logged in" }`

---

## Films

### GET /api/films/next
Returns the next unrated film for the logged-in user.

Response 200:
```json
{
  "identifier": "example_film_1923",
  "title": "Example Public Domain Film",
  "description": "Line one.\n\nLine two.",
  "embedUrl": "https://archive.org/embed/example_film_1923"
}
```

Errors:
- 401 `{ "error": "Not logged in" }`
- 404 `{ "error": "No unrated films left (did you sync?)" }`

### GET /api/films/<identifier>
Returns a specific film by identifier.

Response 200:
```json
{
  "identifier": "example_film_1923",
  "title": "Example Public Domain Film",
  "description": "Line one.\n\nLine two.",
  "embedUrl": "https://archive.org/embed/example_film_1923"
}
```

Errors:
- 401 `{ "error": "Not logged in" }`
- 404 `{ "error": "Film not found" }`

---

## Ratings

### POST /api/films/<identifier>/ratings
Submit scores for the current user for a film.

Request JSON:
```json
{
  "scores": {
    "<criteria_key>": 1
  }
}
```

Response 200:
```json
{ "ok": true }
```

Errors:
- 400 `{ "error": "..." }` (invalid payload / out-of-range / missing criteria)
- 401 `{ "error": "Not logged in" }`
- 404 `{ "error": "Film not found" }`

---

## Admin

### POST /api/admin/sync
(Admin only) Sync films from Internet Archive into the database.

Response 200:
```json
{ "ok": true, "added": 123, "synced": 123 }
```

Errors:
- 401 `{ "error": "Not logged in" }`
- 403 `{ "error": "Forbidden" }`

### GET /api/admin/ratings.csv
(Admin only) Download CSV export of all ratings.

Response 200:
- Content-Type: `text/csv; charset=utf-8`
- Content-Disposition: attachment; filename="ratings.csv"

Errors:
- 401 `{ "error": "Not logged in" }`
- 403 `{ "error": "Forbidden" }`

---

## Notes on client usage (informative)

The client currently calls:
- `/api/auth/register`, `/api/auth/login`, `/api/auth/logout`, `/api/me`
- `/api/criteria`
- `/api/films/next`
- `/api/films/<identifier>/ratings`
- `/api/admin/sync` (admin users)
