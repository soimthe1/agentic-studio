"""Public-release check: refuses a public copy that still carries any organisation detail.

Run before publishing to GitHub:   python scripts/release_check.py            (exit 1 = not ready)
What it looks for is listed in PATTERNS; files that never go public (secrets, local data, the organisation's own
config/local, branding/brand.local, docs/local) are skipped. The organisation's own words: config/local/release-words.txt
(one regular expression per line) or --also "word1,word2".
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Generic patterns only: the organisation's own words live in config/local/release-words.txt (one regex per line,
# never committed), so this file itself carries no organisation detail.
PATTERNS = {
    "private network address": r"\b(10\.\d{1,3}|192\.168|172\.(1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b",
    "e-mail address": r"[A-Za-z0-9._%+-]+@(?![\w.-]*example\.(org|com)\b)[A-Za-z0-9.-]+\.[a-z]{2,}",
}
WORDS = ROOT / "config" / "local" / "release-words.txt"
SKIP_DIRS = {".git", ".venv", "node_modules", "dist", "data", "__pycache__", ".pytest_cache", "logs", "local", "brand.local"}
SKIP_FILES = {"HANDOVER.md", "CLAUDE.md"}
SKIP_PREFIXES = (".env",)
SKIP_PATHS = ("config/local/", "branding/brand.local/", "docs/local/")   # never committed (.gitignore)
TEXT = {".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".yaml", ".yml", ".md", ".html", ".css", ".ps1", ".sh", ".toml",
        ".txt", ".cfg", ".ini", ".svg", ".example", ""}


def files():
    import os

    for base, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]   # never walk into them
        for name in names:
            p = Path(base) / name
            rel = p.relative_to(ROOT).as_posix()
            if name in SKIP_FILES or rel.startswith(SKIP_PATHS):
                continue
            if name.startswith(SKIP_PREFIXES) and not name.endswith(".example"):
                continue
            if p.suffix.lower() in TEXT and p.stat().st_size < 3_000_000:
                yield rel, p


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--also", default="", help="extra comma-separated words that must not appear")
    ap.add_argument("--show", type=int, default=5, help="examples to show per kind")
    args = ap.parse_args()
    pats = dict(PATTERNS)
    if WORDS.is_file():
        for n, w in enumerate(l.strip() for l in WORDS.read_text(encoding="utf-8").splitlines()):
            if w and not w.startswith("#"):
                pats[f"organisation word #{n + 1}"] = w
    for w in filter(None, (x.strip() for x in args.also.split(","))):
        pats[f"word '{w}'"] = re.escape(w)
    found: dict[str, list[str]] = {k: [] for k in pats}
    for rel, p in files():
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for kind, pat in pats.items():
            for n, line in enumerate(text.splitlines(), 1):
                if re.search(pat, line) and "release-ok" not in line:   # deliberate generic sample, marked in place
                    found[kind].append(f"{rel}:{n}: {line.strip()[:110]}")
    bad = {k: v for k, v in found.items() if v}
    for kind, hits in bad.items():
        files_hit = len({h.split(':')[0] for h in hits})
        print(f"\n{kind}: {len(hits)} lines in {files_hit} files")
        for h in hits[: args.show]:
            print("  " + h)
    print("\nNOT READY for a public release." if bad else "Ready: no organisation details found.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
