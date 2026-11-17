## Unreleased
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
