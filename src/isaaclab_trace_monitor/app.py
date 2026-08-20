"""PySide6 desktop application for Isaac Lab trajectory logs."""

from __future__ import annotations

import csv
import math
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import (
    QProcess,
    QProcessEnvironment,
    QSettings,
    QSignalBlocker,
    QTimer,
    Qt,
)
from PySide6.QtGui import QAction, QCloseEvent, QFont, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QStyle,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT,
)
from matplotlib.figure import Figure

from isaaclab_trace_monitor import __version__
from isaaclab_trace_monitor.data import (
    CsvTable,
    TraceData,
    TraceFile,
    discover_env_ids,
    discover_trace_files,
    file_signature,
    find_trace_root,
    load_json,
    load_summary,
    load_trace,
    moving_mean,
)
from isaaclab_trace_monitor.source import (
    SourceSpec,
    cache_directory,
    rsync_arguments,
)


class TrajectoryView(QWidget):
    """Matplotlib view containing path, coordinate, and reward plots."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.figure = Figure(constrained_layout=True)
        grid = self.figure.add_gridspec(2, 2, width_ratios=(1.35, 1.0))
        self.path_axes = self.figure.add_subplot(grid[:, 0], projection="3d")
        self.coordinate_axes = self.figure.add_subplot(grid[0, 1])
        self.reward_axes = self.figure.add_subplot(grid[1, 1])
        self.return_axes = self.reward_axes.twinx()
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, 1)

        self.trace: TraceData | None = None
        self.selected_prefix = ""
        self.path_lines: dict[str, Any] = {}
        self.trail_lines: dict[str, Any] = {}
        self.markers: dict[str, Any] = {}
        self.coordinate_cursor: Any | None = None
        self.reward_cursor: Any | None = None
        self.orientation_handles: list[Any] = []
        self.orientation_scale = 0.01
        self.frame_index = 0
        self._show_empty_state()

    def _show_empty_state(self) -> None:
        self.path_axes.clear()
        self.coordinate_axes.clear()
        self.reward_axes.clear()
        self.return_axes.clear()
        self.path_axes.set_title("Open an object_traces source")
        self.path_axes.set_xlabel("x [m]")
        self.path_axes.set_ylabel("y [m]")
        self.path_axes.set_zlabel("z [m]")
        self.coordinate_axes.set_title("Selected-object coordinates")
        self.reward_axes.set_title("Reward and cumulative return")
        self.canvas.draw_idle()

    def load_trace(self, trace: TraceData, selected_prefix: str | None = None) -> None:
        """Loads a trace and creates static/dynamic plot artists."""
        previous_elevation = self.path_axes.elev
        previous_azimuth = self.path_axes.azim
        self.trace = trace
        self.frame_index = 0
        self.path_lines.clear()
        self.trail_lines.clear()
        self.markers.clear()
        self._remove_orientation()

        self.path_axes.clear()
        all_positions: list[np.ndarray] = []
        for obj in trace.objects:
            positions = trace.position(obj)
            finite_rows = np.all(np.isfinite(positions), axis=1)
            if not np.any(finite_rows):
                continue
            finite_positions = positions[finite_rows]
            all_positions.append(finite_positions)
            (full_line,) = self.path_axes.plot(
                finite_positions[:, 0],
                finite_positions[:, 1],
                finite_positions[:, 2],
                linestyle=":",
                linewidth=1.0,
                label=obj.name,
            )
            color = full_line.get_color()
            (trail_line,) = self.path_axes.plot(
                [],
                [],
                [],
                linewidth=2.0,
                color=color,
            )
            marker = self.path_axes.scatter([], [], [], s=48, color=color)
            first = finite_positions[0]
            self.path_axes.scatter(
                [first[0]],
                [first[1]],
                [first[2]],
                s=28,
                facecolors="none",
                edgecolors=color,
            )
            self.path_lines[obj.prefix] = full_line
            self.trail_lines[obj.prefix] = trail_line
            self.markers[obj.prefix] = marker

        self.path_axes.grid(True)
        self.path_axes.set_xlabel("x [m]")
        self.path_axes.set_ylabel("y [m]")
        self.path_axes.set_zlabel("z [m]")
        self.path_axes.set_title(self._trace_title(trace))
        if self.path_lines:
            self.path_axes.legend(loc="best")
        if all_positions:
            combined = np.vstack(all_positions)
            self._set_equal_limits(combined)
            span = np.ptp(combined, axis=0)
            self.orientation_scale = max(float(np.nanmax(span)) * 0.08, 0.005)
        self.path_axes.view_init(elev=previous_elevation, azim=previous_azimuth)

        prefixes = {obj.prefix for obj in trace.objects}
        if selected_prefix in prefixes:
            self.selected_prefix = str(selected_prefix)
        elif trace.objects:
            preferred = next(
                (
                    obj.prefix
                    for obj in trace.objects
                    if "ee" in obj.name.lower() or "tool" in obj.name.lower()
                ),
                trace.objects[0].prefix,
            )
            self.selected_prefix = preferred
        else:
            self.selected_prefix = ""

        self._draw_selected_curves()
        self.set_frame(0, trail_samples=0, show_orientation=True)

    def set_selected_object(self, prefix: str) -> None:
        """Changes the object shown in the detailed coordinate plot."""
        if self.trace is None or prefix == self.selected_prefix:
            return
        if prefix not in {obj.prefix for obj in self.trace.objects}:
            return
        self.selected_prefix = prefix
        self._draw_selected_curves()
        self.set_frame(self.frame_index, trail_samples=0, show_orientation=True)

    def set_frame(self, index: int, trail_samples: int, show_orientation: bool) -> None:
        """Updates dynamic artists for one trajectory sample."""
        if self.trace is None or self.trace.row_count == 0:
            return
        self.frame_index = max(0, min(int(index), self.trace.row_count - 1))
        first = (
            0 if trail_samples <= 0 else max(0, self.frame_index - trail_samples + 1)
        )
        indices = slice(first, self.frame_index + 1)

        for obj in self.trace.objects:
            positions = self.trace.position(obj)
            if obj.prefix not in self.trail_lines:
                continue
            trail = positions[indices]
            valid = np.all(np.isfinite(trail), axis=1)
            trail = trail[valid]
            if trail.size:
                self.trail_lines[obj.prefix].set_data_3d(
                    trail[:, 0], trail[:, 1], trail[:, 2]
                )
            else:
                self.trail_lines[obj.prefix].set_data_3d([], [], [])

            current = positions[self.frame_index]
            marker = self.markers[obj.prefix]
            if np.all(np.isfinite(current)):
                marker._offsets3d = ([current[0]], [current[1]], [current[2]])
            else:
                marker._offsets3d = ([], [], [])

        steps = self.trace.step_values()
        if steps.size:
            value = float(steps[self.frame_index])
            if self.coordinate_cursor is not None:
                self.coordinate_cursor.set_xdata([value, value])
            if self.reward_cursor is not None:
                self.reward_cursor.set_xdata([value, value])

        self._remove_orientation()
        if show_orientation:
            self._draw_orientation()
        self.canvas.draw_idle()

    def _draw_selected_curves(self) -> None:
        self.coordinate_axes.clear()
        self.reward_axes.clear()
        self.return_axes.clear()
        self.coordinate_cursor = None
        self.reward_cursor = None
        if self.trace is None or not self.selected_prefix:
            self.canvas.draw_idle()
            return

        selected = next(
            (obj for obj in self.trace.objects if obj.prefix == self.selected_prefix),
            None,
        )
        if selected is None:
            return
        steps = self.trace.step_values()
        positions = self.trace.position(selected)
        for axis_index, axis_name in enumerate(("x", "y", "z")):
            self.coordinate_axes.plot(
                steps, positions[:, axis_index], label=axis_name, linewidth=1.1
            )
        self.coordinate_cursor = self.coordinate_axes.axvline(
            float(steps[0]) if steps.size else 0.0, linestyle="--", linewidth=0.9
        )
        self.coordinate_axes.grid(True)
        self.coordinate_axes.set_title(f"{selected.name} coordinates")
        self.coordinate_axes.set_xlabel("Episode step")
        self.coordinate_axes.set_ylabel("Position [m]")
        self.coordinate_axes.legend(loc="best")

        reward = self.trace.values("reward")
        episode_return = self.trace.values("episode_return")
        reward_line = None
        return_line = None
        if np.any(np.isfinite(reward)):
            (reward_line,) = self.reward_axes.plot(
                steps, reward, label="Reward", linewidth=1.0
            )
        if np.any(np.isfinite(episode_return)):
            (return_line,) = self.return_axes.plot(
                steps, episode_return, label="Cumulative return", linewidth=1.2
            )
        self.reward_cursor = self.reward_axes.axvline(
            float(steps[0]) if steps.size else 0.0, linestyle="--", linewidth=0.9
        )
        self.reward_axes.grid(True)
        self.reward_axes.set_title("Reward and cumulative return")
        self.reward_axes.set_xlabel("Episode step")
        self.reward_axes.set_ylabel("Reward")
        self.return_axes.yaxis.set_label_position("right")
        self.return_axes.yaxis.tick_right()
        self.return_axes.set_ylabel("Cumulative return")
        handles = [line for line in (reward_line, return_line) if line is not None]
        if handles:
            self.reward_axes.legend(
                handles, [line.get_label() for line in handles], loc="best"
            )
        self.canvas.draw_idle()

    def _draw_orientation(self) -> None:
        if self.trace is None:
            return
        selected = next(
            (obj for obj in self.trace.objects if obj.prefix == self.selected_prefix),
            None,
        )
        if selected is None:
            return
        quaternion = self.trace.quaternion(selected)
        if quaternion is None:
            return
        position = self.trace.position(selected)[self.frame_index]
        q = quaternion[self.frame_index]
        if not np.all(np.isfinite(position)) or not np.all(np.isfinite(q)):
            return
        rotation = _quat_wxyz_to_rotation(q)
        colors = ("tab:red", "tab:green", "tab:blue")
        for axis_index in range(3):
            vector = rotation[:, axis_index] * self.orientation_scale
            handle = self.path_axes.quiver(
                position[0],
                position[1],
                position[2],
                vector[0],
                vector[1],
                vector[2],
                color=colors[axis_index],
                linewidth=1.5,
                arrow_length_ratio=0.2,
            )
            self.orientation_handles.append(handle)

    def _remove_orientation(self) -> None:
        for handle in self.orientation_handles:
            try:
                handle.remove()
            except (ValueError, AttributeError):
                pass
        self.orientation_handles.clear()

    def _set_equal_limits(self, positions: np.ndarray) -> None:
        finite = positions[np.all(np.isfinite(positions), axis=1)]
        if finite.size == 0:
            return
        minimum = np.min(finite, axis=0)
        maximum = np.max(finite, axis=0)
        center = (minimum + maximum) / 2.0
        radius = max(float(np.max(maximum - minimum)) / 2.0, 0.01)
        self.path_axes.set_xlim(center[0] - radius, center[0] + radius)
        self.path_axes.set_ylim(center[1] - radius, center[1] + radius)
        self.path_axes.set_zlim(center[2] - radius, center[2] + radius)
        self.path_axes.set_box_aspect((1, 1, 1))

    @staticmethod
    def _trace_title(trace: TraceData) -> str:
        episode = trace.values("episode")
        env_id = trace.values("env_id")
        episode_text = (
            f"{int(episode[0])}" if episode.size and np.isfinite(episode[0]) else "-"
        )
        env_text = (
            f"{int(env_id[0])}" if env_id.size and np.isfinite(env_id[0]) else "-"
        )
        return f"{trace.path.name} | env {env_text} | episode {episode_text}"


class TrainingView(QWidget):
    """Episode-return and episode-length history view."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.figure = Figure(constrained_layout=True)
        self.return_axes = self.figure.add_subplot(2, 1, 1)
        self.length_axes = self.figure.add_subplot(2, 1, 2)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, 1)
        self.show_summary(None, None)

    def show_summary(self, summary: CsvTable | None, env_id: int | None) -> None:
        """Plots summary rows for the selected environment."""
        self.return_axes.clear()
        self.length_axes.clear()
        if summary is None or summary.row_count == 0:
            self.return_axes.set_title("No completed-episode summary available")
            self.length_axes.set_xlabel("Episode")
            self.canvas.draw_idle()
            return

        mask = np.ones(summary.row_count, dtype=bool)
        summary_env = summary.numeric("env_id")
        if env_id is not None and "env_id" in summary.headers:
            finite_env = np.isfinite(summary_env)
            mask = np.zeros(summary.row_count, dtype=bool)
            mask[finite_env] = summary_env[finite_env].astype(int) == env_id
        episode = summary.numeric("episode")[mask]
        episode_return = summary.numeric("episode_return")[mask]
        length = summary.numeric("episode_length")[mask]
        success = summary.numeric("success")[mask]
        if episode.size == 0:
            self.return_axes.set_title(
                f"No completed episodes for environment {env_id}"
            )
            self.canvas.draw_idle()
            return

        self.return_axes.plot(
            episode, episode_return, marker=".", label="Episode return"
        )
        self.return_axes.plot(
            episode,
            moving_mean(episode_return, min(20, episode.size)),
            linewidth=1.5,
            label="Moving mean",
        )
        success_mask = np.isfinite(success) & (success > 0.5)
        if np.any(success_mask):
            self.return_axes.scatter(
                episode[success_mask],
                episode_return[success_mask],
                marker="o",
                facecolors="none",
                label="Success",
            )
        self.return_axes.grid(True)
        self.return_axes.set_title("Training episode return")
        self.return_axes.set_ylabel("Return")
        self.return_axes.legend(loc="best")

        self.length_axes.plot(episode, length, marker=".", label="Episode length")
        self.length_axes.grid(True)
        self.length_axes.set_title("Episode length")
        self.length_axes.set_xlabel("Episode")
        self.length_axes.set_ylabel("Steps")
        self.length_axes.legend(loc="best")
        self.canvas.draw_idle()


class MonitorWindow(QMainWindow):
    """Combined offline player and online Coder/SSH monitor."""

    def __init__(self, initial_source: str = "", refresh_period: float = 2.0) -> None:
        super().__init__()
        self.setWindowTitle("IsaacLab Trace Monitor")
        self.resize(1500, 900)

        self.settings = QSettings("IsaacLabTraceMonitor", "TraceMonitor")
        self.source_spec: SourceSpec | None = None
        self.source_root: Path | None = None
        self.explicit_csv: Path | None = None
        self.remote_cache: Path | None = None
        self.metadata: dict[str, Any] = {}
        self.status: dict[str, Any] = {}
        self.summary: CsvTable | None = None
        self.trace_files: tuple[TraceFile, ...] = tuple()
        self.trace: TraceData | None = None
        self.trace_signature: tuple[int, int, int] | None = None
        self.summary_signature: tuple[int, int, int] | None = None
        self.status_signature: tuple[int, int, int] | None = None
        self.frame_index = 0
        self.playing = False
        self.play_start_clock = 0.0
        self.play_start_trace_time = 0.0
        self.last_sync_message = ""
        self.sync_pending = False
        self.sync_output = ""

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_source)
        self.play_timer = QTimer(self)
        self.play_timer.setInterval(20)
        self.play_timer.timeout.connect(self._playback_tick)
        self.sync_process = QProcess(self)
        self.sync_process.readyReadStandardError.connect(self._read_sync_stderr)
        self.sync_process.readyReadStandardOutput.connect(self._read_sync_stdout)
        self.sync_process.finished.connect(self._sync_finished)

        self._create_ui(refresh_period)
        self._create_actions()
        self._restore_settings()
        if initial_source:
            self.source_combo.setCurrentText(initial_source)
            QTimer.singleShot(0, self.open_source)

    def _create_ui(self, refresh_period: float) -> None:
        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 8)

        source_row = QHBoxLayout()
        source_label = QLabel("Source")
        self.source_combo = QComboBox()
        self.source_combo.setEditable(True)
        self.source_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.source_combo.lineEdit().setPlaceholderText(
            "/path/to/object_traces or coder.workspace:/absolute/path/to/object_traces"
        )
        self.source_combo.lineEdit().returnPressed.connect(self.open_source)
        self.browse_button = QPushButton("Browse…")
        self.browse_button.clicked.connect(self.browse_source)
        self.open_button = QPushButton("Open / Connect")
        self.open_button.setDefault(True)
        self.open_button.clicked.connect(self.open_source)
        source_row.addWidget(source_label)
        source_row.addWidget(self.source_combo, 1)
        source_row.addWidget(self.browse_button)
        source_row.addWidget(self.open_button)
        outer.addLayout(source_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.left_panel = QWidget()
        self.left_panel.setMinimumWidth(300)
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        selection_group = QGroupBox("Selection")
        selection_form = QFormLayout(selection_group)
        self.mode_label = QLabel("No source")
        self.environment_combo = QComboBox()
        self.environment_combo.currentIndexChanged.connect(self._environment_changed)
        self.trace_combo = QComboBox()
        self.trace_combo.currentIndexChanged.connect(self._trace_selection_changed)
        self.object_combo = QComboBox()
        self.object_combo.currentIndexChanged.connect(self._object_changed)
        selection_form.addRow("Mode", self.mode_label)
        selection_form.addRow("Environment", self.environment_combo)
        selection_form.addRow("Trace", self.trace_combo)
        selection_form.addRow("Object", self.object_combo)
        left_layout.addWidget(selection_group)

        live_group = QGroupBox("Live monitoring")
        live_form = QFormLayout(live_group)
        self.live_checkbox = QCheckBox("Refresh automatically")
        self.live_checkbox.toggled.connect(self._live_toggled)
        self.follow_checkbox = QCheckBox("Follow newest sample")
        self.follow_checkbox.setChecked(True)
        self.follow_checkbox.toggled.connect(self._follow_toggled)
        self.sync_episodes_checkbox = QCheckBox("Sync retained episodes")
        self.sync_episodes_checkbox.toggled.connect(self._sync_episodes_changed)
        self.refresh_spin = QDoubleSpinBox()
        self.refresh_spin.setRange(0.5, 60.0)
        self.refresh_spin.setDecimals(1)
        self.refresh_spin.setSuffix(" s")
        self.refresh_spin.setValue(max(0.5, refresh_period))
        self.refresh_spin.valueChanged.connect(self._refresh_period_changed)
        self.refresh_button = QPushButton("Refresh now")
        self.refresh_button.clicked.connect(lambda: self.refresh_source(force=True))
        live_form.addRow(self.live_checkbox)
        live_form.addRow(self.follow_checkbox)
        live_form.addRow(self.sync_episodes_checkbox)
        live_form.addRow("Period", self.refresh_spin)
        live_form.addRow(self.refresh_button)
        left_layout.addWidget(live_group)

        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout(status_group)
        self.status_area = QPlainTextEdit()
        self.status_area.setReadOnly(True)
        self.status_area.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.status_area.setFont(
            QFont("Menlo" if sys.platform == "darwin" else "Monospace")
        )
        self.status_area.setPlainText(
            "Open a local trace folder or enter a Coder SSH source."
        )
        status_layout.addWidget(self.status_area)
        left_layout.addWidget(status_group, 1)

        self.tabs = QTabWidget()
        trajectory_page = QWidget()
        trajectory_layout = QVBoxLayout(trajectory_page)
        trajectory_layout.setContentsMargins(0, 0, 0, 0)
        self.trajectory_view = TrajectoryView()
        trajectory_layout.addWidget(self.trajectory_view, 1)
        trajectory_layout.addLayout(self._create_playback_controls())
        self.training_view = TrainingView()
        self.tabs.addTab(trajectory_page, "Trajectory")
        self.tabs.addTab(self.training_view, "Training")

        splitter.addWidget(self.left_panel)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes((330, 1170))
        self.splitter = splitter
        outer.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Ready")

    def _create_playback_controls(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        style = self.style()

        self.first_button = QToolButton()
        self.first_button.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaSkipBackward)
        )
        self.first_button.setToolTip("First sample")
        self.first_button.clicked.connect(
            lambda: self._jump_to_frame(0, user_action=True)
        )
        self.previous_button = QToolButton()
        self.previous_button.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaSeekBackward)
        )
        self.previous_button.setToolTip("Previous sample")
        self.previous_button.clicked.connect(lambda: self._step_frame(-1))
        self.play_button = QToolButton()
        self.play_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.play_button.setToolTip("Play / pause")
        self.play_button.clicked.connect(self.toggle_playback)
        self.next_button = QToolButton()
        self.next_button.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaSeekForward)
        )
        self.next_button.setToolTip("Next sample")
        self.next_button.clicked.connect(lambda: self._step_frame(1))
        self.last_button = QToolButton()
        self.last_button.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaSkipForward)
        )
        self.last_button.setToolTip("Last sample")
        self.last_button.clicked.connect(self._jump_to_last)

        self.sample_slider = QSlider(Qt.Orientation.Horizontal)
        self.sample_slider.setRange(0, 0)
        self.sample_slider.valueChanged.connect(self._slider_changed)
        self.frame_label = QLabel("No trace loaded")
        self.frame_label.setMinimumWidth(250)

        self.speed_combo = QComboBox()
        for speed in (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0):
            self.speed_combo.addItem(f"{speed:g}×", speed)
        self.speed_combo.setCurrentIndex(3)
        self.speed_combo.currentIndexChanged.connect(self._playback_speed_changed)

        self.trail_spin = QSpinBox()
        self.trail_spin.setRange(0, 1_000_000)
        self.trail_spin.setSpecialValueText("Full")
        self.trail_spin.setValue(250)
        self.trail_spin.setToolTip(
            "Number of samples in the animated trail; 0 shows the full trail"
        )
        self.trail_spin.valueChanged.connect(lambda _value: self._render_frame())
        self.orientation_checkbox = QCheckBox("Orientation")
        self.orientation_checkbox.setChecked(True)
        self.orientation_checkbox.toggled.connect(lambda _checked: self._render_frame())
        self.loop_checkbox = QCheckBox("Loop")

        for button in (
            self.first_button,
            self.previous_button,
            self.play_button,
            self.next_button,
            self.last_button,
        ):
            layout.addWidget(button)
        layout.addWidget(self.sample_slider, 1)
        layout.addWidget(self.frame_label)
        layout.addWidget(QLabel("Speed"))
        layout.addWidget(self.speed_combo)
        layout.addWidget(QLabel("Trail"))
        layout.addWidget(self.trail_spin)
        layout.addWidget(self.orientation_checkbox)
        layout.addWidget(self.loop_checkbox)
        return layout

    def _create_actions(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        view_menu = self.menuBar().addMenu("&View")
        playback_menu = self.menuBar().addMenu("&Playback")
        help_menu = self.menuBar().addMenu("&Help")

        open_action = QAction("Open source…", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.browse_source)
        file_menu.addAction(open_action)
        self.addAction(open_action)

        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        refresh_action = QAction("Refresh", self)
        refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)
        refresh_action.triggered.connect(lambda: self.refresh_source(force=True))
        view_menu.addAction(refresh_action)
        self.addAction(refresh_action)

        play_action = QAction("Play / pause", self)
        play_action.setShortcut(Qt.Key.Key_Space)
        play_action.triggered.connect(self.toggle_playback)
        playback_menu.addAction(play_action)
        self.addAction(play_action)

        about_action = QAction("About IsaacLab Trace Monitor", self)
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _show_about(self) -> None:
        """Show project, license, and AI-assistance information."""
        QMessageBox.about(
            self,
            "About IsaacLab Trace Monitor",
            f"""
            <h3>IsaacLab Trace Monitor {__version__}</h3>
            <p>Live monitoring and offline playback of Isaac Lab object traces.</p>
            <p><b>Independent community project:</b> this application is not
            affiliated with or endorsed by NVIDIA or the Isaac Lab project.</p>
            <p><b>Development disclosure:</b> the initial implementation and
            documentation were created with substantial assistance from
            OpenAI's ChatGPT, based on requirements and testing supplied by the
            maintainer.</p>
            <p>The application does not connect to OpenAI and does not transmit
            trace data, paths, or SSH information to OpenAI.</p>
            <p>License: BSD-3-Clause</p>
            """,
        )

    def _restore_settings(self) -> None:
        recent_sources = self.settings.value("recentSources", [], type=list)
        for source in recent_sources:
            self.source_combo.addItem(str(source))
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        splitter_state = self.settings.value("splitter")
        if splitter_state is not None:
            self.splitter.restoreState(splitter_state)
        stored_period = self.settings.value("refreshPeriod")
        if stored_period is not None:
            try:
                self.refresh_spin.setValue(float(stored_period))
            except (TypeError, ValueError):
                pass

    def browse_source(self) -> None:
        """Opens a local directory chooser and loads the selected source."""
        start = self.source_combo.currentText().strip()
        if not start or ":/" in start:
            start = str(Path.home())
        selected = QFileDialog.getExistingDirectory(
            self, "Select object_traces folder", start
        )
        if selected:
            self.source_combo.setCurrentText(selected)
            self.open_source()

    def open_source(self) -> None:
        """Opens a local source or starts an initial remote synchronization."""
        value = self.source_combo.currentText().strip()
        try:
            source = SourceSpec.parse(value)
        except ValueError as error:
            QMessageBox.warning(self, "Invalid source", str(error))
            return

        self.stop_playback()
        self.source_spec = source
        self.source_root = None
        self.explicit_csv = None
        self.metadata = {}
        self.status = {}
        self.summary = None
        self.trace = None
        self.trace_signature = None
        self.summary_signature = None
        self.status_signature = None
        self._remember_source(value)

        if source.remote:
            self.remote_cache = cache_directory(source)
            self.remote_cache.mkdir(parents=True, exist_ok=True)
            self.mode_label.setText("Remote live (SSH/rsync)")
            self.sync_episodes_checkbox.setEnabled(True)
            self.live_checkbox.setChecked(True)
            self.statusBar().showMessage(f"Connecting to {source.remote_host}…")
            self._try_open_cached_root()
            self._start_remote_sync(force=True)
            return

        self.remote_cache = None
        self.sync_episodes_checkbox.setEnabled(False)
        try:
            assert source.local_path is not None
            root, selected_csv = find_trace_root(source.local_path)
        except (FileNotFoundError, ValueError, OSError) as error:
            QMessageBox.critical(self, "Unable to open source", str(error))
            self.mode_label.setText("No source")
            return
        self.source_root = root
        self.explicit_csv = selected_csv
        self.mode_label.setText("Local / offline")
        self._reload_from_disk(force=True, prefer_current=False)
        running = bool(self.status.get("running", False))
        self.live_checkbox.setChecked(running)

    def refresh_source(self, force: bool = False) -> None:
        """Refreshes local files or synchronizes a remote source."""
        if self.source_spec is None:
            return
        if self.source_spec.remote:
            self._start_remote_sync(force=force)
        else:
            self._reload_from_disk(force=force)

    def _try_open_cached_root(self) -> None:
        if self.remote_cache is None:
            return
        try:
            root, _ = find_trace_root(self.remote_cache)
        except (FileNotFoundError, ValueError):
            return
        self.source_root = root
        self._reload_from_disk(force=True)
        self.last_sync_message = "Showing cached data while synchronizing."
        self._update_status_text()

    def _start_remote_sync(self, force: bool = False) -> None:
        del force
        if (
            self.source_spec is None
            or not self.source_spec.remote
            or self.remote_cache is None
        ):
            return
        if self.sync_process.state() != QProcess.ProcessState.NotRunning:
            self.sync_pending = True
            return
        process_path = _augmented_process_path()
        rsync = shutil.which("rsync", path=process_path)
        if not rsync:
            self._show_sync_error(
                "rsync was not found. Install rsync and configure SSH/Coder access first."
            )
            return
        self.sync_output = ""
        self.sync_pending = False
        arguments = rsync_arguments(
            self.source_spec,
            self.remote_cache,
            include_episodes=self.sync_episodes_checkbox.isChecked(),
        )
        self.statusBar().showMessage(f"Synchronizing {self.source_spec.remote_host}…")
        self.refresh_button.setEnabled(False)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PATH", process_path)
        self.sync_process.setProcessEnvironment(environment)
        self.sync_process.start(rsync, arguments)

    def _read_sync_stderr(self) -> None:
        self.sync_output += bytes(self.sync_process.readAllStandardError()).decode(
            "utf-8", errors="replace"
        )

    def _read_sync_stdout(self) -> None:
        self.sync_output += bytes(self.sync_process.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )

    def _sync_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self.refresh_button.setEnabled(True)
        if exit_status != QProcess.ExitStatus.NormalExit or exit_code != 0:
            detail = self.sync_output.strip() or f"rsync exited with code {exit_code}"
            self._show_sync_error(detail)
        else:
            assert self.remote_cache is not None
            try:
                root, _ = find_trace_root(self.remote_cache)
            except (FileNotFoundError, ValueError) as error:
                self._show_sync_error(
                    f"The remote folder did not contain an object_traces log: {error}"
                )
            else:
                self.source_root = root
                self.last_sync_message = f"Last sync: {time.strftime('%H:%M:%S')}"
                self._reload_from_disk(force=False, prefer_current=True)
                self.statusBar().showMessage(self.last_sync_message, 5000)
        if self.sync_pending:
            self.sync_pending = False
            QTimer.singleShot(0, self._start_remote_sync)

    def _show_sync_error(self, detail: str) -> None:
        compact_detail = " ".join(detail.split())
        if len(compact_detail) > 1200:
            compact_detail = "…" + compact_detail[-1199:]
        self.last_sync_message = f"Sync error: {compact_detail}"
        self.statusBar().showMessage("Remote synchronization failed")
        self._update_status_text()

    def _reload_from_disk(
        self, force: bool = False, prefer_current: bool = False
    ) -> None:
        if self.source_root is None:
            return
        root = self.source_root
        try:
            metadata = load_json(root / "metadata.json")
            status_path = root / "live" / "status.json"
            status_signature = file_signature(status_path)
            if force or status_signature != self.status_signature:
                self.status = load_json(status_path)
                self.status_signature = status_signature
            self.metadata = metadata

            self._update_environment_choices()
            self._update_trace_choices(prefer_current=prefer_current)
            self._load_selected_trace(force=force)

            summary_path = root / "episode_summary.csv"
            summary_signature = file_signature(summary_path)
            if force or summary_signature != self.summary_signature:
                self.summary = load_summary(root)
                self.summary_signature = summary_signature
            self.training_view.show_summary(self.summary, self._current_env_id())
            self._update_status_text()
        except (OSError, ValueError, csv.Error) as error:
            self.statusBar().showMessage(f"Refresh failed: {error}")
            self.last_sync_message = f"Read error: {error}"
            self._update_status_text()

    def _update_environment_choices(self) -> None:
        if self.source_root is None:
            return
        current = self._current_env_id()
        env_ids = discover_env_ids(self.source_root, self.metadata, self.status)
        if self.explicit_csv is not None and not env_ids:
            env_ids = (0,)
        with QSignalBlocker(self.environment_combo):
            self.environment_combo.clear()
            for env_id in env_ids:
                self.environment_combo.addItem(str(env_id), env_id)
            if current in env_ids:
                self.environment_combo.setCurrentIndex(env_ids.index(current))
            elif env_ids:
                self.environment_combo.setCurrentIndex(0)

    def _update_trace_choices(self, prefer_current: bool = False) -> None:
        if self.source_root is None:
            return
        previous_path = self._current_trace_path()
        previous_kind = self._current_trace_kind()
        files = discover_trace_files(
            self.source_root, self._current_env_id(), selected_csv=self.explicit_csv
        )
        self.trace_files = files
        target_index = -1
        with QSignalBlocker(self.trace_combo):
            self.trace_combo.clear()
            for index, trace_file in enumerate(files):
                self.trace_combo.addItem(trace_file.label)
                if previous_path is not None and trace_file.path == previous_path:
                    target_index = index
            if target_index < 0 and previous_kind:
                target_index = next(
                    (
                        index
                        for index, item in enumerate(files)
                        if item.kind == previous_kind
                    ),
                    -1,
                )
            if prefer_current and previous_path is None:
                target_index = next(
                    (
                        index
                        for index, item in enumerate(files)
                        if item.kind == "current"
                    ),
                    target_index,
                )
            if target_index < 0 and files:
                target_index = 0
            if target_index >= 0:
                self.trace_combo.setCurrentIndex(target_index)

    def _load_selected_trace(self, force: bool = False) -> None:
        trace_file = self._current_trace_file()
        if trace_file is None or self.source_root is None:
            return
        signature = file_signature(trace_file.path)
        if signature is None:
            return
        if (
            not force
            and signature == self.trace_signature
            and self.trace is not None
            and self.trace.path == trace_file.path.resolve()
        ):
            return

        old_step = None
        selected_prefix = self.object_combo.currentData()
        if self.trace is not None and self.trace.row_count:
            old_steps = self.trace.step_values()
            old_step = float(old_steps[min(self.frame_index, old_steps.size - 1)])

        trace = load_trace(trace_file.path, self.source_root)
        self.trace = trace
        self.trace_signature = signature
        self._update_object_choices(trace, str(selected_prefix or ""))
        selected_prefix = str(self.object_combo.currentData() or "")
        self.trajectory_view.load_trace(trace, selected_prefix)
        self.sample_slider.setRange(0, max(trace.row_count - 1, 0))

        if trace.row_count == 0:
            self.frame_index = 0
        elif self.follow_checkbox.isChecked():
            self.frame_index = trace.row_count - 1
        elif old_step is not None:
            steps = trace.step_values()
            self.frame_index = (
                int(np.argmin(np.abs(steps - old_step))) if steps.size else 0
            )
        else:
            self.frame_index = 0
        self._jump_to_frame(self.frame_index, user_action=False)

    def _update_object_choices(self, trace: TraceData, previous_prefix: str) -> None:
        prefixes = [obj.prefix for obj in trace.objects]
        with QSignalBlocker(self.object_combo):
            self.object_combo.clear()
            for obj in trace.objects:
                self.object_combo.addItem(obj.name, obj.prefix)
            if previous_prefix in prefixes:
                self.object_combo.setCurrentIndex(prefixes.index(previous_prefix))
            elif prefixes:
                preferred = next(
                    (
                        index
                        for index, obj in enumerate(trace.objects)
                        if "ee" in obj.name.lower() or "tool" in obj.name.lower()
                    ),
                    0,
                )
                self.object_combo.setCurrentIndex(preferred)

    def _environment_changed(self, _index: int = -1) -> None:
        if self.source_root is None:
            return
        self.stop_playback()
        self.trace = None
        self.trace_signature = None
        self._update_trace_choices(prefer_current=True)
        self._load_selected_trace(force=True)
        self.training_view.show_summary(self.summary, self._current_env_id())
        self._update_status_text()

    def _trace_selection_changed(self, _index: int = -1) -> None:
        if self.source_root is None:
            return
        self.stop_playback()
        self.trace_signature = None
        self._load_selected_trace(force=True)
        self._update_status_text()

    def _object_changed(self, _index: int = -1) -> None:
        prefix = self.object_combo.currentData()
        if prefix:
            self.trajectory_view.set_selected_object(str(prefix))
            self._render_frame()

    def _current_env_id(self) -> int | None:
        value = self.environment_combo.currentData()
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _current_trace_file(self) -> TraceFile | None:
        index = self.trace_combo.currentIndex()
        if 0 <= index < len(self.trace_files):
            return self.trace_files[index]
        return None

    def _current_trace_path(self) -> Path | None:
        trace_file = self._current_trace_file()
        return trace_file.path if trace_file else None

    def _current_trace_kind(self) -> str:
        trace_file = self._current_trace_file()
        return trace_file.kind if trace_file else ""

    def _live_toggled(self, enabled: bool) -> None:
        if enabled and self.source_spec is not None:
            self.refresh_timer.start(int(self.refresh_spin.value() * 1000))
        else:
            self.refresh_timer.stop()

    def _refresh_period_changed(self, value: float) -> None:
        self.settings.setValue("refreshPeriod", value)
        if self.refresh_timer.isActive():
            self.refresh_timer.start(int(value * 1000))

    def _sync_episodes_changed(self, enabled: bool = False) -> None:
        if self.source_spec is None or not self.source_spec.remote:
            return
        if not enabled and self.remote_cache is not None:
            shutil.rmtree(self.remote_cache / "episodes", ignore_errors=True)
            if self.source_root is not None:
                self._update_trace_choices(prefer_current=True)
        self.refresh_source(force=True)

    def _follow_toggled(self, enabled: bool) -> None:
        if enabled:
            self._jump_to_last()

    def toggle_playback(self) -> None:
        """Starts or pauses simulation-time playback."""
        if self.trace is None or self.trace.row_count < 2:
            return
        if self.playing:
            self.stop_playback()
            return
        if self.frame_index >= self.trace.row_count - 1:
            self._jump_to_frame(0, user_action=False)
        times = self.trace.sample_times()
        self.playing = True
        self.play_start_clock = time.monotonic()
        self.play_start_trace_time = float(times[self.frame_index])
        self.play_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause)
        )
        self.play_timer.start()

    def stop_playback(self) -> None:
        self.playing = False
        self.play_timer.stop()
        if hasattr(self, "play_button"):
            self.play_button.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
            )

    def _playback_tick(self) -> None:
        if not self.playing or self.trace is None or self.trace.row_count < 2:
            self.stop_playback()
            return
        times = self.trace.sample_times()
        speed = float(self.speed_combo.currentData() or 1.0)
        target = (
            self.play_start_trace_time
            + (time.monotonic() - self.play_start_clock) * speed
        )
        index = int(np.searchsorted(times, target, side="right") - 1)
        index = max(0, min(index, self.trace.row_count - 1))
        self._jump_to_frame(index, user_action=False)
        if index >= self.trace.row_count - 1:
            if self.loop_checkbox.isChecked():
                self._jump_to_frame(0, user_action=False)
                self.play_start_clock = time.monotonic()
                self.play_start_trace_time = float(times[0])
            else:
                self.stop_playback()

    def _playback_speed_changed(self) -> None:
        if not self.playing or self.trace is None:
            return
        times = self.trace.sample_times()
        self.play_start_clock = time.monotonic()
        self.play_start_trace_time = float(times[self.frame_index])

    def _step_frame(self, delta: int) -> None:
        self.stop_playback()
        self._jump_to_frame(self.frame_index + delta, user_action=True)

    def _jump_to_last(self) -> None:
        if self.trace is not None and self.trace.row_count:
            self._jump_to_frame(self.trace.row_count - 1, user_action=False)

    def _slider_changed(self, value: int) -> None:
        if self.trace is None or value == self.frame_index:
            return
        self.stop_playback()
        self._jump_to_frame(value, user_action=True, update_slider=False)

    def _jump_to_frame(
        self, index: int, user_action: bool, update_slider: bool = True
    ) -> None:
        if self.trace is None or self.trace.row_count == 0:
            return
        self.frame_index = max(0, min(int(index), self.trace.row_count - 1))
        if user_action and self._current_trace_kind() == "current":
            with QSignalBlocker(self.follow_checkbox):
                self.follow_checkbox.setChecked(False)
        if update_slider:
            with QSignalBlocker(self.sample_slider):
                self.sample_slider.setValue(self.frame_index)
        self._render_frame()
        self._update_frame_label()

    def _render_frame(self) -> None:
        if self.trace is None:
            return
        self.trajectory_view.set_frame(
            self.frame_index,
            trail_samples=self.trail_spin.value(),
            show_orientation=self.orientation_checkbox.isChecked(),
        )

    def _update_frame_label(self) -> None:
        if self.trace is None or self.trace.row_count == 0:
            self.frame_label.setText("No trace loaded")
            return
        steps = self.trace.step_values()
        times = self.trace.sample_times()
        step = steps[self.frame_index] if steps.size else self.frame_index
        sample_time = times[self.frame_index] if times.size else math.nan
        self.frame_label.setText(
            f"Sample {self.frame_index + 1}/{self.trace.row_count} | "
            f"step {step:.0f} | t {sample_time:.3f} s"
        )

    def _update_status_text(self) -> None:
        lines: list[str] = []
        if self.source_spec is not None:
            lines.append(f"Source: {self.source_spec.raw}")
            lines.append(f"Mode:   {'remote' if self.source_spec.remote else 'local'}")
        if self.source_root is not None:
            lines.append(f"Root:   {self.source_root}")
        if self.remote_cache is not None:
            lines.append(f"Cache:  {self.remote_cache}")
        if self.last_sync_message:
            lines.append(self.last_sync_message)

        if self.status:
            lines.append("")
            lines.append(f"Running:       {self.status.get('running', '-')}")
            lines.append(f"Updated UTC:   {self.status.get('updated_utc', '-')}")
            lines.append(
                f"Global step:   {_format_number(self.status.get('global_step'))}"
            )
            lines.append(f"Rollout:       {_format_number(self.status.get('rollout'))}")
            progress = self.status.get("progress_percent")
            lines.append(
                f"Progress:      {float(progress):.2f}%"
                if isinstance(progress, (int, float))
                else "Progress:      -"
            )
            env_id = self._current_env_id()
            environments = self.status.get("environments", {})
            env_status = (
                environments.get(str(env_id), {})
                if isinstance(environments, dict)
                else {}
            )
            if isinstance(env_status, dict):
                lines.append(f"Environment:   {env_id}")
                lines.append(
                    f"Episode:       {_format_number(env_status.get('episode'))}"
                )
                lines.append(
                    f"Episode return:{_format_float(env_status.get('episode_return'), width=12)}"
                )
                lines.append(
                    f"Current samples: {_format_number(env_status.get('current_samples'))}"
                )
                lines.append(
                    f"Adaptive stride: {_format_number(env_status.get('adaptive_stride'))}"
                )

        if self.trace is not None:
            lines.append("")
            lines.append(f"Trace:   {self.trace.path.name}")
            lines.append(f"Samples: {self.trace.row_count}")
            coordinate_frame = self.metadata.get("coordinate_frame", "-")
            lines.append(f"Frame:   {coordinate_frame}")
            lines.append(
                f"Quaternion: {self.metadata.get('quaternion_order', '-') or 'not logged'}"
            )
        self.status_area.setPlainText(
            "\n".join(lines) if lines else "No source loaded."
        )

    def _remember_source(self, source: str) -> None:
        current = [
            self.source_combo.itemText(i) for i in range(self.source_combo.count())
        ]
        recent = [source] + [item for item in current if item != source]
        recent = recent[:10]
        with QSignalBlocker(self.source_combo):
            self.source_combo.clear()
            self.source_combo.addItems(recent)
            self.source_combo.setCurrentText(source)
        self.settings.setValue("recentSources", recent)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.stop_playback()
        self.refresh_timer.stop()
        if self.sync_process.state() != QProcess.ProcessState.NotRunning:
            self.sync_process.kill()
            self.sync_process.waitForFinished(1000)
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitter", self.splitter.saveState())
        self.settings.setValue("refreshPeriod", self.refresh_spin.value())
        event.accept()


def _augmented_process_path() -> str:
    """Return PATH with common desktop CLI locations for SSH proxy tools."""
    candidates = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/opt/local/bin",
        "/usr/bin",
        "/bin",
        str(Path.home() / ".local" / "bin"),
        str(Path.home() / "bin"),
    ]
    existing = os.environ.get("PATH", "")
    entries = candidates + [entry for entry in existing.split(os.pathsep) if entry]
    return os.pathsep.join(dict.fromkeys(entries))


def _quat_wxyz_to_rotation(quaternion: np.ndarray) -> np.ndarray:
    q = np.asarray(quaternion, dtype=float)
    norm = float(np.linalg.norm(q))
    if not math.isfinite(norm) or norm <= np.finfo(float).eps:
        return np.eye(3)
    w, x, y, z = q / norm
    return np.asarray(
        (
            (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
        ),
        dtype=float,
    )


def _format_number(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "-"


def _format_float(value: Any, width: int = 0) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        text = "-"
    else:
        text = f"{number:.6g}"
    return f"{text:>{width}}" if width else text


def _application_icon_path() -> Path | None:
    """Returns the bundled application icon when it is available."""
    path = Path(__file__).resolve().parent / "assets" / "app_icon.png"
    return path if path.is_file() else None


def run_application(
    source: str = "",
    refresh_period: float = 2.0,
    smoke_test: bool = False,
) -> int:
    """Create and run the Qt desktop application."""
    application = QApplication(sys.argv[:1])
    application.setApplicationName("IsaacLab Trace Monitor")
    application.setApplicationDisplayName("IsaacLab Trace Monitor")
    application.setApplicationVersion(__version__)
    application.setOrganizationName("IsaacLabTraceMonitor")
    if hasattr(application, "setDesktopFileName"):
        application.setDesktopFileName("isaaclab-trace-monitor")

    icon_path = _application_icon_path()
    icon = QIcon(str(icon_path)) if icon_path is not None else QIcon()
    if not icon.isNull():
        application.setWindowIcon(icon)

    window = MonitorWindow(source, refresh_period)
    if not icon.isNull():
        window.setWindowIcon(icon)
    window.show()

    if smoke_test:
        QTimer.singleShot(750, application.quit)

    return application.exec()


def main(argv: list[str] | None = None) -> int:
    """Compatibility wrapper for callers that imported ``app.main``."""
    from isaaclab_trace_monitor.cli import main as cli_main

    return cli_main(argv)


__all__ = ["MonitorWindow", "run_application", "main"]
