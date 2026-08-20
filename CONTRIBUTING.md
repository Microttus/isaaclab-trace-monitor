# Contributing

Contributions are welcome through GitHub issues and pull requests.

## Development setup

```bash
python3 -m venv .venv-dev
source .venv-dev/bin/activate
python -m pip install -e '.[dev]'
```

Run the quality checks before submitting a pull request:

```bash
ruff check .
pytest
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
