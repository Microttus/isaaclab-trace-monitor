"""Minimal Stable-Baselines3 integration example for ObjectTraceCallback.

Copy the callback into your Isaac Lab extension and adapt the import path. This
file is intentionally a focused integration fragment rather than a complete
Isaac Lab training script.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from stable_baselines3.common.callbacks import CallbackList

from object_trace_callback import ObjectTraceCallback


def add_trace_arguments(parser: argparse.ArgumentParser) -> None:
    """Add bounded trace options to an existing Isaac Lab training parser."""
    parser.add_argument(
        "--trace_objects",
        type=str,
        default="",
        help="Comma-separated Isaac Lab scene entity names; empty disables tracing.",
    )
    parser.add_argument(
        "--trace_env_ids",
        type=str,
        default="0",
        help="Comma-separated vectorized environment IDs to trace.",
    )
    parser.add_argument(
        "--trace_interval",
        type=int,
        default=5,
        help="Sample every N vectorized environment steps.",
    )
    parser.add_argument(
        "--trace_keep_episodes",
        type=int,
        default=20,
        help="Number of complete episode files retained per traced environment.",
    )
    parser.add_argument(
        "--trace_max_samples",
        type=int,
        default=2000,
        help="Maximum stored samples per episode before adaptive thinning.",
    )


def make_callbacks(
    *,
    existing_callbacks: list,
    args: argparse.Namespace,
    log_dir: str | Path,
    total_timesteps: int,
) -> CallbackList:
    """Append the trace callback to an existing SB3 callback list."""
    callbacks = list(existing_callbacks)
    object_names = tuple(
        name.strip() for name in args.trace_objects.split(",") if name.strip()
    )
    if object_names:
        env_ids = tuple(
            int(value.strip())
            for value in args.trace_env_ids.split(",")
            if value.strip()
        )
        callbacks.append(
            ObjectTraceCallback(
                object_names=object_names,
                log_dir=log_dir,
                env_ids=env_ids,
                sample_interval=args.trace_interval,
                keep_last_episodes=args.trace_keep_episodes,
                max_samples_per_episode=args.trace_max_samples,
                total_timesteps=total_timesteps,
                verbose=1,
            )
        )
    return CallbackList(callbacks)
