# Building and installing on Linux

Linux is supported both from source and as a portable PyInstaller bundle. The
reference CI environments are Ubuntu 22.04/24.04 on x86-64.

## Install runtime dependencies

On Ubuntu or Debian:

```bash
./install_linux_dependencies.sh
```

For CI or headless smoke testing, also install Xvfb:

```bash
INSTALL_XVFB=1 ./install_linux_dependencies.sh
```

The helper installs the Qt 6 XCB/OpenGL runtime libraries used by PySide6 plus
`python3-venv`, `rsync`, and `openssh-client`. Other distributions need the
equivalent packages from their package manager.

## Run from source

```bash
./run_monitor.sh --diagnose
./run_monitor.sh ./example_object_traces
```

`--diagnose` imports PySide6 and Matplotlib's QtAgg backend without creating a
window. It also reports the selected Qt plugin path and whether `ssh` and
`rsync` are available.

## Build a portable application

Build on the same architecture as the target Linux computer:

```bash
./build_linux_app.sh
```

The script creates:

```text
dist/IsaacLab-Trace-Monitor-<version>-Linux-<architecture>/
dist/IsaacLab-Trace-Monitor-<version>-Linux-<architecture>.tar.gz
dist/IsaacLab-Trace-Monitor-<version>-Linux-<architecture>.tar.gz.sha256
```

Run the extracted bundle directly:

```bash
./IsaacLab-Trace-Monitor-*/isaaclab-trace-monitor
```

The bundle contains the Python interpreter, application modules, PySide6/Qt,
Matplotlib, NumPy, the icon, project notices, and collected third-party license
files. It still relies on normal Linux system libraries and does not bundle
`ssh` or `rsync`.

## Install for one user

From the extracted bundle:

```bash
./install.sh
```

This installs only into the current user's directories:

```text
${XDG_DATA_HOME:-~/.local/share}/isaaclab-trace-monitor/
${XDG_DATA_HOME:-~/.local/share}/applications/isaaclab-trace-monitor.desktop
${XDG_DATA_HOME:-~/.local/share}/icons/hicolor/256x256/apps/
${XDG_BIN_HOME:-~/.local/bin}/isaaclab-trace-monitor
```

No root access is used. Remove it with the `uninstall.sh` included in the
extracted archive.

## GitHub Actions bundle

The `Linux bundle` workflow builds on Ubuntu 22.04, runs the frozen application
under Xvfb, and uploads the `.tar.gz` plus checksum as a workflow artifact. It
runs manually and for version tags.

## Troubleshooting

First run:

```bash
isaaclab-trace-monitor --diagnose
```

If the binding imports but the window cannot start, inspect Qt's platform
plugin loading:

```bash
QT_DEBUG_PLUGINS=1 isaaclab-trace-monitor
```

For a headless test:

```bash
QT_QPA_PLATFORM=xcb xvfb-run -a \
  isaaclab-trace-monitor ./example_object_traces --smoke-test
```

For a normal Linux desktop, do not set `QT_QPA_PLATFORM`; Qt will select the
available display integration. On an X11/XWayland session, `xcb` is the normal
Qt platform plugin.

A bundle built on one CPU architecture will not run on another. Build x86-64
artifacts on x86-64 and ARM64 artifacts on ARM64. For broad public Linux
releases, build on the oldest distribution version you intend to support and
test the resulting archive on each advertised distribution.
