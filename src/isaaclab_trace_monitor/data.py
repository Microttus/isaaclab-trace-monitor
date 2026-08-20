"""Data loading and trace discovery for Isaac Lab trajectory logs."""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


@dataclass(frozen=True)
class ObjectDefinition:
    """One traced scene object and its CSV column prefix."""

    name: str
    prefix: str


@dataclass(frozen=True)
class TraceFile:
    """A selectable trace CSV beneath an object_traces directory."""

    label: str
    path: Path
    kind: str
    env_id: int | None
    episode: int | None


@dataclass
class CsvTable:
    """Small CSV table with numeric columns converted to NumPy arrays."""

    path: Path
    headers: tuple[str, ...]
    columns: dict[str, np.ndarray | tuple[str, ...]]
    row_count: int

    def numeric(self, name: str, default: float = math.nan) -> np.ndarray:
        """Returns a numeric column or a default-filled array."""
        values = self.columns.get(name)
        if isinstance(values, np.ndarray):
            return values
        return np.full(self.row_count, default, dtype=float)

    def text(self, name: str) -> tuple[str, ...]:
        """Returns a text column or an empty-string column."""
        values = self.columns.get(name)
        if isinstance(values, tuple):
            return values
        return tuple("" for _ in range(self.row_count))


@dataclass
class TraceData:
    """Parsed trajectory data and associated metadata."""

    table: CsvTable
    metadata: dict[str, Any]
    objects: tuple[ObjectDefinition, ...]

    @property
    def path(self) -> Path:
        return self.table.path

    @property
    def row_count(self) -> int:
        return self.table.row_count

    def values(self, name: str, default: float = math.nan) -> np.ndarray:
        return self.table.numeric(name, default)

    def step_values(self) -> np.ndarray:
        """Returns the most useful horizontal-axis values in the trace."""
        for name in ("episode_step", "sample_index", "callback_call", "global_step"):
            values = self.table.columns.get(name)
            if isinstance(values, np.ndarray):
                return values
        return np.arange(self.row_count, dtype=float)

    def sample_times(self) -> np.ndarray:
        """Returns simulated time when available, otherwise relative wall time."""
        step_dt = self.metadata.get("simulation_step_dt_s")
        try:
            step_dt_value = float(step_dt)
        except (TypeError, ValueError):
            step_dt_value = math.nan

        if math.isfinite(step_dt_value) and step_dt_value > 0:
            steps = self.step_values()
            if steps.size:
                return (steps - steps[0]) * step_dt_value

        wall_time = self.table.columns.get("wall_time_s")
        if isinstance(wall_time, np.ndarray) and wall_time.size:
            return wall_time - wall_time[0]

        return np.arange(self.row_count, dtype=float)

    def position(self, obj: ObjectDefinition) -> np.ndarray:
        """Returns an N-by-3 position array for an object."""
        return np.column_stack(
            (
                self.values(f"{obj.prefix}_x"),
                self.values(f"{obj.prefix}_y"),
                self.values(f"{obj.prefix}_z"),
            )
        )

    def quaternion(self, obj: ObjectDefinition) -> np.ndarray | None:
        """Returns an N-by-4 WXYZ quaternion array when logged."""
        names = tuple(f"{obj.prefix}_{axis}" for axis in ("qw", "qx", "qy", "qz"))
        if not all(name in self.table.headers for name in names):
            return None
        return np.column_stack(tuple(self.values(name) for name in names))


_EPISODE_RE = re.compile(r"episode_(\d+)\.csv$")
_ENV_RE = re.compile(r"env_(\d+)")


def load_csv(path: Path) -> CsvTable:
    """Loads a bounded Isaac Lab CSV without requiring pandas."""
    path = path.expanduser().resolve()
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {path}")
        headers = tuple(reader.fieldnames)
        raw_columns: dict[str, list[str]] = {name: [] for name in headers}
        for row in reader:
            for name in headers:
                raw_columns[name].append((row.get(name) or "").strip())

    columns: dict[str, np.ndarray | tuple[str, ...]] = {}
    for name, raw_values in raw_columns.items():
        numeric_values: list[float] = []
        numeric = True
        for value in raw_values:
            if not value:
                numeric_values.append(math.nan)
                continue
            try:
                numeric_values.append(float(value))
            except ValueError:
                numeric = False
                break
        if numeric:
            columns[name] = np.asarray(numeric_values, dtype=float)
        else:
            columns[name] = tuple(raw_values)

    row_count = len(next(iter(raw_columns.values()), []))
    return CsvTable(path=path, headers=headers, columns=columns, row_count=row_count)


def load_json(path: Path) -> dict[str, Any]:
    """Loads a JSON object, returning an empty object when the file is absent."""
    try:
        with path.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except FileNotFoundError:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def find_trace_root(source: Path) -> tuple[Path, Path | None]:
    """Finds object_traces root and an optional explicitly selected CSV.

    The source may be the object_traces directory, its parent run directory,
    a live/episodes subdirectory, or a specific trace CSV.
    """
    source = source.expanduser()
    if not source.exists():
        raise FileNotFoundError(f"Source does not exist: {source}")

    source = source.resolve()
    selected_csv = (
        source if source.is_file() and source.suffix.lower() == ".csv" else None
    )
    start = source.parent if source.is_file() else source

    direct_child = start / "object_traces"
    if _looks_like_trace_root(direct_child):
        return direct_child, selected_csv

    current = start
    for _ in range(8):
        if _looks_like_trace_root(current):
            return current, selected_csv
        if current.parent == current:
            break
        current = current.parent

    if start.is_dir() and any(start.glob("*.csv")):
        return start, selected_csv

    raise ValueError(
        "Could not find an object_traces directory. Select the folder containing "
        "metadata.json/live/episodes, its run directory, or a trace CSV."
    )


def load_trace(path: Path, root: Path | None = None) -> TraceData:
    """Loads one trace CSV and discovers its object definitions."""
    table = load_csv(path)
    trace_root = root
    if trace_root is None:
        try:
            trace_root, _ = find_trace_root(path)
        except (FileNotFoundError, ValueError):
            trace_root = path.parent
    metadata = load_json(trace_root / "metadata.json")
    objects = object_definitions(metadata, table.headers)
    if not objects:
        raise ValueError(f"No <object>_x/<object>_y/<object>_z columns found in {path}")
    return TraceData(table=table, metadata=metadata, objects=objects)


def object_definitions(
    metadata: Mapping[str, Any], headers: Sequence[str]
) -> tuple[ObjectDefinition, ...]:
    """Returns object definitions from metadata with a CSV-column fallback."""
    header_set = set(headers)
    result: list[ObjectDefinition] = []
    used: set[str] = set()

    metadata_objects = metadata.get("objects", [])
    if isinstance(metadata_objects, list):
        for item in metadata_objects:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("name", "")).strip()
            prefix = str(item.get("prefix", name)).strip()
            if not name or not prefix or prefix in used:
                continue
            required = {f"{prefix}_x", f"{prefix}_y", f"{prefix}_z"}
            if required.issubset(header_set):
                result.append(ObjectDefinition(name=name, prefix=prefix))
                used.add(prefix)

    for header in headers:
        if not header.endswith("_x"):
            continue
        prefix = header[:-2]
        if prefix in used:
            continue
        required = {f"{prefix}_x", f"{prefix}_y", f"{prefix}_z"}
        if required.issubset(header_set):
            result.append(ObjectDefinition(name=prefix, prefix=prefix))
            used.add(prefix)

    return tuple(result)


def discover_env_ids(
    root: Path, metadata: Mapping[str, Any], status: Mapping[str, Any]
) -> tuple[int, ...]:
    """Discovers traced environment IDs from metadata, status, and file names."""
    env_ids: set[int] = set()

    metadata_ids = metadata.get("env_ids", [])
    if isinstance(metadata_ids, list):
        for value in metadata_ids:
            try:
                env_ids.add(int(value))
            except (TypeError, ValueError):
                pass

    environments = status.get("environments", {})
    if isinstance(environments, Mapping):
        for value in environments:
            try:
                env_ids.add(int(value))
            except (TypeError, ValueError):
                pass

    for pattern in (
        "live/env_*_current.csv",
        "live/env_*_latest.csv",
        "episodes/env_*",
    ):
        for path in root.glob(pattern):
            match = _ENV_RE.search(path.name)
            if match:
                env_ids.add(int(match.group(1)))

    return tuple(sorted(env_ids))


def discover_trace_files(
    root: Path, env_id: int | None, selected_csv: Path | None = None
) -> tuple[TraceFile, ...]:
    """Returns current, latest, and retained traces for one environment."""
    if selected_csv is not None:
        return (
            TraceFile(
                label=selected_csv.name,
                path=selected_csv,
                kind="file",
                env_id=_env_from_path(selected_csv),
                episode=_episode_from_path(selected_csv),
            ),
        )

    if env_id is None:
        return tuple()

    result: list[TraceFile] = []
    current = root / "live" / f"env_{env_id:03d}_current.csv"
    latest = root / "live" / f"env_{env_id:03d}_latest.csv"
    if current.is_file():
        result.append(
            TraceFile(
                "Current episode",
                current,
                "current",
                env_id,
                _episode_from_csv(current),
            )
        )
    if latest.is_file():
        result.append(
            TraceFile(
                "Latest completed episode",
                latest,
                "latest",
                env_id,
                _episode_from_csv(latest),
            )
        )

    episode_dir = root / "episodes" / f"env_{env_id:03d}"
    episode_paths = sorted(
        episode_dir.glob("episode_*.csv"),
        key=lambda path: _episode_from_path(path) or -1,
        reverse=True,
    )
    for path in episode_paths:
        episode = _episode_from_path(path)
        label = f"Episode {episode}" if episode is not None else path.name
        result.append(TraceFile(label, path, "episode", env_id, episode))

    return tuple(result)


def load_summary(root: Path) -> CsvTable | None:
    """Loads episode_summary.csv when present."""
    path = root / "episode_summary.csv"
    if not path.is_file():
        return None
    return load_csv(path)


def file_signature(path: Path) -> tuple[int, int, int] | None:
    """Returns a cheap signature for atomic-file change detection."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_mtime_ns, stat.st_size, stat.st_ino


def moving_mean(values: np.ndarray, window: int) -> np.ndarray:
    """Returns a finite-value moving mean with the original array length."""
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return values
    window = max(1, min(int(window), values.size))
    result = np.full(values.size, math.nan, dtype=float)
    for index in range(values.size):
        start = max(0, index - window + 1)
        subset = values[start : index + 1]
        finite = subset[np.isfinite(subset)]
        if finite.size:
            result[index] = float(np.mean(finite))
    return result


def _looks_like_trace_root(path: Path) -> bool:
    return path.is_dir() and (
        (path / "metadata.json").is_file()
        or (path / "live").is_dir()
        or (path / "episodes").is_dir()
        or (path / "episode_summary.csv").is_file()
    )


def _episode_from_path(path: Path) -> int | None:
    match = _EPISODE_RE.search(path.name)
    return int(match.group(1)) if match else None


def _env_from_path(path: Path) -> int | None:
    for part in reversed(path.parts):
        match = _ENV_RE.search(part)
        if match:
            return int(match.group(1))
    return None


def _episode_from_csv(path: Path) -> int | None:
    try:
        table = load_csv(path)
    except (OSError, ValueError):
        return None
    values = table.columns.get("episode")
    if isinstance(values, np.ndarray) and values.size and math.isfinite(values[0]):
        return int(values[0])
    return None
