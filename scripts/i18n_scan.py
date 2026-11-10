"""Scan the project for remaining CJK characters (i18n migration helper).

    .venv\\Scripts\\python.exe scripts\\i18n_scan.py            # remaining CJK lines per file
    .venv\\Scripts\\python.exe scripts\\i18n_scan.py --list     # list line by line
    .venv\\Scripts\\python.exe scripts\\i18n_scan.py --literals # string literals only (UI text)

Exit code is 1 when CJK is still found, so it can be used as a gate.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
# string literals in JS/TS/HTML and Python
LITERAL = re.compile(
    r"""(?<![A-Za-z0-9_])(?:'([^'\n]*)'|"([^"\n]*)"|`([^`]*)`)""",
)

SKIP_DIRS = {".venv", "__pycache__", ".git", ".artifacts", "node_modules", "docs"}
TEXT_SUFFIXES = {".py", ".js", ".mjs", ".html", ".css", ".ps1", ".sh", ".yaml", ".yml", ".md", ".json"}


def iter_files():
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES:
            yield path


def literals_of(text: str):
    for match in LITERAL.finditer(text):
        value = match.group(1) or match.group(2) or match.group(3) or ""
        if CJK.search(value):
            yield value.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true", help="list line by line (with line numbers)")
    parser.add_argument("--literals", action="store_true", help="count string literals only")
    args = parser.parse_args()

    total_lines = 0
    total_files = 0
    for path in sorted(iter_files()):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        lines = [line for line in text.splitlines() if CJK.search(line)]
        literal_hits = list(literals_of(text))
        if args.literals and not literal_hits:
            continue
        if not lines:
            continue

        total_files += 1
        total_lines += len(lines)
        rel = path.relative_to(PROJECT_ROOT)
        if args.literals:
            print(f"{rel}: {len(literal_hits)} Chinese string literals")
            for value in literal_hits[:200]:
                print(f"    {value}")
        elif args.list:
            print(f"=== {rel} ({len(lines)} lines)")
            for index, line in enumerate(text.splitlines(), start=1):
                if CJK.search(line):
                    print(f"  {index:>4}: {line.strip()[:150]}")
        else:
            print(f"{len(lines):>4}  {rel}")

    if not args.list and not args.literals:
        print(f"\nTotal {total_files} files / {total_lines} lines still contain non-ASCII Chinese")
    return 1 if total_files else 0


if __name__ == "__main__":
    sys.exit(main())
