#!/usr/bin/env python3
"""Collect license/notice files from installed build and runtime packages."""

from __future__ import annotations

import argparse
import shutil
from importlib import metadata
from pathlib import Path

DISTRIBUTIONS = (
    "PySide6-Essentials",
    "shiboken6",
    "matplotlib",
    "numpy",
    "pyinstaller",
    "pillow",
)
LICENSE_PREFIXES = ("license", "copying", "notice", "copyright")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest: list[str] = []

    for distribution_name in DISTRIBUTIONS:
        try:
            dist = metadata.distribution(distribution_name)
        except metadata.PackageNotFoundError:
            manifest.append(f"{distribution_name}: not installed")
            continue

        installed_name = dist.metadata.get("Name", distribution_name)
        installed_version = dist.version
        destination = output / safe_name(f"{installed_name}-{installed_version}")
        copied = 0
        for item in dist.files or ():
            basename = Path(str(item)).name.lower()
            if not basename.startswith(LICENSE_PREFIXES):
                continue
            source = Path(dist.locate_file(item))
            if not source.is_file() or source.stat().st_size > 5_000_000:
                continue
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / safe_name(Path(str(item)).name)
            if target.exists():
                target = destination / f"{copied:02d}_{target.name}"
            shutil.copy2(source, target)
            copied += 1

        license_expression = dist.metadata.get("License-Expression")
        legacy_license = dist.metadata.get("License")
        license_value = license_expression or legacy_license or "unspecified"
        license_summary = " ".join(license_value.split())[:240]
        manifest.append(
            f"{installed_name} {installed_version}: copied {copied} file(s); "
            f"license metadata={license_summary}"
        )

    (output / "MANIFEST.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
