from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACE_ROOT = ROOT / "example_object_traces"


def test_monitor_window_constructs_and_loads_example() -> None:
    os.environ.setdefault("QT_API", "pyside6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    from isaaclab_trace_monitor.app import MonitorWindow

    application = QApplication.instance() or QApplication([])
    window = MonitorWindow(str(TRACE_ROOT), refresh_period=30.0)
    window.show()

    for _ in range(8):
        application.processEvents()

    assert window.source_root == TRACE_ROOT.resolve()
    assert window.trace is not None
    assert window.trace.row_count > 0
    assert window.trajectory_view.trace is window.trace

    window.close()
    application.processEvents()
