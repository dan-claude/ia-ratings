# Client–Server API Contract (Binding)

This document defines the **binding API contract** between the client (React/Vite)
and the server (Flask). A change is invalid if the implementation diverges from
this contract without updating this file.

Last verified against the code: 2026-11-25 (`major-changes` branch, step 2: login by
invite). **Work in progress:** the contract below describes the app after step 2.
Film distribution and the ranking/judge screens arrive in later steps and will be
added here as they land.

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
- Request bodies are limited to **1 MB** (admin CSV import 16 MB, backup restore
  64 MB). Larger ones get 413 `{ "error": "Request body is too large" }`.
- Film text fields (`description`, `publicDomainWorks`, `aiDisclosure`, `creator`)
  are **plain text** (or `null`). The client MUST NOT render them as HTML. It may
  turn bare URLs into links.

Auth requirement legend: **public**, **user** (any logged-in user; otherwise
401 `{ "error": "Not logged in" }`), **admin** (`users.is_admin = 1`; 401 if not
logged in, 403 `{ "error": "Forbidden" }` if not an admin).

**Roles.** A user holds any combination of `admin`, `reviewer` and `judge`
(independent flags). Only reviewers and judges rate films; an admin alone does
not. A user with no role sees no films.

**Sessions.** A login lasts 8 hours and is recorded on the server: a request is
logged in only while that record exists, so `POST /api/auth/logout` invalidates
the session even if the cookie was copied, and a successful
`POST /api/admin/db/restore` ends every session except the restoring admin's own
(kept only if their account, same id and email, is still present afterwards).

---

## Health

### GET /api/health — public
Used by the Railway health check.
```json
{ "ok": true }
```

---

## Sign-in and session

Sign-in is by **magic link** only. An admin invites a person (`POST /api/admin/users`) and
passes them a link of the form `https://<site>/signin#<secret>`. The secret is in the URL
fragment (never sent to the server on page load). The `/signin` page shows a **Sign in**
button, and only pressing it calls `POST /api/auth/signin`. A link can be used repeatedly
until it expires or is cancelled; a new link cancels the old one.

### POST /api/auth/signin — public
Rate-limited per client address to **10 per minute and 50 per hour** (over the limit:
429, Flask-Limiter's default response, which is not the JSON error shape).
```json
{ "token": "<the secret from the link>" }
```
200 `{ "ok": true }` — a fresh session (8 hours) is started, replacing any existing one.

401 `{ "error": "This sign-in link is not valid any more. Ask an administrator for a new one." }`
— the same answer for a missing, unknown, cancelled or expired token (expiry is checked on every use).

### POST /api/auth/logout — public
Clears the session (and its server-side record).
```json
{ "ok": true }
```

### GET /api/me — user
```json
{
  "id": 1,
  "email": "judge1@example.com",
  "created_at": "2026-01-01 00:00:00",
  "is_admin": false,
  "is_reviewer": true,
  "is_judge": false,
  "roles": ["reviewer"]
}
```
`roles` lists the roles the user holds, in the order `admin`, `reviewer`,
`judge`; the `is_*` fields are the same information as booleans.
`created_at` is SQLite `datetime('now')` format (UTC, space-separated).

(There is no password, GitHub or archive.org login, and no `/api/config`.)

---

## Categories

### GET /api/categories — user
The three rating categories, fixed in the code (`server/categories.py`), in display order.
```json
[
  {
    "key": "aesthetic",
    "label": "Aesthetic",
    "description": "Well-executed use of archival material",
    "anchors": { "1": "Mash-Up", "5": "Unique and Well Executed", "10": "Unexpected and Surprising" },
    "min": 1,
    "max": 10
  }
]
```
Keys: `aesthetic`, `sound`, `appeal`. Every score is a whole number `min`–`max`.

---

## Films and ratings

People only ever see films **assigned to them** (assignments are created by the
admin; the distribution button is added in a later step). Each assignment has a
status: `assigned` (handed out, not opened), `seen` (opened) or `rated` (submitted).

Film object:
```json
{
  "identifier": "example_film_1923",
  "title": "Example Public Domain Film",
  "creator": "Sam B",
  "description": "Line one.\n\nLine two.",
  "publicDomainWorks": "Nosferatu (1922)",
  "aiDisclosure": "Suno for the music",
  "archiveUrl": "https://archive.org/details/example_film_1923",
  "embedUrl": "https://archive.org/embed/example_film_1923",
  "status": "seen"
}
```
`title` falls back to the identifier. A film whose status is `rated` also has
`"rating": { "scores": { "aesthetic": 10, "sound": 5, "appeal": 1 }, "comment": "…" }`
(the caller's own submitted rating).

### GET /api/films/next — user
The film to rate next, from the caller's own assignments with status `assigned` or
`seen`: a film they opened but did not submit comes back first (oldest first);
otherwise a **random** unopened one. Returning a film marks it `seen` (first time only).

Errors (all 404, with a machine-readable `code`; they are not failures as such and
the client shows them as notices):
- `no_role` — the user holds neither the reviewer nor the judge role
- `no_films` — there are no films in the database at all
- `no_assignments` — films exist but none is assigned to this user
- `all_rated` — every film assigned to this user has been rated

```json
{ "error": "No films have been assigned to you yet.", "code": "no_assignments" }
```

### GET /api/films/<identifier> — user
One of the caller's own films (marks an unopened one `seen`).

Errors: 404 `{ "error": "Film not found" }` — no such film, not assigned to the
caller, or the caller has no reviewer/judge role.

### POST /api/films/<identifier>/ratings — user
Submits the caller's **final** rating of one of their films. The rating, its three
scores and the assignment's move to `rated` are written in one transaction. A
rating cannot be changed afterwards.

Request:
```json
{ "scores": { "aesthetic": 10, "sound": 5, "appeal": 1 }, "comment": "Optional text" }
```
Every category must be present, each a whole number (JSON integer, not a string,
float or boolean) from 1 to 10; unknown category keys are rejected. `comment` is
optional plain text (trimmed, at most 1000 characters; never shown to other
reviewers or judges, only included in the admin export).

Response 200 — `total` is the sum of the three scores (3–30):
```json
{ "ok": true, "total": 16 }
```

Errors:
- 400 — `"scores object required"`, `"Unknown category: <key>"`,
  `"Missing score for: <key>"`, `"Score for <key> must be a whole number"`,
  `"Score for <key> must be 1-10"`, `"comment must be text"`,
  `"comment is too long (maximum 1000 characters)"`
- 404 — `"Film not found"` (no such film, not assigned to the caller, or no role)
- 409 — `"You have already submitted this film. Ratings can't be changed."`

---

## Admin

Film data only arrives through the admin's spreadsheet import (never at server
startup, never from archive.org's collection listing). The film database starts empty.

### GET /api/admin/jobs/status — admin
The single background job slot, used by the title lookup started by an import.
```json
{
  "state": "running",
  "kind": "titles",
  "phase": "titles",
  "done": 120,
  "total": 268,
  "processed": null,
  "error": null,
  "started_at": 1763401300.5,
  "finished_at": null,
  "film_count": 268
}
```
- `state`: `idle` (no job since the server started), `running`, `done`, or `error`.
- `kind`: `titles` (title lookup) or `null` when idle. `phase` (only while running): `titles`,
  with `done`/`total` titles looked up.
- `processed`: items processed by the last finished job (titles found); `error`: failure
  message. `started_at` / `finished_at` are Unix seconds.
- `film_count`: films currently in the database (live count).

The status is held in server memory, so it resets to `idle` on restart.

### POST /api/admin/import/preview — admin
Reads a spreadsheet exported as CSV and suggests which column is which. Saves nothing.
Request: `{ "csv_text": "<the CSV file's text>" }` (max 2 MB, 5000 data rows; first row = headers).
```json
{
  "headers": ["Timestamp", "…", "URL/Link to your film at archive.org", "…"],
  "row_count": 5,
  "sample_rows": [["11/11/2026 …", "…"]],
  "suggested_mapping": { "link": 3, "title": null, "description": 6 }
}
```
`suggested_mapping` indexes are 0-based positions in `headers`; `link` is the column whose cells
most often are archive.org item links. 400 `{ "error" }` for an empty/unreadable/oversized file.
(Creator, public-domain works, AI disclosure and eligibility columns are added to the
mapping in the import step.)

### POST /api/admin/import — admin
Imports films from a CSV using a column mapping.
```json
{
  "csv_text": "…",
  "mapping": { "link": 3, "title": null, "description": 6 },
  "dry_run": false,
  "on_existing": "skip",
  "lookup_titles": true
}
```
- `mapping.link` (required) — 0-based column of the archive.org link. `title` / `description`
  optional (`null` = none).
- **Only archive.org items are imported.** A link must be `archive.org/details/<id>` (also
  `/embed/<id>`, `/download/<id>`; host exactly `archive.org` or `www.archive.org`). Rows with no
  link, a non-archive.org link (e.g. YouTube) or free text are skipped; a repeated item in the file
  is skipped as a duplicate of its first row.
- `dry_run: true` — reports without writing: `{ "ok": true, "dry_run": true, "summary":
  { "rows", "new", "existing", "skipped" }, "skipped": [{ "row", "reason" }], "samples": [...] }`
  (`row` is the spreadsheet row number, header = 1; `skipped` lists at most 100).
- Real import requires `on_existing`: `"skip"` leaves films already in the database untouched,
  `"update"` overwrites the fields the sheet provides (blank cells never erase stored data).
  New films get the identifier as title when no title is given. A film is identified by its
  archive.org identifier alone (unique).
- `lookup_titles: true` — for rows without a title, starts a background job that fetches titles
  from archive.org (never overwriting a real title); follow it via `GET /api/admin/jobs/status`
  (`kind: "titles"`).

200: `{ "ok": true, "result": { "added", "updated", "skipped_existing", "skipped_invalid",
"title_lookup_started" }, "summary": {...}, "skipped": [...] }`

Errors: 400 (bad mapping/file, missing or invalid `on_existing`, or no importable rows);
409 while the background job is running.

### POST /api/admin/db/empty — admin
**Destructive.** Deletes every film and all assignments, ratings and scores (user accounts
and migrations are kept). The body must contain the confirmation word:
```json
{ "confirm": "EMPTY" }
```
200: `{ "ok": true, "deleted": { "rating_scores": 12, "ratings": 4, "assignments": 8, "films": 268 } }`

Errors: 400 if `confirm` is missing or not exactly `"EMPTY"`; 409 while the background
job is running. After this, `GET /api/films/next` returns `no_films` until the next import.
Download a backup first if the data may be needed.

### GET /api/admin/ratings.csv — admin
CSV download (`Content-Disposition: attachment; filename="ratings.csv"`), one row per
submitted rating, newest first. Text cells (`user_email`, `identifier`, `title`, `comment`)
that start with `=`, `+`, `-` or `@` are prefixed with `'` so spreadsheet apps don't
evaluate them. Columns:

`created_at, user_email, identifier, title, aesthetic, sound, appeal, total, comment`

(`total` is the sum of the three scores.)

### User management

#### GET /api/admin/users — admin
Every user, oldest first, with the state of their sign-in link:
```json
[{ "id": 2, "email": "rev@example.com", "created_at": "2026-11-25 23:30:52",
   "is_admin": false, "is_reviewer": true, "is_judge": false, "roles": ["reviewer"],
   "link": { "state": "active", "expires_at": "2026-12-25T23:59:59Z" } }]
```
`link` is `null` when the person has no link; `state` is `active` or `expired`. The link's
secret is never included.

#### POST /api/admin/users — admin
Invites a person: creates the account and its first link. The app sends no email.
```json
{ "email": "rev@example.com", "roles": ["reviewer"], "expires_at": "2026-12-25" }
```
`email` is required (stored lower-case). `roles` (default none) are from `admin`, `reviewer`,
`judge`. `expires_at` is optional: a date `YYYY-MM-DD` (end of that day, UTC) or an ISO-8601
date-time; it must be in the future; the default is 30 days from now.

201 — the secret appears **only here**:
```json
{ "ok": true, "user": { "id": 2, "email": "rev@example.com", "roles": ["reviewer"] },
  "link": { "token": "<secret>", "path": "/signin#<secret>", "expires_at": "2026-12-25T23:59:59Z" } }
```
The client builds the address as its own origin plus `path`.
Errors: 400 (invalid email, unknown role, bad `expires_at`), 409 (the email already has an account).

#### POST /api/admin/users/<id>/login-link — admin
Issues a new link (optional body `{ "expires_at": ... }`, same rules). The previous link stops
working and the person's current logins end (except the admin's own current one when they
issue a link for themselves). 201 `{ "ok": true, "user_id": 2, "link": { ...as above } }`.
Errors: 400 (bad `expires_at`), 404 (unknown user).

#### PUT /api/admin/users/<id>/login-link — admin
Changes the expiry of the user's active (not cancelled) link; this can revive an expired one.
Body `{ "expires_at": ... }` (required). 200 `{ "ok": true, "user_id": 2, "expires_at": "…Z" }`.
Errors: 400 (missing/bad `expires_at`), 404 (unknown user, or no active link).

#### DELETE /api/admin/users/<id>/login-link — admin
Cancels the user's link and ends their current logins (the admin's own, if it is their own link).
200 `{ "ok": true, "user_id": 2 }`, also when there was no link. Errors: 404 (unknown user).

#### PUT /api/admin/users/<id>/roles — admin
Sets the user's roles to **exactly** the list given (a role not listed is removed).
Known roles: `admin`, `reviewer`, `judge`.
```json
{ "roles": ["reviewer", "judge"] }
```
Response 200 `{ "ok": true, "user_id": 7, "roles": ["reviewer", "judge"] }`.
Errors: 400 (`roles` not a list of strings, unknown role, or an admin removing
their *own* admin role), 404 (unknown user).

#### POST /api/admin/users/<id>/make-admin — admin
#### POST /api/admin/users/<id>/revoke-admin — admin
```json
{ "ok": true, "user_id": 7, "is_admin": true }
```
The other roles are left alone. Errors: 404 (unknown user).

### Database inspection

`user_sessions` and `login_links` are internal and never listed, dumped or backed up.

#### GET /api/admin/db/tables — admin
Row counts per table:
```json
{ "assignments": 0, "films": 140, "rating_scores": 0, "ratings": 0,
  "schema_migrations": 1, "users": 3 }
```

#### GET /api/admin/db/schema — admin
`CREATE TABLE` SQL per table: `{ "users": "CREATE TABLE users (...)", ... }`

#### GET /api/admin/db/<table> — admin
Rows of one table as a JSON array.

Query parameters:
- `order_by` — a column name with optional `ASC`/`DESC` (e.g. `id DESC`); anything else is rejected with 400
- `limit`, `offset` — integers

Special cases: `films` rows include a computed `rating_count`; `users` rows
omit `password_hash` (columns: `id, email, is_admin, is_reviewer, is_judge, created_at`).

Errors: 400 (bad `order_by`), 404 `{ "error": "Unknown table: <name>" }`.

### Backup and restore

#### GET /api/admin/db/backup — admin
Downloads the whole database as JSON
(`ia_ratings_backup_<YYYY-MM-DDTHH-MM-SSZ>.json`):
```json
{
  "app": "ia_ratings",
  "format_version": 2,
  "schema_version": 1,
  "exported_at": "2026-11-03T19:00:00Z",
  "tables": { "users": [ { "id": 1, "...": "..." } ], "films": [] }
}
```
Backups of the old app (`format_version` 1) cannot be restored. Login sessions and
magic links are never included.

#### POST /api/admin/db/restore — admin, destructive
The request body is a backup file as produced above. In a single transaction,
for each of `schema_migrations, users, films, assignments, ratings, rating_scores`
that is present in the backup, all existing rows are deleted and replaced with the
backup's rows. Tables missing from the backup are left alone, **except** that if the
backup replaces `users` or `films`, any of `assignments, ratings, rating_scores`
that it lacks is emptied (those rows would point at the wrong people or films).
All login sessions and magic links are deleted.

Response 200:
```json
{ "ok": true, "exported_at": "...", "schema_version": 1,
  "restored": { "users": 3, "films": 140 } }
```
Errors: 400 (not JSON, wrong `app`, unsupported `format_version` or `schema_version`,
`tables` not an object, or a column that doesn't exist in the current schema). On
error nothing is changed.

---

## Client usage (informative)

The client (`client/src/App.jsx`) calls:
- `/api/me`, `/api/auth/signin`, `/api/auth/logout`
- `/api/categories`, `/api/films/next`, `/api/films/<identifier>/ratings`
- Admin panel: `/api/admin/jobs/status`, `/api/admin/import/preview`, `/api/admin/import`,
  `/api/admin/db/empty`, `/api/admin/ratings.csv`, `/api/admin/users`, `/api/admin/users/<id>/roles`,
  `/api/admin/users/<id>/login-link` (POST, PUT, DELETE),
  `/api/admin/db/tables`, `/api/admin/db/<table>` (the Users tab
  uses `/api/admin/users`), `/api/admin/db/backup`, `/api/admin/db/restore`

The client does not call `/api/films/<identifier>`, `/api/admin/db/schema`,
`make-admin`/`revoke-admin` or `/api/health`.
