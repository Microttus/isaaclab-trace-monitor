from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from isaaclab_trace_monitor.data import (
    discover_env_ids,
    discover_trace_files,
    find_trace_root,
    load_json,
    load_summary,
    load_trace,
    moving_mean,
)
from isaaclab_trace_monitor.source import SourceSpec, cache_directory, rsync_arguments

ROOT = Path(__file__).resolve().parents[1] / "example_object_traces"


def test_find_trace_root_from_root_and_run_parent() -> None:
    root, selected = find_trace_root(ROOT)
    assert root == ROOT.resolve()
    assert selected is None


def test_load_trace_and_object_definitions() -> None:
    trace = load_trace(ROOT / "live" / "env_000_current.csv", ROOT)
    assert trace.row_count == 110
    assert [obj.name for obj in trace.objects] == ["pin", "pipe", "center", "ee_frame"]
    assert trace.position(trace.objects[0]).shape == (110, 3)
    assert trace.quaternion(trace.objects[0]).shape == (110, 4)
    assert np.all(np.diff(trace.sample_times()) >= 0)


def test_discovery_and_summary() -> None:
    metadata = load_json(ROOT / "metadata.json")
    status = load_json(ROOT / "live" / "status.json")
    assert discover_env_ids(ROOT, metadata, status) == (0,)
    files = discover_trace_files(ROOT, 0)
    assert [item.kind for item in files] == ["current", "latest", "episode"]
    assert files[-1].episode == 12
    summary = load_summary(ROOT)
    assert summary is not None
    assert summary.row_count == 13


def test_remote_source_and_rsync_arguments(tmp_path: Path) -> None:
    source = SourceSpec.parse("coder.example:/home/coder/run/object_traces")
    assert source.remote
    assert source.remote_host == "coder.example"
    cache = cache_directory(source)
    arguments = rsync_arguments(source, tmp_path / cache.name, include_episodes=False)
    assert "--exclude" in arguments
    assert "episodes/" in arguments
    assert arguments[-3] == "--"
    assert arguments[-2].endswith("/object_traces/")


def test_ssh_url_source() -> None:
    source = SourceSpec.parse("ssh://operator@coder.example/home/operator/traces")
    assert source.remote
    assert source.remote_host == "operator@coder.example"
    assert source.remote_path == "/home/operator/traces"


@pytest.mark.parametrize(
    "value",
    (
        "-e:/tmp/traces",
        "coder.example:/tmp/traces;touch/tmp/x",
        "coder.example:/tmp/trace folder",
        "ssh://user:password@coder.example/tmp/traces",
        "ssh://coder.example:2222/tmp/traces",
        "coder.example:/tmp/traces\nother",
    ),
)
def test_unsafe_remote_sources_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        SourceSpec.parse(value)


def test_local_source_with_spaces() -> None:
    path = ROOT.parent / "folder with spaces"
    source = SourceSpec.parse(str(path))
    assert not source.remote
    assert source.local_path == path


def test_moving_mean() -> None:
    values = np.asarray([1.0, 2.0, 3.0, 4.0])
    assert np.allclose(moving_mean(values, 2), [1.0, 1.5, 2.5, 3.5])
