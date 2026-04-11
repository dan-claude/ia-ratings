#!/usr/bin/env python3
"""
tools/release_check.py

One-command release helper:
- Runs server/unit tests (pytest)
- Runs build validations + creates release ZIP via tools/build_zip.py

Usage:
  python tools/release_check.py
  python tools/release_check.py --out-dir /mnt/data
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="/mnt/data", help="Where to write the release zip")
    args = ap.parse_args()

    # Python tests (server)
    run([sys.executable, "-m", "pytest", "-q"])

    # Build release zip (includes strict validation + normalized build hashing)
    run([sys.executable, "tools/build_zip.py", "--out-dir", args.out_dir])

    print("Release check OK.")

if __name__ == "__main__":
    main()
