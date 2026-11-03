# Client–Server API Contract (Binding)

This document defines the **binding API contract** between the client (React/Vite)
and the server (Flask). A change is invalid if the implementation diverges from
this contract without updating this file.

Last verified against the code: 2026-11-03 (version 1.2.0).

## Conventions (Binding)

- All endpoints are rooted at `/api`. Every other path serves the built React app
  (`client/dist`), falling back to `index.html` for client-side routes.
- Authentication uses a **session cookie**; the client sends
  `fetch(url, { credentials: "include" })`.
- All JSON is UTF-8.
- Error responses are JSON `{ "error": "message" }` with an appropriate HTTP status.
- Unhandled server errors return 500
  `{ "ok": false, "error": "Internal Server Error", "request_id": "<id>" }`.
- Every response carries an `X-Request-Id` header matching the server log line.
- Film objects always include the `description` key. Its value is plain text, or
  `null` when archive.org has no description.
- The client MUST treat `description` as **plain text** (no HTML rendering). It
  may turn bare URLs into links.

Auth requirement legend: **public**, **user** (any logged-in user; otherwise
401 `{ "error": "Not logged in" }`), **admin** (`users.is_admin = 1`; 401 if not
logged in, 403 `{ "error": "Forbidden" }` if not an admin).

---

## Health and config

### GET /api/health — public
Used by the Railway health check.
```json
{ "ok": true }
```

### GET /api/config — public
Tells the client which login form to show.
```json
{ "auth_scheme": "ia" }
```
`auth_scheme` is `"ia"` (archive.org login) or `"local"` (email/password).

---

## Auth (session-based)

`login` and `register` are rate-limited per client IP to
**10 per minute and 50 per hour**. Over the limit the server returns 429
(Flask-Limiter's default response, which is not the JSON error shape).

A successful login or registration clears any existing session and starts a new
one (8-hour lifetime).

### POST /api/auth/login — public

Request body depends on the auth scheme:

| Scheme | Body |
|--------|------|
| `ia` | `{ "username": "archive.org username or email", "password": "string" }` |
| `local` | `{ "email": "string", "password": "string" }` |

In `ia` mode the credentials are checked against
`https://archive.org/services/xauthn/?op=login`. On the first successful login a
local user is created with email `<username>@users.archive.org`.

Response 200:
```json
{ "ok": true }
```

Errors:
- 400 — missing username/email or password
- 401 — bad credentials (in `ia` mode the message is archive.org's reason, or
  `"Could not reach archive.org"`)

### POST /api/auth/register — public, `local` mode only
Creates a user and logs them in.

Request:
```json
{ "email": "string", "password": "string" }
```

Response 200:
```json
{ "ok": true }
```

Errors:
- 400 — validation error, or registration attempted in `ia` mode
- 409 — `"Email already registered"`

### POST /api/auth/logout — public
Clears the session.
```json
{ "ok": true }
```

### GET /api/me — user
```json
{
  "id": 1,
  "email": "judge1@example.com",
  "created_at": "2026-01-01 00:00:00",
  "is_admin": false
}
```
`created_at` is SQLite `datetime('now')` format (UTC, space-separated).

---

## Criteria

### GET /api/criteria — user
Active criteria, ordered by `sortOrder`.
```json
[
  { "key": "originality", "label": "Originality", "min": 1, "max": 5, "sortOrder": 1, "active": 1 }
]
```
Note: the public shape uses `min` / `max` / `sortOrder`. The admin criteria
endpoints below use the raw column names.

---

## Films

Film object:
```json
{
  "identifier": "example_film_1923",
  "title": "Example Public Domain Film",
  "description": "Line one.\n\nLine two.",
  "embedUrl": "https://archive.org/embed/example_film_1923"
}
```

### GET /api/films/next — user
Returns a **random** film from the collection that the current user has not
rated yet.

Errors:
- 404 `{ "error": "No unrated films left (did you sync?)" }`

### GET /api/films/<identifier> — user
Returns one film by its Internet Archive identifier.

Errors:
- 404 `{ "error": "Film not found" }`

---

## Ratings

### POST /api/films/<identifier>/ratings — user
Submits (or replaces) the current user's scores for a film. The rating row and
all scores are written in one transaction.

Request:
```json
{ "scores": { "originality": 4, "use_of_archive_materials": 5 } }
```
Every **active** criterion must be present, each an integer within that
criterion's `min`–`max`. Extra keys are ignored.

Response 200:
```json
{ "ok": true }
```

Errors:
- 400 — `"scores object required"`, `"Missing score for: <key>"`,
  `"Score for <key> must be integer"`, `"Score for <key> must be <min>-<max>"`
- 404 — `"Film not found (sync first)"`

---

## Admin

### POST /api/admin/sync — admin
Fetches every `mediatype:movies` item in the collection from archive.org and
upserts it into `films`, then fetches full HTML descriptions (converted to plain
text) for films that don't have one yet. The request blocks until the sync
finishes, which can take minutes on a first sync.
```json
{ "ok": true, "added": 123, "synced": 123 }
```
`added` and `synced` are the same number: films returned by the collection
search (new and existing).

### GET /api/admin/ratings.csv — admin
CSV download (`Content-Disposition: attachment; filename="ratings.csv"`), newest
first. Columns:

`created_at, user_email, identifier, title, <one column per active criterion key>`

### Criteria management

#### GET /api/admin/criteria — admin
All criteria, including inactive ones, ordered by `sort_order`:
```json
[
  { "id": 1, "key": "originality", "label": "Originality",
    "min_score": 1, "max_score": 5, "sort_order": 1, "active": 1 }
]
```

#### POST /api/admin/criteria — admin
```json
{ "key": "pacing", "label": "Pacing", "min_score": 1, "max_score": 5,
  "sort_order": 3, "active": true }
```
`key` and `label` are required. Defaults: `min_score` 1, `max_score` 5,
`sort_order` 0, `active` true.

Response 201 `{ "ok": true }`. Errors: 400 (missing key/label, non-integer
scores, `min_score >= max_score`), 409 (duplicate key).

#### PUT /api/admin/criteria/<id> — admin
Partial update of `label`, `min_score`, `max_score`, `sort_order`, `active`.
Omitted fields keep their current values. `key` cannot be changed.

Response 200 `{ "ok": true }`. Errors: 400 (empty label,
`min_score >= max_score`), 404 (unknown id).

Deactivating a criterion removes it from `/api/criteria`, from rating validation
and from the CSV export. Existing scores stay in the database.

### User management

#### POST /api/admin/users/<id>/make-admin — admin
#### POST /api/admin/users/<id>/revoke-admin — admin
```json
{ "ok": true, "user_id": 7, "is_admin": true }
```
Errors: 404 (unknown user).

### Database inspection

#### GET /api/admin/db/tables — admin
Row counts per table:
```json
{ "criteria": 2, "films": 140, "rating_scores": 0, "ratings": 0,
  "schema_migrations": 4, "users": 3 }
```

#### GET /api/admin/db/schema — admin
`CREATE TABLE` SQL per table: `{ "users": "CREATE TABLE users (...)", ... }`

#### GET /api/admin/db/<table> — admin
Rows of one table as a JSON array.

Query parameters:
- `order_by` — a column name with optional `ASC`/`DESC` (e.g. `id DESC`); anything else is rejected with 400
- `limit`, `offset` — integers

Special cases: `films` rows include a computed `rating_count`; `users` rows
omit `password_hash` (columns: `id, email, ia_username, is_admin, created_at`).

Errors: 400 (bad `order_by`), 404 `{ "error": "Unknown table: <name>" }`.

### Backup and restore

#### GET /api/admin/db/backup — admin
Downloads the whole database as JSON
(`ia_ratings_backup_<YYYY-MM-DDTHH-MM-SSZ>.json`):
```json
{
  "app": "ia_ratings",
  "format_version": 1,
  "schema_version": 4,
  "exported_at": "2026-11-03T19:00:00Z",
  "tables": { "users": [ { "id": 1, "...": "..." } ], "films": [] }
}
```
The backup includes `password_hash` values. Treat backup files as secrets.

#### POST /api/admin/db/restore — admin, destructive
The request body is a backup file as produced above. In a single transaction,
for each of `schema_migrations, users, criteria, films, ratings, rating_scores`
that is present in the backup, all existing rows are deleted and replaced with
the backup's rows. Tables missing from the backup are left alone.

Response 200:
```json
{ "ok": true, "exported_at": "...", "schema_version": 4,
  "restored": { "users": 3, "films": 140 } }
```
Errors: 400 (not JSON, wrong `app`, unsupported `format_version`, `tables` not
an object, or a column that doesn't exist in the current schema). On error
nothing is changed.

---

## Client usage (informative)

The client (`client/src/App.jsx`) calls:
- `/api/config`, `/api/me`, `/api/auth/login`, `/api/auth/register` (local mode only), `/api/auth/logout`
- `/api/criteria`, `/api/films/next`, `/api/films/<identifier>/ratings`
- Admin panel: `/api/admin/sync`, `/api/admin/ratings.csv`, `/api/admin/criteria`,
  `/api/admin/criteria/<id>`, `/api/admin/users/<id>/make-admin|revoke-admin`,
  `/api/admin/db/tables`, `/api/admin/db/<table>` (including `users?order_by=id`
  for the Users tab), `/api/admin/db/backup`, `/api/admin/db/restore`

The client does not call `/api/films/<identifier>`, `/api/admin/db/schema` or
`/api/health`.
