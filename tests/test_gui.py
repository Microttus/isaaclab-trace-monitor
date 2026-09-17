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


def test_signals_tab_and_archived_trace_selection() -> None:
    os.environ.setdefault("QT_API", "pyside6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    from isaaclab_trace_monitor.app import MonitorWindow

    application = QApplication.instance() or QApplication([])
    window = MonitorWindow(str(TRACE_ROOT), refresh_period=30.0)
    window.show()

    for _ in range(8):
        application.processEvents()

    assert window.tabs.isTabEnabled(window.signals_tab_index)
    assert window.signals_view.trace is window.trace
    assert window.signals_view.cursors
    combo = window.signals_view.sensor_combo
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "left_finger",
        "right_finger",
        "pin_tip",
    ]

    labels = [window.trace_combo.itemText(i) for i in range(window.trace_combo.count())]
    assert "Episode 0 (archived)" in labels
    window.trace_combo.setCurrentIndex(labels.index("Episode 0 (archived)"))
    for _ in range(4):
        application.processEvents()

    assert window.trace is not None
    assert window.trace.path.parent.parent.name == "archive"
    assert window.trace.row_count == 180
    assert window.signals_view.trace is window.trace

    window.close()
    application.processEvents()
