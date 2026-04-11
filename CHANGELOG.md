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
