# Isaac Lab logger example

`object_trace_callback.py` is the reference producer for the trace format read
by IsaacLab Trace Monitor. It is designed for Isaac Lab environments wrapped by
Stable-Baselines3.

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

## Terminal poses

For manager-based Isaac Lab environments, the callback wraps the recorder
manager's pre-reset stage to capture the true terminal pose before the finished
environment is reset. The original recorder method is still called. If that
hook is unavailable, the callback marks the fallback condition in
`termination_reason`.

See [`docs/trace-format.md`](../../docs/trace-format.md) for the complete file
contract.
