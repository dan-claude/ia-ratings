## Unreleased (branch `major-changes`, My films list)
- New `GET /api/me/films` (reviewers and judges; 403 otherwise): the caller's assigned films with `status` (`assigned` / `seen` / `rated`), alphabetical by title. Listing doesn't mark films seen.
- Client: **My films** page listing every assigned film as a link to that film's rating page, with a status column (unseen / seen / rated) and an "only films I haven't rated" filter. Any film can be opened and rated in any order; opening one marks it seen; a rated film opens read-only with the person's own scores and comment. Submitting from a listed film carries on with the next film. Pages are now URL-fragment routes (`#/`, `#/films`, `#/film/<id>`, `#/results`), so every film has a real link and the browser's Back button works; the top bar gains Rate / My films / My ranked films.

## Unreleased (branch `major-changes`, dev proxy target)
- The Vite dev server's `/api` proxy target is now configurable with `API_URL` (base URL: protocol, host, port; default `http://127.0.0.1:5001`), from the environment or `client/.env.local`, instead of being hard-coded in `client/vite.config.js`.

## Unreleased (branch `major-changes`, legacy database switch)
- New one-time setting `LEGACY_DB=move-aside`: when the app finds an old-style database at `DB_PATH` it renames it (and its `-wal` / `-shm`) to `<DB_PATH>.legacy-<UTC time>` instead of refusing to start, and creates a fresh database. **Nothing is deleted.** It only acts on an old-style file, so a forgotten setting does nothing on later deploys; any other value leaves the old behaviour (refuse to boot). The production reset steps are in `CLAUDE.md`.

## Unreleased (branch `major-changes`, step 8: dark mode)
Not deployed. Client only (no API change).
- Dark mode with a Moon / Sun toggle (top bar and the sign-in pages). The choice is remembered in the browser (`localStorage`); the first visit follows the device's light/dark setting; the theme is set before the first paint so there is no flash. All colours moved from inline literals to CSS variables in the new `client/src/theme.css`, and native controls follow the theme (`color-scheme`).
- Fix: opening another person's sign-in link in a browser that was already signed in left the previous person's ranked list / film on screen. The client now resets all per-person state when the signed-in person changes.

## Unreleased (branch `major-changes`, step 7: judge export and final screen)
Not deployed.
- New judge-only routes `GET /api/me/results` and `GET /api/me/results.csv` (403 for anyone without the judge role, admin alone and reviewers included): the judge's own ranked list of the judges' pool films they have rated: rank, title, creator, the three scores, total, comment. Highest total first; equal totals share a rank and are listed alphabetically by title. A film a judge rated earlier as a reviewer is included (they don't rate it twice). Only the caller's own data: no averages or other people's scores. The CSV is `my_ratings.csv`, with formula-like cells prefixed with `'`.
- Client: after a judge's last film they are taken to their ranked list (when a pool exists); judges also get a "My ranked films" button in the top bar and a CSV download. Reviewers get neither.

## Unreleased (branch `major-changes`, step 6: rankings and the judges' pool)
Not deployed.
- **Rankings.** `GET /api/admin/rankings` (and `rankings.csv`): every film with its reviewers' average (highest first), rank (ties share a rank) and all its details (title, creator, description, public-domain works, AI disclosure). Averages are exact (`total` and `reviews` integers); the `average` field is a rounded display value. Only reviewers'-round ratings count, so judges can't change the ranking.
- **Judges' pool.** `GET /api/admin/judges-pool/preview?count=N` shows the top N with a tie check (the film at rank N must score strictly higher than the next; otherwise `valid: false` with the nearest valid counts) and is blocked (409 `reviews_missing`, listing the films and counts missing) until every film has both reviews. `POST /api/admin/judges-pool` confirms: sets `films.in_judges_pool` and gives every judge every pool film. Also `GET` (pool and judges' progress), `POST .../assign` (give the pool to judges added later; idempotent) and `DELETE` (clear it; 409 once a judge has rated). Admins can't remove or swap single films. Judges never see scores.
- **A judge who already reviewed a pool film keeps that rating and does not rate it again** (owner's decision). New column `assignments.round` (`reviewers` / `judges`; baseline schema edited, still version 1) keeps the two rounds apart: the reviewers' average and the "fully reviewed" count use the reviewers' round only; progress assignees now include `round`; a pool film hand-assigned to a judge is a `judges` assignment.
- Admin panel: new **Rankings** tab (pool chooser with preview, tie warning with one-click valid numbers, confirm; pool status per judge; the full ranking with expandable details and the CSV link).
- Client: pasting a sign-in link into a tab already showing `/signin` now picks it up (hashchange).

## Unreleased (branch `major-changes`, step 5: rating screen)
Not deployed. Client only (no API change).
- New rating screen layout: film title as a link to the archive.org item with "by <creator>" (the identifier is gone), then description, list of public domain works used, AI disclosure, the film player, and the three categories underneath, each with its name, a bold description and a **1–10 list of buttons only** (no number box, no separate range) with the 1 / 5 / 10 labels. Once all three are chosen the person's total is shown ("10 + 5 + 10 = 25").
- Comments: one box below the scores headed "Comments on Film" with a smaller "(May be used in presentation)", 1000 characters, optional; no username or timestamp. Submit & Next sits below it and asks "Are you sure? Scores cannot be changed" before sending.
- The next film no longer flashes empty scores: the old film and scores stay (controls disabled, "Loading next film…") until the next film has loaded; then everything changes together and the page scrolls to the top. If the server says the film was already submitted (409, e.g. from a second tab) the person is moved on with a notice.
- Opening a sign-in link while already signed in now shows the Sign in button (to switch accounts) instead of the app.

## Unreleased (branch `major-changes`, step 4: distribution and progress)
Not deployed.
- **Distribute films.** `POST /api/admin/distribute` gives every film to 2 different reviewers at random, spread evenly (each reviewer's count within one film of the others). Runs once: 409 `already_distributed` if any assignment exists, plus `no_films` and `too_few_reviewers`. `POST /api/admin/distribute/reset` (body `{"confirm": "RESET"}`) deletes all assignments **and ratings** and empties the judges' pool so it can be run again (deleting ratings too is a decision of mine: a rating without its assignment would block re-distribution).
- **Progress views.** `GET /api/admin/progress`: overall counter (films fully reviewed = at least 2 submitted reviews; still needing reviews), per-person counts of `assigned` / `seen` / `rated`, per-film assignees with their status. Admin panel → new **Reviews** tab: the counter, distribute and reset buttons, a People table (Show films lists a person's films with status) and a Films table with an "only films that still need reviews" filter.
- **Hand assignment** (admin duty from the plan): `POST /api/admin/assignments {user_id, identifier}` and `DELETE /api/admin/assignments/<user_id>/<identifier>` (not once rated). Only reviewers and judges can be given films. Available per film in the Films table.

## Unreleased (branch `major-changes`, step 3: import)
Not deployed.
- The CSV import now maps the form's other columns: `creator` (the "by" credit), `public_domain_works`, `ai_disclosure`, plus the existing `link`, `title`, `description`, and a new optional `eligible` (yes/no). They are stored on the film (the columns already existed) and reach reviewers through the film object. `suggested_mapping` guesses all of them from header names (each column used once). **API:** the `mapping` of `POST /api/admin/import` and `suggested_mapping` of the preview gain these keys; dry-run samples gain `creator`; the summary gains `ineligible` and `ineligible_in_database`.
- Eligibility: with `eligible` mapped only rows saying yes are imported; `no`, blank and unclear cells are skipped and listed with the reason (decided with the owner: nothing ambiguous is guessed). Ineligible films are never loaded. An import never deletes a film: one already loaded whose row now says no stays, and the dry run counts it as `ineligible_in_database` (the Import tab warns). Re-importing works as before (skip, or update with blank cells never erasing stored text).
- Cell text is normalised (CRLF to LF, non-breaking spaces, trimmed); empty cells store nothing.
- Import tab: a dropdown per field, "not eligible" count and the new warning, creator shown in the samples.

## Unreleased (branch `major-changes`, step 2: login by invite)
Not deployed. **Magic-link login is now the only way in.**
- New `POST /api/auth/signin` `{"token"}` (rate-limited 10/min, 50/hour per client address; the rate-limit and body-size tests moved here). 401 with one message for unknown, cancelled and expired links. The client route `/signin` shows a **Sign in** button and nothing happens until it is pressed; the secret lives in the URL fragment (`/signin#<secret>`), so it isn't sent to the server on page load, and is removed from the address bar once read. `/signin` is served by an explicit route (the static route at `/` would otherwise 404 it).
- Links are reusable until their expiry (admin-chosen; default 30 days; checked on every use) or until cancelled. Only the SHA-256 is stored, so a link is shown once, when created. One active link per user; a new link cancels the old one, and issuing or cancelling a link ends that person's sessions (not the admin's own when acting on themselves).
- New admin routes: `GET /api/admin/users` (users with roles and link state), `POST /api/admin/users` (invite: email + roles + optional expiry → 201 with the link), `POST` / `PUT` / `DELETE /api/admin/users/<id>/login-link` (new link / change expiry / cancel). Admin panel → Users has an invite form, a copy-once link box, and per-user New link / Set expiry / Cancel link.
- First admin: `python tools/print_db.py --invite EMAIL --admin [--roles ...] [--days N]` creates the user (or adds roles and re-issues the link for an existing one) and prints the link; new setting `PUBLIC_URL` (CLI only) prints the full address. It creates the database if missing.

## Unreleased (branch `major-changes`, step 1: clean baseline)
Work in progress toward the rebuild described in `CHANGES_DRAFT.md` (kept out of git). **Not deployed.** Breaking by design: no data is carried over.
- **New baseline schema.** `server/db.py` is rewritten as one clean schema (`SCHEMA_VERSION = 1`); the old migrations v1–v9 (including the `films` table rebuild) are gone. An old-style database (old tables, an old `users` layout, or another schema version) is **refused at startup** with a message to delete the file, locally and on Railway; the dev entrypoint prints it, gunicorn fails to boot. Tables: `users` (email, nullable `password_hash`, `is_admin`/`is_reviewer`/`is_judge`), `login_links` (hashed magic links; routes come in step 2), `user_sessions`, `films` (`creator`, `description`, `public_domain_works`, `ai_disclosure`, `in_judges_pool`; `ia_identifier` unique on its own), `assignments` (user, film, status `assigned`/`seen`/`rated`), `ratings` (one per person per film, with the comment), `rating_scores` (by category key, 1–10). Dropped: `criteria`, `film_notes`, `app_settings`, and `films.collection`/`mediatype`/`metadata_json`.
- **Three roles.** `reviewer` joins `admin` and `judge` (independent). `GET /api/me` gains `is_reviewer`; `PUT /api/admin/users/<id>/roles` accepts `reviewer`; the users dump has `is_reviewer`. Only reviewers and judges rate (admin alone does not); a user with no role sees no films.
- **Hard-coded categories.** Aesthetic, Sound(track) and Appeal (1–10, with descriptions and 1/5/10 labels) live in `server/categories.py`. **Breaking:** `GET /api/criteria` is replaced by `GET /api/categories`; the `/api/admin/criteria` routes and the Criteria tab are removed.
- **Assigned films, final ratings.** `GET /api/films/next` and `GET /api/films/<id>` only serve films assigned to the caller; opening a film marks it `seen`; an opened-but-unfinished film comes back first, else a random unopened one. New 404 codes `no_role` and `no_assignments` (plus `no_films`, `all_rated`). Film objects gain `creator`, `publicDomainWorks`, `aiDisclosure`, `archiveUrl`, `status`. `POST /api/films/<id>/ratings` takes `{"scores": {aesthetic, sound, appeal}, "comment"}` (whole numbers 1–10; optional comment ≤ 1000 chars), is **final** (409 if repeated) and answers `{"ok": true, "total": n}`.
- **Removed:** the archive.org collection sync (`POST /api/admin/sync`, `GET /api/admin/sync/status`, `tools/sync.py`, the `aiohttp` dependency) and the collection setting (`/api/admin/settings*`, and the `collection`/`activate_collection` fields of the import); judges' notes (`/api/films/<id>/notes`, `notes.csv`; replaced by the comment on each rating); archive.org, local email/password and GitHub login (`/api/auth/login`, `/api/auth/register`, `/api/auth/github/*`, `/api/config`, `AUTH_SCHEME`, `GITHUB_*`, `docs/GITHUB_LOGIN.md`, `--auth-scheme`). **Until step 2 (magic-link login) lands nobody can sign in.**
- Title lookup after an import is unchanged, but its status moved: `GET /api/admin/jobs/status` (was `/api/admin/sync/status`; `kind` is always `titles`, the count field is `processed`). The import mapping no longer has `extra` columns.
- Backup/restore: `format_version` is now 2 and `schema_version` must match (old backups are refused); restoring also deletes magic links; if the backup replaces `users` or `films` but lacks `assignments`/`ratings`/`rating_scores`, those are emptied. `login_links` and `user_sessions` are hidden from the DB browser and backups.
- `POST /api/admin/db/empty` now also deletes assignments. `ratings.csv` columns: `created_at, user_email, identifier, title, aesthetic, sound, appeal, total, comment`.
- Client: the login form is replaced by a "sign-in is by invitation" message; the admin panel loses the collection, sync and Criteria screens and gains a Reviewer checkbox; the rating screen uses the new API (title links to archive.org with "by creator", description / public-domain works / AI disclosure, 1–10 buttons, comment box). The full new rating screen is step 5.

## Unreleased
- Security hardening from an audit (details below). **Deploy notes:** `SESSION_SECRET` must be set in Railway or the app now refuses to boot (the deploy fails its health check and the previous deployment keeps running); everyone is logged out once (sessions are now server-side, migration v9); run `pip install -r server/requirements.txt` locally for the new pinned versions.
- Fix: the server no longer starts with the public default `SESSION_SECRET` (anyone could have forged an admin session). `create_app()` raises unless a real secret is set; the local dev entrypoint (`python -m server.app`) uses a random per-run secret instead. Session cookies are `Secure` everywhere except that dev entrypoint.
- Fix: the local dev server now binds `127.0.0.1` by default (was `0.0.0.0`), and refuses `--debug` on a non-local host.
- Fix: the login rate limit was keyed on the proxy's address behind Railway, so every user shared one bucket (10 logins/min site-wide, easy to lock everyone out). New `TRUSTED_PROXY_HOPS` setting (Dockerfile sets 1) makes it per client address.
- Fix: no limit on request body size (an unauthenticated 30 MB login body was accepted). Bodies are capped at 1 MB (admin import 16 MB, restore 64 MB); larger get 413 JSON.
- Fix: one archive.org person could get several accounts (and several ratings per film) by typing their username in a different case or their email. Accounts are now keyed on the canonical name archive.org reports, case-insensitively; older email-keyed accounts are adopted on next login. The login logs the key names of archive.org's response so the field names can be confirmed in production.
- Fix: logout didn't invalidate a copied cookie and a backup restore could hand old sessions to different people. Sessions now have a server-side record (`user_sessions`, DB migration v9, SHA-256 of the id only): logout revokes, restore ends all sessions except the restoring admin's, and cookies from before the upgrade stop working. The table is hidden from the DB browser and backups.
- Fix: note authors could expose an email address (an archive.org account keyed on a typed email) to every judge; authors are now shown without the `@domain`.
- Fix: `ratings.csv` wrote film titles (uploader-controlled) and emails unescaped, so `=HYPERLINK(...)` in a title would run in Excel. It now uses the same `csv_safe` helper as `notes.csv` (moved to `server/services/csv_utils.py`).
- Dependencies: Flask 3.1.3 (CVE-2026-27205), requests 2.33.0 (CVE-2024-47081, CVE-2026-25645), aiohttp pinned to 3.14.5. Docker builds use `npm ci` with the committed lockfile.
- Docker: the server now runs as an unprivileged user (`docker-entrypoint.sh` chowns the volume, then drops privileges; falls back to root with a warning if it can't). Via `railway ssh`, write to the DB as `app` (see CLAUDE.md).
- CI: `permissions: contents: read`, actions pinned to commit SHAs, `npm ci`.
- Removed `RECREATE_WITH_CLAUDE.txt`, the from-scratch rebuild spec that embedded a copy of the server source. It duplicated the code and the other docs, had to be regenerated by hand on every change and drifted out of date. Git history holds every version of the code; `README.md`, `CLAUDE.md` and `API_CLIENT_SERVER.md` document the app.

## 1.3.0 (2026-11-19)
- User roles and judges' notes. A user can now hold any of the roles `admin` and `judge` (independent of each other). Admin panel → Users shows Admin / Judge checkboxes per user (replacing the Make/Revoke admin buttons; an admin can't untick their own Admin box). New route `PUT /api/admin/users/<id>/roles` sets the list exactly; `make-admin` / `revoke-admin` still work and leave the judge role alone. `GET /api/me` gains `is_judge` and `roles`; the admin users dump gains `is_judge`.
- Judges can write notes about a film: **Add note** opens a popup; every note on the film is listed at the bottom of the film page in a table (who wrote it, when, the text). New judge-only routes `GET` and `POST /api/films/<id>/notes` (403 for everyone else, admins included; max 5000 characters; plain text). Notes are kept when a film is re-synced, deleted by "empty database", and included in backup/restore (restoring a backup that has films but no notes clears notes, since they would point at the wrong films).
- New admin download `GET /api/admin/notes.csv` (Actions → Download notes.csv): one row per judge's note on the active collection — `created_at, author, identifier, title, text` — grouped by film. Cells starting with `=`, `+`, `-` or `@` are prefixed with `'` so spreadsheet apps don't run judges' text as formulas. `ratings.csv` is unchanged.
- DB migration v8: `users.is_judge` and the new `film_notes` table. Existing admins stay admins.
- Fix: importing into a different collection still counted films from other collections as "already there". A film is now unique per (archive.org identifier, collection) (DB migration v7, which rebuilds the `films` table in place keeping every id and rating; all-or-nothing). "Already there" in an import means already in the target collection; the same item in another collection is new and gets its own row and ratings. `update` no longer moves films between collections. Lookups by identifier, sync upserts and title lookups are scoped to a collection.
- CSV import: the admin now sets the **collection name** the films are filed under (the Import tab field starts as the active collection and explains it must match the name of an archive.org collection). If it differs from the active collection the page warns that raters won't see the films, and offers "also make it the active collection". API: `POST /api/admin/import` accepts `collection` and `activate_collection`; the dry run reports `collection` and `active_collection`; the result reports `collection` and `activated`.
- Populate films from a spreadsheet: admin panel → **Import** takes a CSV export, lets the admin map columns (link / title / description / optional admin-only extras), shows a dry-run summary, and imports. New routes `POST /api/admin/import/preview` and `POST /api/admin/import`. Only `archive.org` item links are imported (YouTube links, free text and blanks are skipped and listed); the admin chooses skip vs update for films that already exist; missing titles can be looked up from archive.org in the background.
- The active film collection is now an admin setting (admin panel → Actions → Film collection) instead of being hard-coded: raters only see films in it, and sync/import tag films with it. Stored in a new `app_settings` table (DB migration v6, included in backup/restore); changes apply immediately without a restart. New routes `GET /api/admin/settings` and `PUT /api/admin/settings/collection` (409 while a sync/title lookup runs). The built-in default stays `2026-public-domain-day-film-contest`; `tools/sync.py` now defaults to the collection stored in the target DB.
- `GET /api/admin/sync/status` now also reports `kind` (`sync` / `titles`) and a `titles` phase; the background job slot is shared, so import/sync/empty return 409 while one is running.
- Admin sync now runs in the background: `POST /api/admin/sync` returns 202 immediately (409 if already running) and the new `GET /api/admin/sync/status` reports `state`, `phase`, `done`/`total` and the live `film_count`. The admin panel shows a progress bar and survives page reloads. Nothing syncs at server startup (the film DB starts empty). **Breaking:** the old blocking response `{ok, added, synced}` is gone.
- New admin command `POST /api/admin/db/empty` (body `{"confirm": "EMPTY"}`) deletes all films and ratings, keeping users and criteria; refused with 409 during a sync. Admin panel: Actions → Danger zone.
- `GET /api/films/next` 404s now carry `code`: `no_films` ("film database hasn't been set up yet") vs `all_rated`; the client shows these as notices instead of errors.
- Fix: sync silently dropped films (a 268-film collection often yielded ~214–232) because archive.org's unsorted paging returns overlapping pages; the search is now sorted by identifier and results are de-duplicated.
- Fix: a first sync on an empty database never fetched full descriptions (films not yet in the DB were skipped), so the "descriptions" step only ran on re-syncs.
- GitHub OAuth login, offered alongside the existing archive.org / local login when `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` are set. New routes `GET /api/auth/github/login` and `/api/auth/github/callback`; `GET /api/config` gains `oauth_providers`; the login screen shows "Continue with GitHub".
- DB migration v5: `users.github_id`, `users.github_username` (+ unique index on `github_id`). The admin Users tab shows `github_username`.
- New setup guide: `docs/GITHUB_LOGIN.md`.

## 1.2.0
- Documentation refresh to match the code as of 2026-11-03 (no code changes):
  - README.md rewritten: IA vs local auth, admin panel, config table, first-time admin setup, CLI tools, deployment, doc map; fixed the requirements path and the dev proxy port (5001).
  - API_CLIENT_SERVER.md now covers every route: `/api/config`, IA login body, rate limits, `/api/films/<identifier>`, admin criteria, user admin, DB browser, backup/restore, error/500 shapes. `description` is documented as string or `null`, which is what the server returns.
  - CLAUDE.md: corrected password hashing (werkzeug, not bcrypt); added the DB migration table, `LOG_LEVEL` / `FLASK_RUN_*` / `VITE_LOG_LEVEL`, the Vite proxy port, `tools/sync.py`, the test DB-sharing quirk, and a docs map.
  - RECREATE_WITH_CLAUDE.txt: regenerated all embedded server source from the current files (18 of 23 sections had drifted) and updated the schema, endpoints, app.py behaviors, client admin panel, tools and deployment sections.
  - RECREATE_WITH_CHATGPT.txt: marked as historical; version bumped to match.
- Fix: tests now each get their own temp database. `Settings` read env vars once at import time, so every test after the first reused the first test's DB. `server/config.py` now uses `default_factory`; added `server/tests/test_isolation.py`.
- (Superseded by the removal above) Fix: `tools/build_zip.py` crashed with `NameError` (missing `import os`) while writing the source ZIP.
- Removed the ChatGPT-era release-ZIP workflow: `RECREATE_WITH_CHATGPT.txt`, `RECREATE_GUARDRAILS.md`, `tools/build_zip.py`, `tools/release_check.py`. Releases ship through git, GitHub Actions and Railway.
- Removed `justfile` (duplicate of `Makefile`), the empty root `package-lock.json` and `.gitignore~`.
- `.gitignore`: ignore only the root `package-lock.json` so `client/package-lock.json` can be committed (CI's npm cache needs it); also ignore `.pytest_cache/` and `.claude/settings.local.json`.
- The Docker image now includes `tools/`, so `print_db.py` (e.g. `--make-admin`) and `sync.py` can be run on Railway via `railway ssh`.
- Production now runs under gunicorn 26.2.0 (1 worker, 8 threads, `--timeout 0`) instead of Flask's development server, which logged "This is a development server" on Railway. One worker keeps SQLite and the in-memory login rate limiter in a single process; no timeout so the admin sync isn't killed.
- Deployment: Railway now deploys through its GitHub integration (new project on the `dan-claude` account, repo `dan-claude/ia-ratings`). Removed the `deploy` job and `RAILWAY_TOKEN` from CI; docs updated, including `railway ssh` for creating the first production admin.
- (Superseded by the removal above) Fix: release and source ZIPs no longer include `server/app.db` (user emails and password hashes), `client/dist/`, `.claude/settings.local.json`, `.DS_Store` or `*~` backup files.

## Unreleased (between 1.1.44 and 1.2.0, from git history)
- Archive.org login (`AUTH_SCHEME=ia`, default) with auto-created users and `users.ia_username` (migration v4); `--auth-scheme` CLI flag; `GET /api/config`.
- Admin panel in the client (Actions, Criteria, Users, DB Browser, Backup tabs) and the matching admin API.
- Database backup/restore as versioned JSON.
- Security hardening: session cookie flags and 8h lifetime, login/register rate limiting, session rotation on login, `order_by` validation, `password_hash` hidden from the DB browser, restore column validation, safe link rendering in descriptions.
- Description sync now uses aiohttp for concurrent fetches; added `tools/sync.py`.
- Railway deployment: multi-stage Dockerfile, `railway.toml`, GitHub Actions CI with auto-deploy.

## 1.1.44
- Updated API_CLIENT_SERVER.md to include all endpoints implemented in client and server (auth/register, criteria, films/next, admin sync, etc.)

## 1.1.44
- Added binding client–server API contract (API_CLIENT_SERVER.md) and documented recreation rules in RECREATE

## 1.1.43
- Added binding Behavioral Canon for description behavior and added build-time checks to prevent HTML rendering and require API description serialization

## 1.1.42
- Locked in two-ZIP artifact requirement (canonical release + updated source) with build-time enforcement

## 1.1.41
- Enforced build-time check that RECREATE Database Schema (summary) matches server/db.py CREATE TABLE columns

## 1.1.40
- Fixed RECREATE Database Schema (summary) films line to match actual SQLite schema (ia_identifier/description/metadata_json)

## 1.1.39
- Fixed RECREATE films schema summary to include description and correct column names; fixed build invariant to read metadata_json

## 1.1.38
- Fixed Database Schema documentation to explicitly include films.description column

- Documented films.metadata vs films.description (with JSON example) and enforced description normalization invariant in build tooling

## 1.1.37
- Clarified films.metadata vs films.description in Database Schema documentation

- Removed obsolete 'Project Structure (canonical)' subsection (without deleting other documentation) and removed duplicate noisy 'CANONICAL PROJECT STRUCTURE'

- Fixed RECREATE canonical project structure to list all files in the project ZIP
- Updated RECREATE Film Display and Film Panel Layout documentation to match current client behavior (including description)

- tools/build_zip.py now validates that RECREATE CLIENT section matches actual client behavior

- Updated RECREATE client build and runtime description to match actual client behavior

- Updated canonical project structure list to include all project files present in the ZIP (excluding caches/pyc)

- Synchronized canonical project structure with actual ZIP contents (added missing files)

- Documented client film panel layout: description displayed above embedded player

- Client now displays film description above embedded player; layout documented in RECREATE

- Added RECREATE integrity rule and build-time section completeness enforcement; added RECREATE_GUARDRAILS.md documenting process guardrails

- Restored full RECREATE_WITH_CHATGPT.txt instructions after accidental truncation
- Kept corrected canonical project structure (including tools)

- Fixed canonical project structure to include all tools/*.py files

- Updated canonical project structure documentation to match actual release contents

- Added documentation requirement + change-request template to RECREATE_WITH_CHATGPT.txt
- build_zip.py now enforces presence of those RECREATE sections

- Documented IA film description field in RECREATE_WITH_CHATGPT.txt (API + UI)

- Store Internet Archive film description in films table and return it via API
- Display film description above the embed viewer in the client

- Removed legacy ADMIN_TOKEN reference blocking normalized build
- Recomputed normalized Build SHA256
 - 2026-01-26
- Updated RECREATE_WITH_CHATGPT.txt with concrete layout/styling/responsiveness guidance for the scoring grid.
- Updated tools/build_zip.py to exclude .pytest_cache from staged builds.

## 0.4.0 - 2026-01-15
- Refactored Python/Flask backend into an object-oriented, multi-file architecture (services/models/routes/app factory).
- Preserved the same API contract for the React client.

## 0.5.0 - 2026-01-15
- Added a repository (data access) layer and refactored services to use repositories (cleaner separation of concerns).
- App wiring now uses a simple dependency injection pattern: create repositories, then services, then register routes.

## 0.6.0 - 2026-01-15
- Added a repository (data access) layer and refactored services to use repositories (cleaner separation of concerns).
- App wiring now uses a simple dependency injection pattern: create repositories, then services, then register routes.

## 0.7.0 - 2026-01-15
- Added a pytest-based server test suite (auth, criteria, films/ratings, admin sync) using Flask's test client and an isolated SQLite DB per test.
- Added server/requirements-dev.txt and server/pytest.ini.

## 0.8.0 - 2026-01-15
- Added tools/build_zip.py: a deterministic, self-checking zip builder that stages the repo, validates required files (including client/), and verifies ZIP contents.

## 1.1.0 - 2026-01-19
- Improved SQLite ACID behavior and application-level atomicity:
  - Database connections now set `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`, and `foreign_keys=ON`.
  - Rating submission is now atomic: the server upserts the rating row and all criterion scores in a single transaction (`RatingRepository.upsert_rating_with_scores`).
- Test suite import fix (Option A): request helpers moved to `server/tests/helpers.py` and tests import them directly.

## 1.0.8 - 2026-01-15
- Server: serve the built React client (client/dist) directly from the Flask app with SPA fallback routing, eliminating the need for a separate static server in production.


## 1.0.9 - 2026-01-15
- Fixed server/app.py app-factory wiring: removed all import-time use of settings/db and moved it inside create_app().


## 1.1.0 - 2026-01-15
- Standardized Flask blueprint exports to the `*_bp` naming convention across server/routes/* and updated app imports accordingly.


## 1.1.1 - 2026-01-15
- Added logging to server (LOG_LEVEL + request/exception logs) and client (VITE_LOG_LEVEL logger + startup/API logs).

## 1.1.2 - 2026-01-19
- Fixed release ZIP builder semantics and determinism:
  - Build SHA256 now refers to a stable *staged manifest* hash (file paths + contents, with the Build SHA256 line normalized), not the ZIP's own hash.
  - ZIP contents verification now enumerates staged files so it automatically adapts to added/removed files.
  - ZIP creation is now deterministic (sorted file order, fixed timestamps, normalized permissions).


## 1.1.5
- Documented session-based auth, current API routes, and admin model (users.is_admin).

## 1.1.6
- Repaired RECREATE_WITH_CHATGPT.txt version/build-hash consistency and documented normalized build hashing.

## 1.1.7
- Added tools/release_check.py to run pytest and then build the release ZIP via tools/build_zip.py (single-command release workflow).

## 1.1.8
- Added build guardrail: tools/build_zip.py now fails if RECREATE_WITH_CHATGPT.txt omits required CLI tool documentation (including tools/print_db.py).

## 1.1.9
- Documented admin tool requirements in RECREATE_WITH_CHATGPT.txt (admin model via users.is_admin, promotion via tools/print_db.py, and admin endpoint/session requirements).

## 1.1.11
- Canonicalized release after updating print_db.py documentation.
- Bumped version, normalized Build SHA256, and rebuilt ZIP.

## 1.1.12
- Rewrote RECREATE instructions for tools/print_db.py so a fresh session can accurately recreate the CLI tool (flags, DB path resolution, default behavior, and admin mutations).

## 1.1.13
- Added invariants in RECREATE_WITH_CHATGPT.txt for tools/build_zip.py and tools/release_check.py (behavioral contract; bump version if behaviors change).
- Tightened RECREATE tool descriptions to focus on observable behaviors and rebuilt canonical ZIP.

## 1.1.14
- Tightened RECREATE print_db.py section to describe observable behaviors (not implementation) and rebuilt canonical release.

## 1.1.15
- Converted RECREATE print_db.py section to a strictly behavioral contract (no implementation-level details) and rebuilt canonical release.

## 1.1.16
- Documented supported CLI options for tools/build_zip.py, tools/release_check.py, and tools/print_db.py in RECREATE_WITH_CHATGPT.txt (from the actual argparse definitions).

## 1.1.17
- Updated client to match RECREATE UI behavior: one-film-at-a-time rating table/grid, per-criterion validation, archive link + identifier display, JSON submit of integer scores, and cookie-authenticated admin sync.
