#!/usr/bin/env python3
"""
tools/build_zip.py

Creates a release ZIP for the IA Film Rater project with strict validation.

Key properties:
- Deterministic file selection + stable ordering
- Excludes caches/venvs/node_modules
- Fails fast if docs/spec drift is detected
- Uses NORMALIZED Build SHA256 hashing to avoid self-referential hashing:
  When computing the build hash, treat the line `Build SHA256: <value>` inside
  RECREATE_WITH_CHATGPT.txt as `Build SHA256: TBD`, then SHA-256 the ZIP bytes.
- Outputs: /mnt/data/release_v{version}.zip
"""
from __future__ import annotations




def _parse_create_table_columns(db_py_text: str) -> dict:
    """Return {table_name: [col1, col2, ...]} parsed from server/db.py CREATE TABLE statements."""
    tables = {}
    # Match CREATE TABLE IF NOT EXISTS <name> ( ... );
    for m in re.finditer(r"(?is)CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)\s*\((.*?)\)\s*;", db_py_text):
        name = m.group(1)
        body = m.group(2)
        cols = []
        for line in body.splitlines():
            line = line.strip().rstrip(',')
            if not line:
                continue
            # Skip table constraints
            if line.upper().startswith("PRIMARY KEY") or line.upper().startswith("FOREIGN KEY") or line.upper().startswith("UNIQUE") or line.upper().startswith("CHECK"):
                continue
            # Column name is first token
            col = line.split()[0].strip('"`[]')
            cols.append(col)
        if cols:
            tables[name] = cols
    return tables

def _extract_recreate_schema_summary(recreate_text: str) -> dict:
    """Return {table_name: [col1, col2, ...]} from Database Schema (summary) lines like '- films(a,b,c)'."""
    m = re.search(r"(?ms)^Database Schema \(summary\)\s*\n(.*?)(?=\n[A-Z][A-Z0-9 _-]{3,}\n|\Z)", recreate_text)
    if not m:
        return {}
    section = m.group(1)
    out = {}
    for ln in section.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        ln = re.sub(r"^[-*•]\s+", "", ln)
        mm = re.match(r"^(\w+)\(([^)]*)\)\s*$", ln)
        if not mm:
            continue
        name = mm.group(1)
        cols = [c.strip() for c in mm.group(2).split(',') if c.strip()]
        out[name] = cols
    return out

def _assert_recreate_schema_matches_db(project_root: str, recreate_text: str) -> None:
    """Fail build if RECREATE Database Schema (summary) does not match server/db.py CREATE TABLE columns."""
    db_py_path = os.path.join(project_root, "server", "db.py")
    if not os.path.exists(db_py_path):
        return
    db_py_text = Path(db_py_path).read_text(encoding="utf-8")
    db_tables = _parse_create_table_columns(db_py_text)
    rec_tables = _extract_recreate_schema_summary(recreate_text)

    if not rec_tables:
        raise SystemExit("ERROR: RECREATE_WITH_CHATGPT.txt missing or unparsable 'Database Schema (summary)' section.")

    # Check each table listed in RECREATE exists in db.py and matches columns (order-sensitive)
    for tname, rec_cols in rec_tables.items():
        if tname not in db_tables:
            raise SystemExit(f"ERROR: RECREATE schema lists table '{tname}' but server/db.py does not define it.")
        db_cols = db_tables[tname]
        if rec_cols != db_cols:
            raise SystemExit(
                "ERROR: RECREATE schema mismatch for table '%s'.\n"
                "RECREATE: %s\n"
                "db.py   : %s\n" % (tname, rec_cols, db_cols)
            )


def _assert_description_normalized(project_root: str) -> None:
    """Verify that if metadata.description exists, films.description is populated.

    This check is only performed when a SQLite DB file exists at server/app.db.
    """
    import os, sqlite3, json
    db_path = os.path.join(project_root, "server", "app.db")
    if not os.path.exists(db_path):
        return
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT metadata_json, description FROM films").fetchall()
    except Exception:
        conn.close()
        return
    for r in rows:
        if not r["metadata_json"]:
            continue
        try:
            meta = json.loads(r["metadata_json"])
        except Exception:
            continue
        if meta.get("description") and not (r["description"] or "").strip():
            conn.close()
            raise SystemExit("ERROR: Invariant violated: metadata.description present but films.description is empty.")
    conn.close()


def _extract_section(text: str, header: str) -> str:
    """Extract a top-level ALL-CAPS section by header name."""
    pattern = rf"(?s)^{re.escape(header)}\s*\n(.*?)(?=\n[A-Z][A-Z0-9 _-]{3,}\n|\Z)"
    m = re.search(pattern, text, flags=re.MULTILINE)
    return m.group(1).strip() if m else ""

def _assert_client_doc_matches(project_root: str, recreate_text: str) -> None:
    """Fail the build if RECREATE's CLIENT section doesn't match actual client behavior."""
    client_section = _extract_section(recreate_text, "CLIENT")
    if not client_section:
        raise SystemExit("ERROR: RECREATE_WITH_CHATGPT.txt missing required CLIENT section.")

    import json
    pkg_path = os.path.join(project_root, "client", "package.json")
    app_path = os.path.join(project_root, "client", "src", "App.jsx")
    try:
        pkg = json.loads(Path(pkg_path).read_text(encoding="utf-8"))
        app = Path(app_path).read_text(encoding="utf-8")
    except Exception as e:
        raise SystemExit(f"ERROR: Unable to read client files for documentation validation: {e}")

    deps = (pkg.get("dependencies") or {})
    devdeps = (pkg.get("devDependencies") or {})
    scripts = (pkg.get("scripts") or {})

    is_vite = ("vite" in deps) or ("vite" in devdeps)
    has_dev = "dev" in scripts
    has_build = "build" in scripts

    uses_api_me = "/api/me" in app
    uses_api_films = "/api/films" in app

    desc_pos = app.find("film.description")
    iframe_pos = app.find("<iframe")
    desc_above_iframe = (desc_pos != -1 and iframe_pos != -1 and desc_pos < iframe_pos)

    def must_contain(needle: str, msg: str):
        if needle.lower() not in client_section.lower():
            raise SystemExit("ERROR: CLIENT section mismatch: " + msg + f" (missing '{needle}')")

    if is_vite:
        must_contain("Vite", "client uses Vite but CLIENT section does not mention Vite")
    if has_dev:
        must_contain("npm run dev", "client has a dev script but CLIENT section does not document 'npm run dev'")
    if has_build:
        must_contain("npm run build", "client has a build script but CLIENT section does not document 'npm run build'")
    if uses_api_me:
        must_contain("/api/me", "client calls /api/me but CLIENT section does not document it")
    if uses_api_films:
        must_contain("/api/films", "client calls /api/films* but CLIENT section does not document it")
    if desc_above_iframe:
        must_contain("above", "client renders description above embedded player but CLIENT section does not state it")
        must_contain("description", "client renders description but CLIENT section does not document it")


REQUIRED_RECREATE_CLAUDE_MARKERS = {
    "FILE: server/repositories/film_repo.py",
    "FILE: server/services/ia_service.py",
    "FILE: server/app.py",
    "CLIENT: App.jsx",
    "CHANGELOG",
    "fetch_description_html",
    "_html_to_text",
    "--with-client",
    "syncing",
}


def ensure_recreate_claude_valid(root: Path) -> None:
    """Fail the build if RECREATE_WITH_CLAUDE.txt is missing or out of date."""
    claude_path = root / "RECREATE_WITH_CLAUDE.txt"
    if not claude_path.exists():
        die("RECREATE_WITH_CLAUDE.txt is missing.")
    text = read_text(claude_path)
    for marker in REQUIRED_RECREATE_CLAUDE_MARKERS:
        if marker not in text:
            die(f"RECREATE_WITH_CLAUDE.txt missing required marker: '{marker}' — "
                f"update the file to reflect recent code changes.")

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path
from typing import Iterable, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]

EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
}

EXCLUDE_FILE_SUFFIXES = {".pyc"}

REQUIRED_TOP_LEVEL = {
    "client",
    "server",
    "tools",
    "RECREATE_WITH_CHATGPT.txt",
    "README.md",
    "CHANGELOG.md",
}

FORBIDDEN_STRINGS_IN_README = {"ADMIN_TOKEN"}

REQUIRED_RECREATE_MARKERS = {
    "tools/build_zip.py",
    "tools/release_check.py",
    "tools/print_db.py",
    "Admin tool requirements",
    "DOCUMENTATION REQUIREMENT (NON-NEGOTIABLE)",
    "CHANGE REQUEST TEMPLATE (COPY/PASTE)",
}


FIXED_ZIP_DATETIME = (1980, 1, 1, 0, 0, 0)  # stable timestamps


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def write_text(p: Path, s: str) -> None:
    p.write_text(s, encoding="utf-8")


def parse_version_from_recreate(recreate_text: str) -> str:
    m = re.search(r"(?m)^Version:\s*([0-9]+\.[0-9]+\.[0-9]+)\s*$", recreate_text)
    if not m:
        die("RECREATE_WITH_CHATGPT.txt missing 'Version: x.y.z'.")
    return m.group(1)


def parse_top_version_from_changelog(changelog_text: str) -> str | None:
    m = re.search(r"(?m)^##\s*([0-9]+\.[0-9]+\.[0-9]+)\s*$", changelog_text)
    return m.group(1) if m else None


def ensure_required_structure(root: Path) -> None:
    for name in REQUIRED_TOP_LEVEL:
        if not (root / name).exists():
            die(f"Missing required top-level item: {name}")


def ensure_readme_no_forbidden(root: Path) -> None:
    readme = read_text(root / "README.md")
    for s in FORBIDDEN_STRINGS_IN_README:
        if s in readme:
            die(f"README.md contains forbidden legacy string: {s}")


def ensure_recreate_contains_required_markers(root: Path) -> None:
    text = read_text(root / "RECREATE_WITH_CHATGPT.txt")
    for m in REQUIRED_RECREATE_MARKERS:
        if m not in text:
            die(f"RECREATE_WITH_CHATGPT.txt missing required documentation marker: {m}")


def ensure_recreate_matches_changelog(root: Path) -> str:
    recreate = read_text(root / "RECREATE_WITH_CHATGPT.txt")
    version = parse_version_from_recreate(recreate)
    chlog = read_text(root / "CHANGELOG.md")
    top = parse_top_version_from_changelog(chlog)
    if top and top != version:
        die(f"Version mismatch: RECREATE {version} vs CHANGELOG top {top}.")
    return version


def iter_files_for_zip(root: Path) -> list[Tuple[Path, Path]]:
    files: list[Tuple[Path, Path]] = []
    for abs_path in root.rglob("*"):
        rel = abs_path.relative_to(root)
        if abs_path.is_dir():
            continue
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if abs_path.suffix in EXCLUDE_FILE_SUFFIXES:
            continue
        files.append((abs_path, rel))
    files.sort(key=lambda t: str(t[1]).lower())
    return files


def normalize_recreate_line(text: str) -> str:
    return re.sub(r"(?m)^Build SHA256:\s*.*$", "Build SHA256: TBD", text)


def sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()


def build_zip_bytes(root: Path, force_recreate_tbd: bool) -> bytes:
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, strict_timestamps=False) as zf:
        for abs_path, rel_path in iter_files_for_zip(root):
            arcname = str(rel_path).replace("\\", "/")
            info = zipfile.ZipInfo(arcname, date_time=FIXED_ZIP_DATETIME)
            info.compress_type = zipfile.ZIP_DEFLATED

            if arcname == "RECREATE_WITH_CHATGPT.txt" and force_recreate_tbd:
                normalized = normalize_recreate_line(read_text(abs_path))
                zf.writestr(info, normalized.encode("utf-8"))
            else:
                zf.writestr(info, abs_path.read_bytes())
    return buf.getvalue()


def _build_source_zip(project_root: str, version: str, out_dir: str = "/mnt/data") -> str:
    """Create an updated source ZIP (full tree) alongside the canonical release ZIP."""
    import os, zipfile

    out_path = os.path.join(out_dir, f"source_v{version}.zip")

    def is_noise(rel: str) -> bool:
        parts = rel.split("/")
        skip_dirs = {".venv", "node_modules", "__pycache__", ".pytest_cache", ".git", ".mypy_cache", ".ruff_cache"}
        if any(part in skip_dirs for part in parts):
            return True
        if rel.endswith(".pyc"):
            return True
        return False

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(project_root):
            for fn in files:
                # Skip generated release zip(s) that may exist in tree
                if fn.startswith("release_v") and fn.endswith(".zip"):
                    continue
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, project_root).replace("\\", "/")
                if is_noise(rel):
                    continue
                zf.write(full, rel)
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="/mnt/data")
    args = ap.parse_args()

    root = PROJECT_ROOT

    # Preflight
    ensure_required_structure(root)
    ensure_readme_no_forbidden(root)
    ensure_recreate_contains_required_markers(root)
    ensure_recreate_claude_valid(root)
    version = ensure_recreate_matches_changelog(root)

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_zip = out_dir / f"release_v{version}.zip"

    # Normalized hash (RECREATE forced to TBD in zip bytes)
    zip_bytes_norm = build_zip_bytes(root, force_recreate_tbd=True)
    normalized_sha = sha256_bytes(zip_bytes_norm)

    # Write normalized hash into RECREATE in working tree
    rp = root / "RECREATE_WITH_CHATGPT.txt"
    rt = read_text(rp)
    rt = re.sub(r"(?m)^Build SHA256:\s*.*$", f"Build SHA256: {normalized_sha}", rt)
    write_text(rp, rt)

    # Final zip bytes and raw sha
    zip_bytes_final = build_zip_bytes(root, force_recreate_tbd=False)
    raw_sha = sha256_bytes(zip_bytes_final)
    out_zip.write_bytes(zip_bytes_final)

    # Postflight: ensure normalized hash is stable + recorded
    zip_bytes_norm_again = build_zip_bytes(root, force_recreate_tbd=True)
    norm_again = sha256_bytes(zip_bytes_norm_again)
    recorded = re.search(r"(?m)^Build SHA256:\s*([0-9a-f]{64})\s*$", read_text(rp))
    if not recorded:
        die("Postflight: RECREATE missing 64-hex Build SHA256.")
    if recorded.group(1) != norm_again:
        die("Postflight: normalized hash mismatch.")
    # Ensure required items inside zip
    with zipfile.ZipFile(out_zip, "r") as zf:
        names = zf.namelist()
        for bad in EXCLUDE_DIRS:
            for n in names:
                if n.startswith(f"{bad}/") or f"/{bad}/" in n:
                    die(f"Postflight: excluded directory '{bad}' found in zip as '{n}'.")
        required = {"client/", "server/", "tools/", "RECREATE_WITH_CHATGPT.txt", "README.md", "CHANGELOG.md"}
        for req in required:
            if req.endswith("/"):
                if not any(n.startswith(req) for n in names):
                    die(f"Postflight: missing required directory '{req}' in zip.")
            else:
                if req not in names:
                    die(f"Postflight: missing required file '{req}' in zip.")

    print("OK")
    print(f"Version: {version}")
    print(f"Output:  {out_zip}")
    print(f"Build SHA256 (normalized): {normalized_sha}")

    # HARD REQUIREMENT: also build updated source ZIP
    source_zip_path = _build_source_zip(root, version, out_dir=str(out_dir))
    if not Path(source_zip_path).exists():
        raise SystemExit(f"ERROR: Expected source ZIP not created: {source_zip_path}")
    print(f"Source ZIP Output: {source_zip_path}")
    print(f"ZIP SHA256 (raw):         {raw_sha}")


if __name__ == "__main__":
    main()

def _assert_no_dangerous_inner_html(project_root: str) -> None:
    import os
    client_root = os.path.join(project_root, "client", "src")
    if not os.path.exists(client_root):
        return
    bad = []
    for root, _, files in os.walk(client_root):
        for fn in files:
            if not fn.endswith((".js", ".jsx", ".ts", ".tsx")):
                continue
            p = os.path.join(root, fn)
            txt = Path(p).read_text(encoding="utf-8", errors="ignore")
            if "dangerouslySetInnerHTML" in txt:
                bad.append(os.path.relpath(p, project_root))
    if bad:
        raise SystemExit("ERROR: Client must not use dangerouslySetInnerHTML (plain-text description required). Found in: " + ", ".join(bad))

def _assert_api_includes_description(project_root: str) -> None:
    import os, re
    server_root = os.path.join(project_root, "server")
    # crude but effective: require at least one occurrence of '"description"' in routes/ or serialization code
    hits = 0
    for root, _, files in os.walk(server_root):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(root, fn)
            txt = Path(p).read_text(encoding="utf-8", errors="ignore")
            if re.search(r'["\']description["\']\s*:', txt):
                hits += 1
    if hits == 0:
        raise SystemExit("ERROR: API serialization must include a 'description' field in film objects (no occurrences found).")
