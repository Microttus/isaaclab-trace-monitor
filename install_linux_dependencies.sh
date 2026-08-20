#!/usr/bin/env bash

set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This helper is intended for Linux." >&2
  exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
  cat >&2 <<'EOF'
This helper currently supports Ubuntu and Debian through apt-get.
Install Python 3.10+, python3-venv, rsync, OpenSSH, and the Qt 6 XCB/OpenGL
runtime libraries using your distribution's package manager.
EOF
  exit 1
fi

SUDO=()
if [[ "${EUID}" -ne 0 ]]; then
  if ! command -v sudo >/dev/null 2>&1; then
    echo "sudo is required when this script is not run as root." >&2
    exit 1
  fi
  SUDO=(sudo)
fi

"${SUDO[@]}" apt-get update
"${SUDO[@]}" apt-get install -y --no-install-recommends \
  python3-venv \
  rsync \
  openssh-client \
  libegl1 \
  libgl1 \
  libopengl0 \
  libdbus-1-3 \
  libfontconfig1 \
  libfreetype6 \
  libx11-6 \
  libx11-xcb1 \
  libxext6 \
  libxrender1 \
  libxi6 \
  libsm6 \
  libice6 \
  libxcb1 \
  libxcb-cursor0 \
  libxcb-icccm4 \
  libxcb-image0 \
  libxcb-keysyms1 \
  libxcb-randr0 \
  libxcb-render0 \
  libxcb-render-util0 \
  libxcb-shape0 \
  libxcb-shm0 \
  libxcb-sync1 \
  libxcb-util1 \
  libxcb-xfixes0 \
  libxcb-xinerama0 \
  libxcb-xkb1 \
  libxkbcommon0 \
  libxkbcommon-x11-0

if [[ "${INSTALL_XVFB:-0}" == "1" ]]; then
  "${SUDO[@]}" apt-get install -y --no-install-recommends xvfb xauth
fi

cat <<'EOF'

Linux runtime dependencies installed.
Run:
  ./run_monitor.sh --diagnose
  ./run_monitor.sh ./example_object_traces
EOF
