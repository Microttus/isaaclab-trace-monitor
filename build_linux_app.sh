#!/usr/bin/env bash

set -euo pipefail
trap 'echo "[build_linux_app] ERROR at line ${LINENO}: ${BASH_COMMAND}" >&2' ERR

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This script must be run on Linux." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${SCRIPT_DIR}/.venv-build-linux"
DIST_DIR="${SCRIPT_DIR}/dist"
ICON_PNG="${SCRIPT_DIR}/src/isaaclab_trace_monitor/assets/app_icon.png"
DESKTOP_ICON_PNG="${SCRIPT_DIR}/packaging/linux/app_icon_256.png"
ARCH="$(uname -m)"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Python was not found: ${PYTHON_BIN}" >&2
  exit 1
fi
if [[ ! -f "${ICON_PNG}" || ! -f "${DESKTOP_ICON_PNG}" ]]; then
  echo "Application icon assets are missing." >&2
  exit 1
fi
if ! "${PYTHON_BIN}" -c 'import sys; raise SystemExit(0 if (3, 10) <= sys.version_info < (3, 15) else 1)'; then
  echo "Python 3.10 through 3.14 is required." >&2
  exit 1
fi

APP_VERSION="$(${PYTHON_BIN} - "${SCRIPT_DIR}/pyproject.toml" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
if match is None:
    raise SystemExit("Could not read project version from pyproject.toml")
print(match.group(1))
PY
)"

BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/isaaclab-trace-monitor-linux.XXXXXX")"
BUILD_SUCCEEDED=false
cleanup() {
  if [[ "${BUILD_SUCCEEDED}" == "true" ]]; then
    rm -rf "${BUILD_ROOT}"
  else
    echo "Build diagnostics were kept at: ${BUILD_ROOT}" >&2
  fi
}
trap cleanup EXIT

PYI_DIST="${BUILD_ROOT}/pyinstaller-dist"
PYI_WORK="${BUILD_ROOT}/work"
PYI_SPEC="${BUILD_ROOT}/spec"
PACKAGE_NAME="IsaacLab-Trace-Monitor-${APP_VERSION}-Linux-${ARCH}"
PACKAGE_DIR="${DIST_DIR}/${PACKAGE_NAME}"
ARCHIVE_PATH="${DIST_DIR}/${PACKAGE_NAME}.tar.gz"

rm -rf "${VENV_DIR}" "${PACKAGE_DIR}" "${ARCHIVE_PATH}"
mkdir -p "${DIST_DIR}" "${PYI_DIST}" "${PYI_WORK}" "${PYI_SPEC}"

printf 'Building IsaacLab Trace Monitor %s for Linux %s\n' "${APP_VERSION}" "${ARCH}"
"${PYTHON_BIN}" -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip wheel
"${VENV_DIR}/bin/python" -m pip install "${SCRIPT_DIR}[build]"

"${VENV_DIR}/bin/pyinstaller" \
  --noconfirm \
  --clean \
  --onedir \
  --noupx \
  --name isaaclab-trace-monitor \
  --icon "${ICON_PNG}" \
  --paths "${SCRIPT_DIR}/src" \
  --collect-data isaaclab_trace_monitor \
  --collect-all matplotlib \
  --hidden-import matplotlib.backends.backend_qtagg \
  --hidden-import PySide6.QtSvg \
  --exclude-module PyQt5 \
  --exclude-module PyQt6 \
  --exclude-module tkinter \
  --distpath "${PYI_DIST}" \
  --workpath "${PYI_WORK}" \
  --specpath "${PYI_SPEC}" \
  "${SCRIPT_DIR}/launcher.py"

APP_SOURCE="${PYI_DIST}/isaaclab-trace-monitor"
APP_EXECUTABLE="${APP_SOURCE}/isaaclab-trace-monitor"
if [[ ! -x "${APP_EXECUTABLE}" ]]; then
  echo "PyInstaller did not create the expected executable: ${APP_EXECUTABLE}" >&2
  find "${PYI_DIST}" -maxdepth 3 -print >&2 || true
  exit 1
fi

mkdir -p "${PACKAGE_DIR}"
cp -a "${APP_SOURCE}" "${PACKAGE_DIR}/app"
cp "${DESKTOP_ICON_PNG}" "${PACKAGE_DIR}/app_icon.png"
cp "${SCRIPT_DIR}/packaging/linux/install.sh" "${PACKAGE_DIR}/install.sh"
cp "${SCRIPT_DIR}/packaging/linux/uninstall.sh" "${PACKAGE_DIR}/uninstall.sh"
cp "${SCRIPT_DIR}/docs/building-linux.md" "${PACKAGE_DIR}/README-LINUX.md"
cp "${SCRIPT_DIR}/LICENSE" "${PACKAGE_DIR}/LICENSE"
cp "${SCRIPT_DIR}/THIRD_PARTY_NOTICES.md" "${PACKAGE_DIR}/THIRD_PARTY_NOTICES.md"
cp "${SCRIPT_DIR}/AI_ASSISTANCE.md" "${PACKAGE_DIR}/AI_ASSISTANCE.md"
chmod 0755 "${PACKAGE_DIR}/install.sh" "${PACKAGE_DIR}/uninstall.sh"

cat > "${PACKAGE_DIR}/isaaclab-trace-monitor" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
PACKAGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${PACKAGE_DIR}/app/isaaclab-trace-monitor" "$@"
EOF
chmod 0755 "${PACKAGE_DIR}/isaaclab-trace-monitor"

LICENSE_DIR="${PACKAGE_DIR}/licenses/third-party"
mkdir -p "${LICENSE_DIR}"
"${VENV_DIR}/bin/python" "${SCRIPT_DIR}/tools/collect_licenses.py" \
  --output "${LICENSE_DIR}"

"${PACKAGE_DIR}/isaaclab-trace-monitor" --version
"${PACKAGE_DIR}/isaaclab-trace-monitor" --diagnose

tar -C "${DIST_DIR}" -czf "${ARCHIVE_PATH}" "${PACKAGE_NAME}"
(
  cd "${DIST_DIR}"
  sha256sum "$(basename "${ARCHIVE_PATH}")" > "$(basename "${ARCHIVE_PATH}").sha256"
)
BUILD_SUCCEEDED=true

cat <<OUTPUT

Linux build completed successfully.

Portable directory:
  ${PACKAGE_DIR}

Portable archive:
  ${ARCHIVE_PATH}

Checksum:
  ${ARCHIVE_PATH}.sha256

Run without installing:
  "${PACKAGE_DIR}/isaaclab-trace-monitor"

Install for the current user:
  "${PACKAGE_DIR}/install.sh"
OUTPUT
