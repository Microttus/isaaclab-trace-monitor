from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from isaaclab_trace_monitor.data import (
    contact_definitions,
    discover_env_ids,
    discover_trace_files,
    find_trace_root,
    joint_definitions,
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
    assert [item.kind for item in files] == [
        "current",
        "latest",
        "episode",
        "archive",
        "archive",
    ]
    assert [item.episode for item in files[2:]] == [12, 6, 0]
    summary = load_summary(ROOT)
    assert summary is not None
    assert summary.row_count == 13


def test_archived_episodes_are_selectable() -> None:
    files = discover_trace_files(ROOT, 0)
    archived = [item for item in files if item.kind == "archive"]
    assert [item.label for item in archived] == [
        "Episode 6 (archived)",
        "Episode 0 (archived)",
    ]
    assert all(item.path.parent.parent.name == "archive" for item in archived)


def test_retained_episode_wins_over_its_archived_copy() -> None:
    files = discover_trace_files(ROOT, 0)
    episode_12 = [
        item
        for item in files
        if item.episode == 12 and item.kind in ("episode", "archive")
    ]
    assert len(episode_12) == 1
    assert episode_12[0].kind == "episode"
    assert episode_12[0].path.parent.parent.name == "episodes"


def test_contact_and_joint_definitions_from_metadata() -> None:
    trace = load_trace(ROOT / "live" / "env_000_latest.csv", ROOT)
    assert trace.has_signals
    assert [sensor.name for sensor in trace.contacts] == [
        "left_finger",
        "right_finger",
        "pin_tip",
    ]
    assert trace.contacts[0].prefix == "contact_left_finger"
    assert trace.contacts[0].sensor == "left_finger_contact"
    assert [joint.name for joint in trace.joints] == ["left", "right"]
    assert [joint.index for joint in trace.joints] == [7, 8]
    assert trace.joints[0].prefix == "gripper_left"

    magnitude = trace.contact_magnitude(trace.contacts[0])
    components = trace.contact_components(trace.contacts[0])
    assert magnitude.shape == (trace.row_count,)
    assert components.shape == (trace.row_count, 3)
    assert np.allclose(np.linalg.norm(components, axis=1), magnitude)
    assert magnitude[0] == 0.0
    assert magnitude[-1] > 1.0
    assert trace.joint_position(trace.joints[0]).shape == (trace.row_count,)
    assert trace.joint_velocity(trace.joints[0]).shape == (trace.row_count,)


def test_definitions_fall_back_to_csv_columns() -> None:
    headers = (
        "contact_tool_fx_N",
        "contact_tool_fy_N",
        "contact_tool_fz_N",
        "contact_tool_force_N",
        "gripper_left_pos_rad",
        "gripper_left_vel_rad_s",
        "gripper_right_pos_rad",
    )
    contacts = contact_definitions({}, headers)
    assert [sensor.name for sensor in contacts] == ["tool"]
    assert contacts[0].prefix == "contact_tool"
    joints = joint_definitions({}, headers)
    assert [joint.name for joint in joints] == ["gripper_left"]


def test_trace_without_signals_reports_none() -> None:
    headers = ("pin_x", "pin_y", "pin_z")
    assert contact_definitions({}, headers) == ()
    assert joint_definitions({}, headers) == ()


def test_remote_source_and_rsync_arguments(tmp_path: Path) -> None:
    source = SourceSpec.parse("coder.example:/home/coder/run/object_traces")
    assert source.remote
    assert source.remote_host == "coder.example"
    cache = cache_directory(source)
    arguments = rsync_arguments(source, tmp_path / cache.name, include_episodes=False)
    assert "--exclude" in arguments
    assert "episodes/" in arguments
    assert "archive/" in arguments
    assert arguments[-3] == "--"
    assert arguments[-2].endswith("/object_traces/")


def test_rsync_archive_inclusion(tmp_path: Path) -> None:
    source = SourceSpec.parse("coder.example:/home/coder/run/object_traces")
    arguments = rsync_arguments(
        source, tmp_path, include_episodes=True, include_archive=True
    )
    assert "episodes/" not in arguments
    assert "archive/" not in arguments
    arguments = rsync_arguments(
        source, tmp_path, include_episodes=True, include_archive=False
    )
    assert "episodes/" not in arguments
    assert "archive/" in arguments


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
