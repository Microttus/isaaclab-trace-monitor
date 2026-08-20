"""Isaac Lab trace monitor package."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("isaaclab-trace-monitor")
except PackageNotFoundError:
    # Source-tree fallback used before the package is installed.
    __version__ = "1.3.0"

__all__ = ["__version__"]
