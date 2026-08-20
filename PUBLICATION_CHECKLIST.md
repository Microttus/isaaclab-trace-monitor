# Publication checklist

This archive is ready to become a GitHub repository after replacing the
`GITHUB_OWNER` placeholder.

## 1. Configure repository metadata

```bash
python3 tools/configure_repository.py \
  --github-owner YOUR_GITHUB_USERNAME
```

Use `--author-name` only when the public author name should differ from the
current metadata:

```bash
python3 tools/configure_repository.py \
  --github-owner YOUR_GITHUB_USERNAME \
  --author-name "Your Public Name"
```

Verify that no repository URLs still use the placeholder:

```bash
rg 'github.com/GITHUB_OWNER' README.md pyproject.toml CITATION.cff .github
```

The command should return no matches.

## 2. Review publishability

Before the first public commit:

- confirm ownership of the code, icon, logger, and documentation;
- confirm that the synthetic example trace contains no confidential data;
- review `AI_ASSISTANCE.md` and retain it if it accurately reflects the project;
- review `LICENSE` and the copyright holder;
- review `THIRD_PARTY_NOTICES.md`;
- confirm that no server names, usernames, credentials, private keys, or real
  training logs are present; and
- run the tests.

```bash
python3 -m venv .venv-dev
source .venv-dev/bin/activate
python -m pip install -e '.[dev]'
ruff check .
pytest
```

On Ubuntu or Debian, install the Qt runtime first:

```bash
INSTALL_XVFB=1 ./install_linux_dependencies.sh
```

## 3. Initialize Git

```bash
git init -b main
git add .
git status
git diff --cached --stat
git commit -m "Initial public release"
```

## 4. Create and push the GitHub repository

With GitHub CLI:

```bash
gh auth login
gh repo create YOUR_GITHUB_USERNAME/isaaclab-trace-monitor \
  --public \
  --source=. \
  --push
```

Do not ask GitHub to add another README, license, or `.gitignore`; all three are
already present.

## 5. Configure repository settings

Recommended GitHub topics:

```text
isaaclab
robotics
reinforcement-learning
trajectory-visualization
pyside6
matplotlib
macos
linux
```

Enable:

- Issues;
- private vulnerability reporting;
- Dependabot alerts and updates; and
- a branch ruleset requiring the CI job before merging to `main`.

## 6. Create a release

After CI passes:

```bash
git tag -a v1.3.0 -m "IsaacLab Trace Monitor 1.3.0"
git push origin v1.3.0
```

Build macOS artifacts on a Mac:

```bash
./build_macos_app.sh
```

Build the portable Linux archive on Linux, or download the artifact produced by
the `Linux bundle` GitHub Actions workflow:

```bash
./install_linux_dependencies.sh
./build_linux_app.sh
```

Create a GitHub release after collecting both platform artifacts:

```bash
gh release create v1.3.0 \
  dist/IsaacLab-Trace-Monitor-1.3.0-macOS.dmg \
  dist/IsaacLab-Trace-Monitor-1.3.0-macOS.zip \
  dist/IsaacLab-Trace-Monitor-1.3.0-Linux-*.tar.gz \
  dist/IsaacLab-Trace-Monitor-1.3.0-Linux-*.tar.gz.sha256 \
  --title "IsaacLab Trace Monitor 1.3.0" \
  --generate-notes
```

Until Developer ID signing and notarization are configured, describe the macOS
bundle as ad-hoc signed. Describe Linux archives by their architecture and the
oldest distribution on which they were built and tested.
