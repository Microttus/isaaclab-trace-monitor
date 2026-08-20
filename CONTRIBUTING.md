# Contributing

Contributions are welcome through GitHub issues and pull requests.

## Development setup

```bash
python3 -m venv .venv-dev
source .venv-dev/bin/activate
python -m pip install -e '.[dev]'
```

On Ubuntu/Debian, install the Qt runtime and Xvfb first:

```bash
INSTALL_XVFB=1 ./install_linux_dependencies.sh
```

Run the quality checks before submitting a pull request:

```bash
ruff check .
pytest
```

Run a Linux GUI smoke test with:

```bash
QT_QPA_PLATFORM=xcb xvfb-run -a \
  isaaclab-trace-monitor ./example_object_traces --smoke-test
```

## Scope

Keep the monitor independent of Isaac Sim at runtime. Isaac Lab-specific code
belongs in `examples/isaaclab_logger/`; the desktop application should continue
to operate from bounded CSV/JSON files alone.

Changes to the trace format must update:

- `docs/trace-format.md`;
- the reference logger;
- the data loader; and
- relevant tests and example files.

Platform-specific changes should preserve both the macOS and Linux source
runners. Native application bundles must include the project notices and the
third-party license material collected by the build scripts.

## Pull requests

Describe:

- the problem being solved;
- the expected user-visible behavior;
- platforms tested;
- test results; and
- any compatibility or file-format impact.

Substantial use of generative AI in a contribution should be disclosed in the
pull request. Generated code must be reviewed and tested like any other code.
Do not submit confidential prompts, training logs, credentials, or proprietary
source material.
