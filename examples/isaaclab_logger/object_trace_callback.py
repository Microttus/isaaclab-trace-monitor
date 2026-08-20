# Copyright (c) 2026, Martin Økter
# SPDX-License-Identifier: BSD-3-Clause

"""Bounded trajectory logging for Isaac Lab + Stable-Baselines3 training.

The callback writes compact, monitor-compatible, wide CSV files containing one
row per sampled simulation state. Only the requested environments and scene
objects are copied from the simulator.

Directory layout below ``log_dir / subdir``::

    metadata.json
    episode_summary.csv
    live/
        status.json
        env_000_current.csv
        env_000_latest.csv
    episodes/
        env_000/
            episode_000000.csv
            episode_000001.csv
            ... only the newest configured number are retained

Each object contributes the columns::

    <object>_x, <object>_y, <object>_z,
    <object>_qw, <object>_qx, <object>_qy, <object>_qz

Quaternions use Isaac Lab's ``(w, x, y, z)`` convention. Positions are
translated by the environment origin by default, while orientations remain in
world-axis orientation. This is the usual local-environment representation for
Isaac Lab's translated environment clones.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import torch
from stable_baselines3.common.callbacks import BaseCallback


@dataclass
class _TerminalSnapshot:
    """Pose and termination data captured immediately before Isaac Lab resets an env."""

    poses: dict[str, np.ndarray]
    episode_step: int
    terminated: bool
    timeout: bool
    termination_reason: str


class ObjectTraceCallback(BaseCallback):
    """Write bounded object-pose trajectories during an SB3 training run.

    Parameters
    ----------
    object_names:
        Scene entity names to trace, for example ``("pin", "pipe", "center", "ee_frame")``.
    log_dir:
        The existing Isaac Lab/SB3 run directory.
    sample_interval:
        Sample every N SB3 callback calls. One callback call normally represents
        one vectorized environment step, regardless of the number of parallel envs.
    env_ids:
        Vectorized environments to trace. Keep this small; ``(0,)`` is normally sufficient.
    subdir:
        Trace directory below ``log_dir``.
    relative_to_env_origin:
        Subtract ``scene.env_origins`` from positions. Orientations are unchanged.
    object_indices:
        Optional target/body/object index per scene entity. This is useful for a
        FrameTransformer with several targets, an articulation body, or a
        RigidObjectCollection. Unspecified entities use index 0.
    log_orientation:
        Include quaternion columns in ``(w, x, y, z)`` order.
    include_actions:
        Include flattened action columns. Disabled by default to keep files small.
    keep_last_episodes:
        Number of complete trajectory files retained per traced environment.
        ``0`` retains no completed episode files, but live files are still written.
    max_samples_per_episode:
        Hard in-memory/file limit per episode. When reached, the stored trajectory
        is thinned by a factor of two and sampling continues at the coarser rate.
        Start and terminal samples are always preserved.
    live_update_interval_s:
        Minimum wall-clock interval between atomic updates of current live files.
    max_summary_rows:
        Maximum rows retained in ``episode_summary.csv``.
    total_timesteps:
        Optional planned SB3 timestep count, used only for status/progress reporting.
    capture_terminal_pose:
        Install a lightweight pre-reset hook on Isaac Lab's RecorderManager so the
        true terminal object poses are captured before the environment resets.
    verbose:
        SB3 callback verbosity.
    """

    _FORMAT_VERSION = 2

    def __init__(
        self,
        object_names: Sequence[str],
        log_dir: str | Path,
        sample_interval: int = 5,
        env_ids: Iterable[int] = (0,),
        subdir: str = "object_traces",
        relative_to_env_origin: bool = True,
        object_indices: Mapping[str, int] | None = None,
        log_orientation: bool = True,
        include_actions: bool = False,
        keep_last_episodes: int = 20,
        max_samples_per_episode: int = 2000,
        live_update_interval_s: float = 2.0,
        max_summary_rows: int = 10_000,
        total_timesteps: int | None = None,
        capture_terminal_pose: bool = True,
        verbose: int = 0,
    ) -> None:
        super().__init__(verbose=verbose)

        if not object_names:
            raise ValueError("object_names must contain at least one scene entity name")
        if sample_interval < 1:
            raise ValueError("sample_interval must be >= 1")
        env_ids_tuple = tuple(int(env_id) for env_id in env_ids)
        if not env_ids_tuple:
            raise ValueError("env_ids must contain at least one environment id")
        if keep_last_episodes < 0:
            raise ValueError("keep_last_episodes must be >= 0")
        if max_samples_per_episode < 3:
            raise ValueError("max_samples_per_episode must be >= 3")
        if live_update_interval_s <= 0:
            raise ValueError("live_update_interval_s must be > 0")
        if max_summary_rows < 1:
            raise ValueError("max_summary_rows must be >= 1")

        self.object_names = tuple(str(name) for name in object_names)
        self.log_dir = Path(log_dir)
        self.trace_dir = self.log_dir / subdir
        self.live_dir = self.trace_dir / "live"
        self.episodes_dir = self.trace_dir / "episodes"
        self.metadata_path = self.trace_dir / "metadata.json"
        self.summary_path = self.trace_dir / "episode_summary.csv"
        self.status_path = self.live_dir / "status.json"

        self.sample_interval = int(sample_interval)
        self.env_ids = tuple(dict.fromkeys(env_ids_tuple))
        self.relative_to_env_origin = bool(relative_to_env_origin)
        self.object_indices = {
            name: int((object_indices or {}).get(name, 0)) for name in self.object_names
        }
        self.log_orientation = bool(log_orientation)
        self.include_actions = bool(include_actions)
        self.keep_last_episodes = int(keep_last_episodes)
        self.max_samples_per_episode = int(max_samples_per_episode)
        self.live_update_interval_s = float(live_update_interval_s)
        self.max_summary_rows = int(max_summary_rows)
        self.total_timesteps = None if total_timesteps is None else int(total_timesteps)
        self.capture_terminal_pose = bool(capture_terminal_pose)

        self._base_env: Any | None = None
        self._scene: Any | None = None
        self._started_at_monotonic = 0.0
        self._started_at_utc = ""
        self._last_live_write_monotonic = 0.0
        self._rollout_index = 0
        self._action_dim = 0
        self._columns: list[str] = []
        self._object_prefixes = self._make_unique_prefixes(self.object_names)

        self._episode_by_env = {env_id: 0 for env_id in self.env_ids}
        self._episode_return_by_env = {env_id: 0.0 for env_id in self.env_ids}
        self._episode_start_step_by_env = {env_id: 0 for env_id in self.env_ids}
        self._adaptive_stride_by_env = {env_id: 1 for env_id in self.env_ids}
        self._buffers: dict[int, list[dict[str, Any]]] = {env_id: [] for env_id in self.env_ids}
        self._terminal_cache: dict[int, _TerminalSnapshot] = {}
        self._latest_complete_file_by_env: dict[int, str | None] = {
            env_id: None for env_id in self.env_ids
        }
        self._latest_complete_episode_by_env: dict[int, int | None] = {
            env_id: None for env_id in self.env_ids
        }
        self._summary_rows: deque[dict[str, Any]] = deque(maxlen=self.max_summary_rows)

        self._recorder_pre_reset_original: Any | None = None
        self._terminal_hook_installed = False
        self._warned_missing_terminal_snapshot = False

    # ------------------------------------------------------------------
    # SB3 callback lifecycle
    # ------------------------------------------------------------------

    def _on_training_start(self) -> None:
        self._started_at_monotonic = time.monotonic()
        self._started_at_utc = self._utc_now()
        self._last_live_write_monotonic = self._started_at_monotonic

        self._base_env = self._resolve_base_env(self.training_env)
        self._scene = self._base_env.scene

        available = set(self._scene.keys())
        missing = [name for name in self.object_names if name not in available]
        if missing:
            raise KeyError(
                f"ObjectTraceCallback could not find scene object(s): {missing}. "
                f"Available scene keys include: {sorted(available)}"
            )

        num_envs = int(getattr(self._base_env, "num_envs", len(self.env_ids)))
        invalid = [env_id for env_id in self.env_ids if env_id < 0 or env_id >= num_envs]
        if invalid:
            raise ValueError(f"Invalid env_ids {invalid}; environment has num_envs={num_envs}")

        self._action_dim = self._infer_action_dim() if self.include_actions else 0
        self._columns = self._build_columns()

        self.live_dir.mkdir(parents=True, exist_ok=True)
        self.episodes_dir.mkdir(parents=True, exist_ok=True)
        for env_id in self.env_ids:
            (self.episodes_dir / f"env_{env_id:03d}").mkdir(parents=True, exist_ok=True)

        self._load_existing_summary()
        self._write_metadata()

        if self.capture_terminal_pose:
            self._install_pre_reset_hook()

        # SB3 resets the vectorized environment before on_training_start. Record
        # this state so every trajectory has an explicit starting pose.
        initial_poses = self._read_scene_poses(self.env_ids)
        for env_id in self.env_ids:
            self._append_sample(
                env_id=env_id,
                poses=initial_poses[env_id],
                episode_step=0,
                reward=0.0,
                action=None,
                terminal=False,
                timeout=False,
                termination_reason="",
                force=True,
            )

        self._write_live_files(force=True)
        self._write_status(running=True)

        if self.verbose:
            print(
                "[ObjectTraceCallback] "
                f"objects={self.object_names}, env_ids={self.env_ids}, "
                f"sample_interval={self.sample_interval}, keep_last_episodes={self.keep_last_episodes} "
                f"-> {self.trace_dir}"
            )

    def _on_rollout_start(self) -> None:
        self._rollout_index += 1
        self._write_status(running=True)

    def _on_step(self) -> bool:
        dones = self._as_1d_array(self.locals.get("dones"), dtype=bool)
        rewards = self._as_1d_array(self.locals.get("rewards"), dtype=float)
        actions = self._as_action_array(self.locals.get("actions"))
        infos = self.locals.get("infos")

        for env_id in self.env_ids:
            if env_id < rewards.size:
                self._episode_return_by_env[env_id] += float(rewards[env_id])

        done_env_ids = [
            env_id for env_id in self.env_ids if env_id < dones.size and bool(dones[env_id])
        ]

        # Finalize completed episodes first. The terminal pose comes from the
        # pre-reset hook because the scene has already been reset by this point.
        for env_id in done_env_ids:
            terminal_snapshot = self._terminal_cache.pop(env_id, None)
            action = self._action_for_env(actions, env_id)

            if terminal_snapshot is not None:
                self._append_sample(
                    env_id=env_id,
                    poses=terminal_snapshot.poses,
                    episode_step=terminal_snapshot.episode_step,
                    reward=(
                        float(rewards[env_id]) if env_id < rewards.size else math.nan
                    ),
                    action=action,
                    terminal=terminal_snapshot.terminated,
                    timeout=terminal_snapshot.timeout,
                    termination_reason=terminal_snapshot.termination_reason,
                    force=True,
                )
                episode_length = terminal_snapshot.episode_step
                terminated = terminal_snapshot.terminated
                timeout = terminal_snapshot.timeout
                termination_reason = terminal_snapshot.termination_reason
            else:
                # Direct environments or an incompatible Isaac Lab version may
                # not expose the RecorderManager hook. Preserve the last sampled
                # pose and clearly mark that the exact terminal pose was unavailable.
                episode_length = self._current_episode_step(env_id)
                terminated = not self._info_timeout(infos, env_id)
                timeout = self._info_timeout(infos, env_id)
                termination_reason = "terminal_pose_unavailable"
                self._mark_last_row_terminal(
                    env_id,
                    terminated=terminated,
                    timeout=timeout,
                    termination_reason=termination_reason,
                )
                if self.verbose and not self._warned_missing_terminal_snapshot:
                    print(
                        "[ObjectTraceCallback] Warning: exact pre-reset terminal pose was not captured. "
                        "The last sampled pose is used instead."
                    )
                    self._warned_missing_terminal_snapshot = True

            success = self._extract_success(infos, env_id, termination_reason)
            self._finalize_episode(
                env_id=env_id,
                episode_length=episode_length,
                terminated=terminated,
                timeout=timeout,
                termination_reason=termination_reason,
                success=success,
            )

        # Isaac Lab has now reset each completed sub-environment. Start the new
        # trajectory immediately with an explicit reset pose.
        if done_env_ids:
            reset_poses = self._read_scene_poses(done_env_ids)
            for env_id in done_env_ids:
                self._episode_by_env[env_id] += 1
                self._episode_return_by_env[env_id] = 0.0
                self._episode_start_step_by_env[env_id] = int(self.num_timesteps)
                self._adaptive_stride_by_env[env_id] = 1
                self._buffers[env_id] = []
                self._append_sample(
                    env_id=env_id,
                    poses=reset_poses[env_id],
                    episode_step=0,
                    reward=0.0,
                    action=None,
                    terminal=False,
                    timeout=False,
                    termination_reason="",
                    force=True,
                )

        # For active episodes, sample the post-step scene at the requested rate.
        if self.n_calls % self.sample_interval == 0:
            active_env_ids = [env_id for env_id in self.env_ids if env_id not in done_env_ids]
            if active_env_ids:
                poses_by_env = self._read_scene_poses(active_env_ids)
                for env_id in active_env_ids:
                    episode_step = self._current_episode_step(env_id)
                    if not self._passes_adaptive_stride(env_id, episode_step):
                        continue
                    reward = float(rewards[env_id]) if env_id < rewards.size else math.nan
                    self._append_sample(
                        env_id=env_id,
                        poses=poses_by_env[env_id],
                        episode_step=episode_step,
                        reward=reward,
                        action=self._action_for_env(actions, env_id),
                        terminal=False,
                        timeout=False,
                        termination_reason="",
                        force=False,
                    )

        now = time.monotonic()
        if done_env_ids or now - self._last_live_write_monotonic >= self.live_update_interval_s:
            self._write_live_files(force=True)
            self._write_status(running=True)
            self._last_live_write_monotonic = now

        return True

    def _on_rollout_end(self) -> None:
        self._write_live_files(force=True)
        self._write_status(running=True)

    def _on_training_end(self) -> None:
        self._write_live_files(force=True)
        self._write_status(running=False)
        self._restore_pre_reset_hook()

    # ------------------------------------------------------------------
    # Terminal state capture
    # ------------------------------------------------------------------

    def _install_pre_reset_hook(self) -> None:
        if self._base_env is None:
            return
        recorder_manager = getattr(self._base_env, "recorder_manager", None)
        original = getattr(recorder_manager, "record_pre_reset", None)
        if original is None or not callable(original):
            if self.verbose:
                print(
                    "[ObjectTraceCallback] RecorderManager.record_pre_reset is unavailable; "
                    "terminal poses will fall back to the last sampled pose."
                )
            return

        self._recorder_pre_reset_original = original

        def record_pre_reset_with_trace(env_ids, *args, **kwargs):
            self._capture_terminal_before_reset(env_ids)
            return original(env_ids, *args, **kwargs)

        recorder_manager.record_pre_reset = record_pre_reset_with_trace
        self._terminal_hook_installed = True

    def _restore_pre_reset_hook(self) -> None:
        if not self._terminal_hook_installed or self._base_env is None:
            return
        recorder_manager = getattr(self._base_env, "recorder_manager", None)
        if recorder_manager is not None and self._recorder_pre_reset_original is not None:
            recorder_manager.record_pre_reset = self._recorder_pre_reset_original
        self._terminal_hook_installed = False

    def _capture_terminal_before_reset(self, env_ids: Any) -> None:
        traced_ids = [
            env_id for env_id in self._normalize_env_ids(env_ids) if env_id in self._buffers
        ]
        if not traced_ids or self._base_env is None:
            return

        poses_by_env = self._read_scene_poses(traced_ids)
        episode_lengths = self._tensor_values(
            getattr(self._base_env, "episode_length_buf", None), traced_ids, dtype=int
        )
        termination_manager = getattr(self._base_env, "termination_manager", None)
        for local_idx, env_id in enumerate(traced_ids):
            terminated = False
            timeout = False
            reasons: list[str] = []

            if termination_manager is not None:
                terminated = self._tensor_bool_at(
                    getattr(termination_manager, "terminated", None), env_id
                )
                timeout = self._tensor_bool_at(
                    getattr(termination_manager, "time_outs", None), env_id
                )
                for term_name in getattr(termination_manager, "active_terms", []):
                    try:
                        if self._tensor_bool_at(termination_manager.get_term(term_name), env_id):
                            reasons.append(str(term_name))
                    except Exception:
                        continue
            else:
                # DirectRLEnv exposes aggregate reset tensors rather than a
                # TerminationManager. Preserve the same terminal/timeout split.
                terminated = self._tensor_bool_at(
                    getattr(self._base_env, "reset_terminated", None), env_id
                )
                timeout = self._tensor_bool_at(
                    getattr(self._base_env, "reset_time_outs", None), env_id
                )
                if terminated:
                    reasons.append("terminated")
                if timeout:
                    reasons.append("timeout")

            self._terminal_cache[env_id] = _TerminalSnapshot(
                poses=poses_by_env[env_id],
                episode_step=int(episode_lengths[local_idx]),
                terminated=bool(terminated),
                timeout=bool(timeout),
                termination_reason=";".join(reasons),
            )

    # ------------------------------------------------------------------
    # Sampling and pose extraction
    # ------------------------------------------------------------------

    def _append_sample(
        self,
        *,
        env_id: int,
        poses: dict[str, np.ndarray],
        episode_step: int,
        reward: float,
        action: np.ndarray | None,
        terminal: bool,
        timeout: bool,
        termination_reason: str,
        force: bool,
    ) -> None:
        buffer = self._buffers[env_id]

        if len(buffer) >= self.max_samples_per_episode:
            self._thin_buffer(env_id)
            buffer = self._buffers[env_id]

        if not force and len(buffer) >= self.max_samples_per_episode:
            return

        row: dict[str, Any] = {
            "global_step": int(self.num_timesteps),
            "callback_call": int(self.n_calls),
            "rollout": int(self._rollout_index),
            "wall_time_s": float(time.monotonic() - self._started_at_monotonic),
            "env_id": int(env_id),
            "episode": int(self._episode_by_env[env_id]),
            "sample_index": 0,  # re-indexed immediately before writing
            "episode_step": int(episode_step),
            "reward": float(reward),
            "episode_return": float(self._episode_return_by_env[env_id]),
            "terminal": int(bool(terminal)),
            "timeout": int(bool(timeout)),
            "termination_reason": str(termination_reason),
        }

        for object_name in self.object_names:
            prefix = self._object_prefixes[object_name]
            pose = np.asarray(poses[object_name], dtype=float).reshape(-1)
            if pose.size < 3:
                raise ValueError(f"Pose for {object_name!r} has fewer than three position values")
            row[f"{prefix}_x"] = float(pose[0])
            row[f"{prefix}_y"] = float(pose[1])
            row[f"{prefix}_z"] = float(pose[2])
            if self.log_orientation:
                quat = pose[3:7] if pose.size >= 7 else np.full(4, np.nan)
                row[f"{prefix}_qw"] = float(quat[0])
                row[f"{prefix}_qx"] = float(quat[1])
                row[f"{prefix}_qy"] = float(quat[2])
                row[f"{prefix}_qz"] = float(quat[3])

        if self.include_actions:
            flat_action = (
                np.full(self._action_dim, np.nan, dtype=float)
                if action is None
                else np.asarray(action, dtype=float).reshape(-1)
            )
            if flat_action.size != self._action_dim:
                padded = np.full(self._action_dim, np.nan, dtype=float)
                padded[: min(self._action_dim, flat_action.size)] = flat_action[: self._action_dim]
                flat_action = padded
            for index, value in enumerate(flat_action):
                row[f"action_{index}"] = float(value)

        buffer.append(row)

    def _thin_buffer(self, env_id: int) -> None:
        """Bound an episode while preserving its overall path and final sample."""
        old = self._buffers[env_id]
        if len(old) < 3:
            return
        thinned = old[::2]
        if thinned[-1] is not old[-1]:
            thinned.append(old[-1])
        self._buffers[env_id] = thinned
        self._adaptive_stride_by_env[env_id] *= 2

    def _passes_adaptive_stride(self, env_id: int, episode_step: int) -> bool:
        stride = self._adaptive_stride_by_env[env_id]
        if stride <= 1:
            return True
        sample_number = max(episode_step // self.sample_interval, 0)
        return sample_number % stride == 0

    def _read_scene_poses(self, env_ids: Iterable[int]) -> dict[int, dict[str, np.ndarray]]:
        if self._scene is None:
            raise RuntimeError("Scene is not initialized")

        selected_ids = tuple(int(env_id) for env_id in env_ids)
        if not selected_ids:
            return {}
        poses_by_env: dict[int, dict[str, np.ndarray]] = {env_id: {} for env_id in selected_ids}

        for object_name in self.object_names:
            obj = self._scene[object_name]
            pos, quat = self._read_pose_tensors(obj, self.object_indices[object_name])

            if self.relative_to_env_origin:
                origins = self._scene.env_origins
                pos = pos - origins

            ids_tensor = pos.new_tensor(selected_ids, dtype=torch.long)
            pos_np = pos.index_select(0, ids_tensor).detach().cpu().numpy()
            if quat is None:
                quat_np = np.full((len(selected_ids), 4), np.nan, dtype=float)
            else:
                quat_np = quat.index_select(0, ids_tensor).detach().cpu().numpy()

            for local_idx, env_id in enumerate(selected_ids):
                poses_by_env[env_id][object_name] = np.concatenate(
                    (pos_np[local_idx], quat_np[local_idx]), axis=0
                )

        return poses_by_env

    @staticmethod
    def _read_pose_tensors(obj: Any, item_index: int) -> tuple[torch.Tensor, torch.Tensor | None]:
        data = getattr(obj, "data", None)
        if data is None:
            raise AttributeError(f"Scene object {obj!r} has no .data attribute")

        # FrameTransformer: target world pose after configured offsets.
        if hasattr(data, "target_pos_w"):
            pos = data.target_pos_w
            quat = getattr(data, "target_quat_w", None)
        # RigidObjectCollection: select one object with object_indices.
        elif hasattr(data, "object_link_pos_w"):
            pos = data.object_link_pos_w
            quat = getattr(data, "object_link_quat_w", None)
        elif hasattr(data, "object_pos_w"):
            pos = data.object_pos_w
            quat = getattr(data, "object_quat_w", None)
        # RigidObject/Articulation: prefer the actor/root-link frame, which maps
        # directly to the object's USD/root geometry frame.
        elif hasattr(data, "root_pos_w"):
            pos = data.root_pos_w
            quat = getattr(data, "root_quat_w", None)
        elif hasattr(data, "root_link_pos_w"):
            pos = data.root_link_pos_w
            quat = getattr(data, "root_link_quat_w", None)
        elif hasattr(data, "root_com_pos_w"):
            pos = data.root_com_pos_w
            quat = getattr(data, "root_com_quat_w", None)
        elif hasattr(data, "body_pos_w"):
            pos = data.body_pos_w
            quat = getattr(data, "body_quat_w", None)
        elif hasattr(data, "body_link_pos_w"):
            pos = data.body_link_pos_w
            quat = getattr(data, "body_link_quat_w", None)
        else:
            raise AttributeError(
                f"Scene object {obj!r} does not expose a supported world-position tensor"
            )

        if not isinstance(pos, torch.Tensor):
            raise TypeError(f"Expected a torch.Tensor position, got {type(pos)!r}")

        if pos.ndim == 3:
            if item_index < 0 or item_index >= pos.shape[1]:
                raise IndexError(
                    f"item_index={item_index} is invalid for position shape {tuple(pos.shape)}"
                )
            pos = pos[:, item_index, :]
        elif pos.ndim != 2:
            raise ValueError(f"Expected position shape [N,3] or [N,M,3], got {tuple(pos.shape)}")

        if quat is not None:
            if not isinstance(quat, torch.Tensor):
                quat = None
            elif quat.ndim == 3:
                if item_index < 0 or item_index >= quat.shape[1]:
                    raise IndexError(
                        f"item_index={item_index} is invalid for quaternion shape {tuple(quat.shape)}"
                    )
                quat = quat[:, item_index, :]
            elif quat.ndim != 2:
                raise ValueError(
                    f"Expected quaternion shape [N,4] or [N,M,4], got {tuple(quat.shape)}"
                )

        return pos, quat

    # ------------------------------------------------------------------
    # Episode finalization and files
    # ------------------------------------------------------------------

    def _finalize_episode(
        self,
        *,
        env_id: int,
        episode_length: int,
        terminated: bool,
        timeout: bool,
        termination_reason: str,
        success: float,
    ) -> None:
        episode = self._episode_by_env[env_id]
        rows = self._rows_for_writing(self._buffers[env_id])
        episode_file = self.episodes_dir / f"env_{env_id:03d}" / f"episode_{episode:06d}.csv"

        if self.keep_last_episodes > 0:
            self._atomic_write_csv(episode_file, rows)
            self._latest_complete_file_by_env[env_id] = str(
                episode_file.relative_to(self.trace_dir)
            )
            self._latest_complete_episode_by_env[env_id] = episode
            self._apply_episode_retention(env_id)
        else:
            self._latest_complete_file_by_env[env_id] = None
            self._latest_complete_episode_by_env[env_id] = episode

        latest_file = self.live_dir / f"env_{env_id:03d}_latest.csv"
        self._atomic_write_csv(latest_file, rows)

        summary_row = {
            "global_step": int(self.num_timesteps),
            "wall_time_s": float(time.monotonic() - self._started_at_monotonic),
            "rollout": int(self._rollout_index),
            "env_id": int(env_id),
            "episode": int(episode),
            "episode_return": float(self._episode_return_by_env[env_id]),
            "episode_length": int(episode_length),
            "samples": int(len(rows)),
            "terminated": int(bool(terminated)),
            "timeout": int(bool(timeout)),
            "success": float(success),
            "termination_reason": str(termination_reason),
            "file": str(episode_file.relative_to(self.trace_dir))
            if self.keep_last_episodes > 0
            else "",
        }
        self._summary_rows.append(summary_row)
        self._write_summary()

        if self.verbose:
            print(
                "[ObjectTraceCallback] "
                f"env={env_id} episode={episode} return={self._episode_return_by_env[env_id]:.4f} "
                f"length={episode_length} samples={len(rows)} reason={termination_reason or '-'}"
            )

    def _write_live_files(self, force: bool = False) -> None:
        del force  # kept for a clear call site and future throttling changes
        for env_id in self.env_ids:
            current_path = self.live_dir / f"env_{env_id:03d}_current.csv"
            self._atomic_write_csv(current_path, self._rows_for_writing(self._buffers[env_id]))

    def _write_metadata(self) -> None:
        step_dt = getattr(self._base_env, "step_dt", None)
        objects = [
            {
                "name": name,
                "prefix": self._object_prefixes[name],
                "item_index": self.object_indices[name],
            }
            for name in self.object_names
        ]
        metadata = {
            "format_version": self._FORMAT_VERSION,
            "created_utc": self._started_at_utc,
            "objects": objects,
            "env_ids": list(self.env_ids),
            "sample_interval_callback_calls": self.sample_interval,
            "relative_to_env_origin": self.relative_to_env_origin,
            "coordinate_frame": (
                "world axes with environment-origin translation removed"
                if self.relative_to_env_origin
                else "simulation world"
            ),
            "position_units": "m",
            "quaternion_order": "wxyz" if self.log_orientation else None,
            "simulation_step_dt_s": None if step_dt is None else float(step_dt),
            "include_actions": self.include_actions,
            "action_dimension": self._action_dim,
            "keep_last_episodes_per_env": self.keep_last_episodes,
            "max_samples_per_episode": self.max_samples_per_episode,
            "live_update_interval_s": self.live_update_interval_s,
            "capture_terminal_pose": self.capture_terminal_pose,
            "reward_source": (
                "Stable-Baselines3 callback reward after any active vector wrappers; "
                "episode_return is the cumulative sum of this same value"
            ),
            "columns": self._columns,
        }
        self._atomic_write_json(self.metadata_path, metadata)

    def _write_status(self, *, running: bool) -> None:
        progress = None
        if self.total_timesteps and self.total_timesteps > 0:
            progress = min(100.0, 100.0 * float(self.num_timesteps) / self.total_timesteps)

        environments: dict[str, Any] = {}
        for env_id in self.env_ids:
            environments[str(env_id)] = {
                "episode": self._episode_by_env[env_id],
                "episode_return": self._episode_return_by_env[env_id],
                "current_samples": len(self._buffers[env_id]),
                "adaptive_stride": self._adaptive_stride_by_env[env_id],
                "current_file": f"live/env_{env_id:03d}_current.csv",
                "latest_file": f"live/env_{env_id:03d}_latest.csv",
                "latest_complete_episode": self._latest_complete_episode_by_env[env_id],
                "retained_episode_file": self._latest_complete_file_by_env[env_id],
            }

        status = {
            "format_version": self._FORMAT_VERSION,
            "running": bool(running),
            "updated_utc": self._utc_now(),
            "wall_time_s": float(time.monotonic() - self._started_at_monotonic),
            "global_step": int(self.num_timesteps),
            "total_timesteps": self.total_timesteps,
            "progress_percent": progress,
            "callback_call": int(self.n_calls),
            "rollout": int(self._rollout_index),
            "environments": environments,
        }
        self._atomic_write_json(self.status_path, status)

    def _write_summary(self) -> None:
        columns = [
            "global_step",
            "wall_time_s",
            "rollout",
            "env_id",
            "episode",
            "episode_return",
            "episode_length",
            "samples",
            "terminated",
            "timeout",
            "success",
            "termination_reason",
            "file",
        ]
        self._atomic_write_csv(self.summary_path, list(self._summary_rows), columns=columns)

    def _load_existing_summary(self) -> None:
        if not self.summary_path.is_file():
            return
        try:
            with self.summary_path.open("r", newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    self._summary_rows.append(dict(row))
        except (OSError, csv.Error):
            self._summary_rows.clear()

    def _apply_episode_retention(self, env_id: int) -> None:
        episode_dir = self.episodes_dir / f"env_{env_id:03d}"
        files = sorted(episode_dir.glob("episode_*.csv"), key=lambda path: path.name)
        excess = len(files) - self.keep_last_episodes
        for path in files[: max(excess, 0)]:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def _rows_for_writing(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for sample_index, source in enumerate(rows):
            row = dict(source)
            row["sample_index"] = sample_index
            result.append(row)
        return result

    def _mark_last_row_terminal(
        self, env_id: int, *, terminated: bool, timeout: bool, termination_reason: str
    ) -> None:
        if not self._buffers[env_id]:
            return
        row = self._buffers[env_id][-1]
        row["terminal"] = int(bool(terminated))
        row["timeout"] = int(bool(timeout))
        row["termination_reason"] = termination_reason
        row["episode_return"] = float(self._episode_return_by_env[env_id])

    # ------------------------------------------------------------------
    # General helpers
    # ------------------------------------------------------------------

    def _build_columns(self) -> list[str]:
        columns = [
            "global_step",
            "callback_call",
            "rollout",
            "wall_time_s",
            "env_id",
            "episode",
            "sample_index",
            "episode_step",
            "reward",
            "episode_return",
            "terminal",
            "timeout",
            "termination_reason",
        ]
        for object_name in self.object_names:
            prefix = self._object_prefixes[object_name]
            columns.extend([f"{prefix}_x", f"{prefix}_y", f"{prefix}_z"])
            if self.log_orientation:
                columns.extend(
                    [
                        f"{prefix}_qw",
                        f"{prefix}_qx",
                        f"{prefix}_qy",
                        f"{prefix}_qz",
                    ]
                )
        if self.include_actions:
            columns.extend(f"action_{index}" for index in range(self._action_dim))
        return columns

    def _infer_action_dim(self) -> int:
        action_space = getattr(self.training_env, "action_space", None)
        shape = getattr(action_space, "shape", None)
        if shape:
            return int(np.prod(shape))
        return 1

    def _current_episode_step(self, env_id: int) -> int:
        if self._base_env is None:
            return 0
        buffer = getattr(self._base_env, "episode_length_buf", None)
        if isinstance(buffer, torch.Tensor):
            return int(buffer[env_id].detach().cpu().item())
        return max(int(self.n_calls), 0)

    @staticmethod
    def _make_unique_prefixes(names: Sequence[str]) -> dict[str, str]:
        prefixes: dict[str, str] = {}
        used: set[str] = set()
        for name in names:
            prefix = re.sub(r"[^A-Za-z0-9_]", "_", name)
            prefix = re.sub(r"_+", "_", prefix).strip("_") or "object"
            if prefix[0].isdigit():
                prefix = f"obj_{prefix}"
            candidate = prefix
            suffix = 2
            while candidate in used:
                candidate = f"{prefix}_{suffix}"
                suffix += 1
            used.add(candidate)
            prefixes[name] = candidate
        return prefixes

    @staticmethod
    def _as_1d_array(value: Any, dtype: Any) -> np.ndarray:
        if value is None:
            return np.empty(0, dtype=dtype)
        if isinstance(value, torch.Tensor):
            value = value.detach().cpu().numpy()
        return np.asarray(value, dtype=dtype).reshape(-1)

    @staticmethod
    def _as_action_array(value: Any) -> np.ndarray | None:
        if value is None:
            return None
        if isinstance(value, torch.Tensor):
            value = value.detach().cpu().numpy()
        array = np.asarray(value)
        if array.ndim == 0:
            return array.reshape(1, 1)
        if array.ndim == 1:
            return array.reshape(-1, 1)
        return array.reshape(array.shape[0], -1)

    @staticmethod
    def _action_for_env(actions: np.ndarray | None, env_id: int) -> np.ndarray | None:
        if actions is None or env_id >= actions.shape[0]:
            return None
        return actions[env_id]

    @staticmethod
    def _info_timeout(infos: Any, env_id: int) -> bool:
        try:
            info = infos[env_id]
            return bool(info.get("TimeLimit.truncated", False))
        except (IndexError, KeyError, TypeError):
            return False

    @staticmethod
    def _extract_success(infos: Any, env_id: int, termination_reason: str) -> float:
        try:
            info = infos[env_id]
        except (IndexError, TypeError):
            info = {}

        candidates: list[Any] = []
        if isinstance(info, dict):
            candidates.extend(info.get(key) for key in ("is_success", "success") if key in info)
            episode_info = info.get("episode")
            if isinstance(episode_info, dict):
                for key, value in episode_info.items():
                    if "success" in str(key).lower():
                        candidates.append(value)

        for value in candidates:
            try:
                if isinstance(value, torch.Tensor):
                    value = value.detach().cpu().item()
                array = np.asarray(value).reshape(-1)
                if array.size:
                    return float(bool(array[0]))
            except Exception:
                continue

        if "success" in termination_reason.lower():
            return 1.0
        return math.nan

    def _normalize_env_ids(self, env_ids: Any) -> list[int]:
        if env_ids is None:
            if self._base_env is None:
                return []
            return list(range(int(self._base_env.num_envs)))
        if isinstance(env_ids, torch.Tensor):
            return [int(value) for value in env_ids.detach().cpu().reshape(-1).tolist()]
        if isinstance(env_ids, np.ndarray):
            return [int(value) for value in env_ids.reshape(-1).tolist()]
        if isinstance(env_ids, slice):
            if self._base_env is None:
                return []
            return list(range(int(self._base_env.num_envs)))[env_ids]
        return [int(value) for value in env_ids]

    @staticmethod
    def _tensor_values(tensor: Any, env_ids: Sequence[int], dtype: Any) -> np.ndarray:
        if isinstance(tensor, torch.Tensor):
            ids = tensor.new_tensor(env_ids, dtype=torch.long)
            return tensor.index_select(0, ids).detach().cpu().numpy().astype(dtype, copy=False)
        return np.zeros(len(env_ids), dtype=dtype)

    @staticmethod
    def _tensor_bool_at(tensor: Any, env_id: int) -> bool:
        if isinstance(tensor, torch.Tensor):
            return bool(tensor[env_id].detach().cpu().item())
        if tensor is None:
            return False
        try:
            return bool(np.asarray(tensor).reshape(-1)[env_id])
        except Exception:
            return False

    @staticmethod
    def _resolve_base_env(env: Any) -> Any:
        """Walk through SB3/VecNormalize/Sb3VecEnvWrapper wrappers."""
        current = env
        seen: set[int] = set()
        for _ in range(32):
            if id(current) in seen:
                break
            seen.add(id(current))

            candidate = getattr(current, "unwrapped", None)
            if candidate is not None:
                try:
                    if hasattr(candidate, "scene"):
                        return candidate
                except Exception:
                    pass

            if hasattr(current, "scene"):
                return current
            if hasattr(current, "venv"):
                current = current.venv
                continue
            if hasattr(current, "env"):
                current = current.env
                continue
            break

        raise RuntimeError(
            "Could not find the Isaac Lab base environment from the SB3 training_env. "
            "Expected a wrapper chain containing Sb3VecEnvWrapper or an env with .unwrapped.scene."
        )

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _atomic_write_csv(
        self,
        path: Path,
        rows: Sequence[Mapping[str, Any]],
        *,
        columns: Sequence[str] | None = None,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.tmp")
        fieldnames = list(columns or self._columns)
        with tmp_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, path)

    @staticmethod
    def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.tmp")
        with tmp_path.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, path)
