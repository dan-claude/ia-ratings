# Client–Server API Contract (Binding)

This document defines the **binding API contract** between the client (React/Vite)
and the server (Flask). A change is invalid if the implementation diverges from
this contract without updating this file.

Last verified against the code: 2026-11-19.

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
{ "auth_scheme": "ia", "oauth_providers": ["github"] }
```
`auth_scheme` is `"ia"` (archive.org login) or `"local"` (email/password).
`oauth_providers` lists the extra sign-in buttons to show; it is `[]` unless
GitHub login is configured (`GITHUB_CLIENT_ID` + `GITHUB_CLIENT_SECRET`), in
which case it is `["github"]`. Clients must tolerate unknown provider names.

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

### GET /api/auth/github/login — public, GitHub login only
Browser navigation, not an XHR call. Stores a random single-use `state` in the
session and responds `302` to `https://github.com/login/oauth/authorize`.
Rate-limited like `login`. Returns 404 `{"error": "GitHub login is not
configured"}` when GitHub login is off.

### GET /api/auth/github/callback — public, GitHub login only
The URL registered as the OAuth app's *Authorization callback URL*; GitHub sends
the browser here with `?code=…&state=…`. The state must match the session's
(and is consumed either way). On success the server finds or creates the user
for that GitHub account id, starts a new session, and responds `302 /`.
On failure it responds `302 /?auth_error=<code>` with a code of:
- `github_state` — missing/mismatched state (expired session, replay)
- `github_denied` — the user declined on GitHub
- `github_failed` — code exchange or profile lookup failed

New users get email `<github-id>+<login>@users.noreply.github.com`. Same 404
and rate limit as `/api/auth/github/login`.

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
  "is_admin": false,
  "is_judge": false,
  "roles": []
}
```
`roles` lists the roles the user holds, in the order `admin`, `judge`; `is_admin`
and `is_judge` are the same information as booleans. Roles are independent: an
admin is not automatically a judge.
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

Errors (both 404, with a machine-readable `code`):
- `{ "error": "The film database hasn't been set up yet. An admin needs to sync it from the Internet Archive.", "code": "no_films" }`
  — there are no films at all (never synced, or the database was emptied)
- `{ "error": "You've rated every film — there's nothing left to rate.", "code": "all_rated" }`
  — films exist but this user has rated them all

### GET /api/films/<identifier> — user
Returns one film by its Internet Archive identifier, **in the active collection** (the same item can
exist in several collections, each as its own film).

Errors:
- 404 `{ "error": "Film not found" }`

---

### GET /api/films/<identifier>/notes — judge
Judges' notes on a film, oldest first. Requires the `judge` role: 401 if not logged
in, 403 `{ "error": "Forbidden" }` for any user who is not a judge (admins
included).
```json
[
  { "id": 12, "author": "judge1@example.com",
    "createdAt": "2026-11-19T16:02:11Z", "text": "Lovely colour work." }
]
```
`author` is the writer's archive.org username, else GitHub username, else email.
`createdAt` is UTC ISO-8601. `text` is plain text (render it as text, not HTML).

Errors: 404 `{ "error": "Film not found" }`.

### POST /api/films/<identifier>/notes — judge
Adds a note (a film can have any number). Every judge can see every note.
```json
{ "text": "Lovely colour work." }
```
Response 201: the created note (same shape as above). The text is trimmed.

Errors: 400 — `"Note text is required"` (missing, not a string, or blank),
`"Note is too long (max 5000 characters)"`; 404 `"Film not found"`.

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

Nothing syncs automatically (not at server startup either): film data only
appears when an admin starts a sync. The film database starts empty.

### POST /api/admin/sync — admin
Starts a sync **in the background** and returns immediately. The sync fetches
every `mediatype:movies` item in the collection from archive.org and upserts it
into `films`, then fetches full HTML descriptions (converted to plain text) for
films that don't have one yet. It can take minutes; poll
`GET /api/admin/sync/status` for progress.

202 — started:
```json
{ "ok": true, "status": { "state": "running", "...": "see status below" } }
```
409 — a sync is already running: `{ "error": "A sync is already running", "status": { ... } }`

### GET /api/admin/sync/status — admin
This reports the single background job slot, which is used by the sync and by the
CSV import's title lookup (`kind` says which).
```json
{
  "state": "running",
  "kind": "sync",
  "phase": "descriptions",
  "done": 120,
  "total": 268,
  "synced": null,
  "error": null,
  "started_at": 1763401300.5,
  "finished_at": null,
  "film_count": 268
}
```
- `state`: `idle` (no job since the server started), `running`, `done`, or `error`.
- `kind`: `sync` (archive.org sync) or `titles` (title lookup started by an import); `null` when idle.
- `phase` (only while running): `listing` (reading the film list; `total` is
  `null`, `done` counts films found so far), `descriptions` (`done`/`total`
  films whose description has been fetched) or `titles` (`done`/`total` titles looked up).
- `synced`: items processed by the last finished job — films fetched (sync) or
  titles found (titles); `error`: failure message. `started_at` / `finished_at` are Unix seconds.
- `film_count`: films currently in the database (live count).

The status is held in server memory, so it resets to `idle` on restart.

### GET /api/admin/settings — admin
```json
{
  "collection": "2026-public-domain-day-film-contest",
  "default_collection": "2026-public-domain-day-film-contest",
  "collections": [{ "name": "2026-public-domain-day-film-contest", "films": 268 }]
}
```
`collection` is the **active** archive.org collection: raters only see films whose collection matches it,
and sync / import add films to it. `default_collection` is the built-in value used until an admin sets one.
`collections` lists every collection that currently has films in the database, with counts.

### PUT /api/admin/settings/collection — admin
Request: `{ "collection": "2027-public-domain-day-film-contest" }` (whitespace trimmed).
The value must be an archive.org identifier: letters, digits, `.`, `_`, `-`; starts with a letter or digit; at
most 100 characters. Takes effect immediately for all users. Films stored under other collections are kept but
hidden from raters until that collection is selected again.

200: `{ "ok": true, "collection", "default_collection", "collections", "film_count": <films in the new collection> }`
Errors: 400 invalid value; 409 while a sync or title lookup is running.

### POST /api/admin/import/preview — admin
Reads a spreadsheet exported as CSV and suggests which column is which. Saves nothing.
Request: `{ "csv_text": "<the CSV file's text>" }` (max 2 MB, 5000 data rows; first row = headers).
```json
{
  "headers": ["Timestamp", "…", "URL/Link to your film at archive.org", "…"],
  "row_count": 5,
  "sample_rows": [["11/11/2026 …", "…"]],
  "suggested_mapping": { "link": 3, "title": null, "description": 6, "extra": [] },
  "collection": "2026-public-domain-day-film-contest"
}
```
(`collection` is the active collection the films will be added to.)
`suggested_mapping` indexes are 0-based positions in `headers`; `link` is the column whose cells
most often are archive.org item links. 400 `{ "error" }` for an empty/unreadable/oversized file.

### POST /api/admin/import — admin
Imports films from a CSV using a column mapping.
```json
{
  "csv_text": "…",
  "mapping": { "link": 3, "title": null, "description": 6, "extra": [7] },
  "collection": "2026-public-domain-day-film-contest",
  "activate_collection": false,
  "dry_run": false,
  "on_existing": "skip",
  "lookup_titles": true
}
```
- `collection` — optional; the archive.org collection the films are filed under (defaults to the active
  collection). It should match the name of an Internet Archive collection exactly (the last part of its
  web address). Validated like `PUT /api/admin/settings/collection`; 400 if invalid.
- `activate_collection` — optional; when `true` and `collection` differs from the active one, the
  collection also becomes the active one after a successful import (so raters see the films).
- `mapping.link` (required) — 0-based column of the archive.org link. `title` / `description`
  optional (`null` = none); `extra` — columns kept in `films.metadata_json` (admin-only; never
  returned by `/api/films/*`).
- **Only archive.org items are imported.** A link must be `archive.org/details/<id>` (also
  `/embed/<id>`, `/download/<id>`; host exactly `archive.org` or `www.archive.org`). Rows with no
  link, a non-archive.org link (e.g. YouTube) or free text are skipped; a repeated item in the file
  is skipped as a duplicate of its first row.
- `dry_run: true` — reports without writing: `{ "ok": true, "dry_run": true, "summary":
  { "rows", "new", "existing", "skipped" }, "skipped": [{ "row", "reason" }], "samples": [...],
  "collection", "active_collection" }` (`row` is the spreadsheet row number, header = 1; `skipped` lists
  at most 100; `collection` is the collection the films would be filed under).
- Real import requires `on_existing`: `"skip"` leaves films already in the database untouched,
  `"update"` overwrites the fields the sheet provides (blank cells never erase stored data).
  New films get the identifier as title when no title is given.
- "Existing" means already in the target `collection`. The same archive.org item in a *different*
  collection is a separate film (its own row and its own ratings), so it counts as new. `"skip"` leaves
  existing films untouched; `"update"` updates only the rows in the target collection.
- `lookup_titles: true` — for rows without a title, starts a background job that fetches titles
  from archive.org (never overwriting a real title); follow it via `GET /api/admin/sync/status`
  (`kind: "titles"`).

200: `{ "ok": true, "result": { "added", "updated", "skipped_existing", "skipped_invalid",
"title_lookup_started", "collection", "activated" }, "summary": {...}, "skipped": [...] }`

Errors: 400 (bad mapping/file, missing or invalid `on_existing`, or no importable rows);
409 while a sync or title lookup is running.

### POST /api/admin/db/empty — admin
**Destructive.** Deletes every film and all ratings and scores (user accounts,
criteria and migrations are kept). The body must contain the confirmation word:
```json
{ "confirm": "EMPTY" }
```
200: `{ "ok": true, "deleted": { "rating_scores": 12, "ratings": 6, "films": 268 } }`

Errors: 400 if `confirm` is missing or not exactly `"EMPTY"`; 409 while a sync is
running. After this, `GET /api/films/next` returns the `no_films` error until
the next sync. Download a backup first if the data may be needed.

### GET /api/admin/ratings.csv — admin
CSV download (`Content-Disposition: attachment; filename="ratings.csv"`), newest
first. Columns:

`created_at, user_email, identifier, title, <one column per active criterion key>`

### GET /api/admin/notes.csv — admin
CSV download (`Content-Disposition: attachment; filename="notes.csv"`) of judges'
notes on films in the **active collection**, grouped by film (by identifier) and
oldest first within a film. Columns: `created_at, author, identifier, title, text`
(`author` as in the notes API). Text cells that start with `=`, `+`, `-` or `@`
are prefixed with `'` to stop spreadsheet apps evaluating them as formulas.
Admins can download this even without the judge role.

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

#### PUT /api/admin/users/<id>/roles — admin
Sets the user's roles to **exactly** the list given (a role not listed is removed).
Known roles: `admin`, `judge`.
```json
{ "roles": ["admin", "judge"] }
```
Response 200 `{ "ok": true, "user_id": 7, "roles": ["admin", "judge"] }`.
Errors: 400 (`roles` not a list of strings, unknown role, or an admin removing
their *own* admin role), 404 (unknown user).

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
omit `password_hash` (columns: `id, email, ia_username, github_username, is_admin, is_judge, created_at`).

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
for each of `schema_migrations, app_settings, users, criteria, films, ratings,
rating_scores, film_notes` that is present in the backup, all existing rows are deleted and replaced with
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
- `/api/config`, `/api/me`, `/api/auth/login`, `/api/auth/register` (local mode only), `/api/auth/github/login` and `/api/auth/github/callback` (when configured), `/api/auth/logout`
- `/api/criteria`, `/api/films/next`, `/api/films/<identifier>/ratings`
- Admin panel: `/api/admin/settings`, `/api/admin/settings/collection`, `/api/admin/sync`, `/api/admin/sync/status`, `/api/admin/import/preview`, `/api/admin/import`, `/api/admin/db/empty`, `/api/admin/ratings.csv`, `/api/admin/notes.csv`, `/api/admin/criteria`,
  `/api/admin/criteria/<id>`, `/api/admin/users/<id>/make-admin|revoke-admin`,
  `/api/admin/db/tables`, `/api/admin/db/<table>` (including `users?order_by=id`
  for the Users tab), `/api/admin/db/backup`, `/api/admin/db/restore`

Judges' notes: `/api/films/<identifier>/notes` (GET and POST, only for users with the
judge role). Admin Users tab: `/api/admin/users/<id>/roles`.

The client does not call `/api/films/<identifier>`, `/api/admin/db/schema` or
`/api/health`.
