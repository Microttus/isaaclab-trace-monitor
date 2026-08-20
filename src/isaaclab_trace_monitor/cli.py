"""Command-line interface with deferred GUI imports.

Keeping this module free of Qt and Matplotlib imports allows metadata commands
such as ``--version`` to work even when a desktop session is unavailable.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import sys
from importlib import metadata
from typing import Sequence

from isaaclab_trace_monitor import __version__

_LINUX_RUNTIME_HINT = """On Ubuntu/Debian, install the desktop runtime with:
  sudo apt-get update
  sudo apt-get install -y \\
    python3-venv rsync openssh-client \\
    libegl1 libgl1 libopengl0 libdbus-1-3 libfontconfig1 libfreetype6 \\
    libx11-6 libx11-xcb1 libxext6 libxrender1 libxi6 libsm6 libice6 \\
    libxcb1 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \\
    libxcb-randr0 libxcb-render0 libxcb-render-util0 libxcb-shape0 \\
    libxcb-shm0 libxcb-sync1 libxcb-util1 libxcb-xfixes0 \\
    libxcb-xinerama0 libxcb-xkb1 libxkbcommon0 libxkbcommon-x11-0
"""


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the public command-line parser without importing GUI modules."""
    parser = argparse.ArgumentParser(
        prog="isaaclab-trace-monitor",
        description="Offline and live monitor for Isaac Lab object trajectory logs.",
    )
    parser.add_argument(
        "source",
        nargs="?",
        default="",
        help="Local object_traces directory or host:/absolute/object_traces path.",
    )
    parser.add_argument(
        "--refresh",
        type=float,
        default=2.0,
        help="Automatic refresh period in seconds (default: 2.0).",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Check Python, Qt, Matplotlib, SSH, and rsync availability, then exit.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def _distribution_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "not installed"


def diagnose_runtime() -> int:
    """Print deterministic runtime diagnostics without creating a window."""
    os.environ.setdefault("QT_API", "pyside6")
    lines = [
        f"IsaacLab Trace Monitor: {__version__}",
        f"Python: {platform.python_version()} ({sys.executable})",
        f"Platform: {platform.platform()}",
        f"Architecture: {platform.machine()}",
        f"QT_API: {os.environ.get('QT_API', '-')}",
        f"QT_QPA_PLATFORM: {os.environ.get('QT_QPA_PLATFORM', '-')}",
        f"DISPLAY: {os.environ.get('DISPLAY', '-')}",
        f"WAYLAND_DISPLAY: {os.environ.get('WAYLAND_DISPLAY', '-')}",
        f"PySide6-Essentials: {_distribution_version('PySide6-Essentials')}",
        f"Matplotlib: {_distribution_version('matplotlib')}",
        f"NumPy: {_distribution_version('numpy')}",
        f"ssh: {shutil.which('ssh') or 'not found'}",
        f"rsync: {shutil.which('rsync') or 'not found'}",
    ]

    errors: list[str] = []
    try:
        import PySide6
        from PySide6.QtCore import QLibraryInfo, qVersion
        from PySide6.QtGui import QGuiApplication  # noqa: F401
        from PySide6.QtWidgets import QApplication  # noqa: F401

        lines.append(f"PySide6 import: OK ({PySide6.__version__})")
        lines.append(f"Qt runtime: {qVersion()}")
        try:
            plugin_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
        except AttributeError:
            plugin_path = QLibraryInfo.location(QLibraryInfo.PluginsPath)
        lines.append(f"Qt plugins: {plugin_path}")
    except (ImportError, OSError) as error:
        errors.append(f"PySide6 import failed: {error!r}")

    try:
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: F401

        lines.append("Matplotlib QtAgg import: OK")
    except (ImportError, OSError) as error:
        errors.append(f"Matplotlib QtAgg import failed: {error!r}")

    print("\n".join(lines))
    if errors:
        print("\nRuntime errors:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        if sys.platform.startswith("linux"):
            print(f"\n{_LINUX_RUNTIME_HINT}", file=sys.stderr)
        return 1
    return 0


def _print_gui_import_error(error: BaseException) -> None:
    print("IsaacLab Trace Monitor could not load its Qt GUI.", file=sys.stderr)
    print(f"Cause: {error!r}", file=sys.stderr)
    print(
        "Run 'isaaclab-trace-monitor --diagnose' for dependency details.",
        file=sys.stderr,
    )
    if sys.platform.startswith("linux"):
        print(f"\n{_LINUX_RUNTIME_HINT}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse CLI options and import the Qt application only when required."""
    arguments = build_argument_parser().parse_args(argv)
    if arguments.diagnose:
        return diagnose_runtime()

    os.environ.setdefault("QT_API", "pyside6")
    try:
        from isaaclab_trace_monitor.app import run_application
    except (ImportError, OSError) as error:
        _print_gui_import_error(error)
        return 2

    return run_application(
        source=arguments.source,
        refresh_period=arguments.refresh,
        smoke_test=arguments.smoke_test,
    )


__all__ = ["build_argument_parser", "diagnose_runtime", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
