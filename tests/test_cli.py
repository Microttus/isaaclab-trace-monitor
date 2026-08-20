from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import types
from pathlib import Path

from isaaclab_trace_monitor import cli

ROOT = Path(__file__).resolve().parents[1]


def test_version_does_not_import_gui_dependencies() -> None:
    script = textwrap.dedent(
        """
        import builtins

        real_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name.startswith(("PySide6", "matplotlib")):
                raise AssertionError(f"GUI dependency imported for --version: {name}")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = guarded_import
        from isaaclab_trace_monitor.cli import main
        main(["--version"])
        """
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "1.3.0" in result.stdout


def test_cli_preserves_remote_source(monkeypatch) -> None:
    received: dict[str, object] = {}
    fake_app = types.ModuleType("isaaclab_trace_monitor.app")

    def run_application(**kwargs):
        received.update(kwargs)
        return 17

    fake_app.run_application = run_application  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "isaaclab_trace_monitor.app", fake_app)

    result = cli.main(
        [
            "coder.example:/home/coder/run/object_traces",
            "--refresh",
            "3.5",
            "--smoke-test",
        ]
    )

    assert result == 17
    assert received == {
        "source": "coder.example:/home/coder/run/object_traces",
        "refresh_period": 3.5,
        "smoke_test": True,
    }
