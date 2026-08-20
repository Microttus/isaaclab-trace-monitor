#!/usr/bin/env python3
"""Replace public-repository metadata placeholders before the first commit."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNER_FILES = (
    ROOT / "README.md",
    ROOT / "pyproject.toml",
    ROOT / "CITATION.cff",
    ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml",
)
AUTHOR_FILES = (
    ROOT / "LICENSE",
    ROOT / "pyproject.toml",
    ROOT / "AI_ASSISTANCE.md",
    ROOT / "build_macos_app.sh",
)
DEFAULT_AUTHOR = "Martin Økter"
_SKIP_PARTS = {".git", ".venv", ".venv-build", ".venv-dev", "build", "dist"}
_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-owner", required=True, help="GitHub user or organization")
    parser.add_argument(
        "--author-name",
        default=DEFAULT_AUTHOR,
        help=f"Public author/copyright name (default: {DEFAULT_AUTHOR})",
    )
    return parser.parse_args()


def replace_text(path: Path, old: str, new: str) -> bool:
    text = path.read_text(encoding="utf-8")
    updated = text.replace(old, new)
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def update_citation_author(author_name: str) -> bool:
    parts = author_name.strip().split()
    if len(parts) < 2:
        raise ValueError("--author-name must contain given and family names")
    given_names = " ".join(parts[:-1])
    family_names = parts[-1]
    path = ROOT / "CITATION.cff"
    text = path.read_text(encoding="utf-8")
    updated = re.sub(
        r'  - family-names: ".*?"\n    given-names: ".*?"',
        f'  - family-names: "{family_names}"\n    given-names: "{given_names}"',
        text,
        count=1,
    )
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    args = parse_args()
    owner = args.github_owner.strip()
    if not _OWNER_RE.fullmatch(owner):
        raise SystemExit("Invalid GitHub owner name")

    changed: list[Path] = []
    for path in OWNER_FILES:
        if replace_text(path, "GITHUB_OWNER", owner):
            changed.append(path)

    author_name = args.author_name.strip()
    if author_name != DEFAULT_AUTHOR:
        for path in AUTHOR_FILES:
            if replace_text(path, DEFAULT_AUTHOR, author_name):
                changed.append(path)
        if update_citation_author(author_name):
            changed.append(ROOT / "CITATION.cff")

    remaining = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in _SKIP_PARTS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "GITHUB_OWNER" in text:
            remaining.append(path.relative_to(ROOT))

    print(f"Configured repository owner: {owner}")
    print(f"Configured public author:   {author_name}")
    if changed:
        print("Updated files:")
        for path in sorted(set(changed)):
            print(f"  {path.relative_to(ROOT)}")
    if remaining:
        print("Remaining deliberate documentation references:")
        for path in remaining:
            print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
