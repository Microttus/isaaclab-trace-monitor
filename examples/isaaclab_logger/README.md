# Isaac Lab logger example

`object_trace_callback.py` is the reference producer for the trace format read
by IsaacLab Trace Monitor. It is designed for Isaac Lab environments wrapped by
Stable-Baselines3.

`object_trace_callback_v2.py` writes format version 4, a superset of the
original. It adds contact-sensor forces, actual joint states, and a sparse
episode archive. The monitor opens both without configuration.

| Option | Effect |
|---|---|
| `contact_sensors={"alias": "scene_sensor_name"}` | Logs `contact_<alias>_fx_N`, `_fy_N`, `_fz_N`, and `_force_N` for the strongest filtered contact |
| `joint_state_entity="robot"` | Logs `<joint_state_prefix>_<label>_pos_rad` and `_vel_rad_s` for `joint_state_indices` |
| `archive_every_episodes=25` | Also writes every 25th completed episode to `archive/`, which `keep_last_episodes` never prunes |

`archive_every_episodes` is the setting that makes older episodes of a long run
reachable: retained episodes bound disk use, while the archive keeps a coarse
history the monitor can still load and play back.

## Installation

Copy the callback into your Isaac Lab extension, for example:

```text
MyExtension/
└── logging/
    └── object_trace_callback.py
```

Import it from the training script and add it to the SB3 callback list. The
focused `train_integration_example.py` file shows the required parser options
and callback construction without depending on a particular task.

Recommended first settings:

```text
--trace_objects pin,pipe,center,ee_frame
--trace_env_ids 0
--trace_interval 2
--trace_keep_episodes 20
--trace_max_samples 2000
```

Tracing one environment keeps GPU-to-CPU transfer and file output restrictive.
Set `--trace_keep_episodes 0` when only the current and latest-completed live
files should be retained.

Contact sensors, joint state, and archiving are off by default in
`object_trace_callback_v2.py`. Each contact sensor adds four columns per
sample, each traced joint adds two, and archiving adds one file per archive
interval, so enable only what you intend to inspect.

## Terminal poses

For manager-based Isaac Lab environments, the callback wraps the recorder
manager's pre-reset stage to capture the true terminal pose before the finished
environment is reset. The original recorder method is still called. If that
hook is unavailable, the callback marks the fallback condition in
`termination_reason`.

See [`docs/trace-format.md`](../../docs/trace-format.md) for the complete file
contract.
