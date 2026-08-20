#!/usr/bin/env bash

set -euo pipefail
trap 'echo "[build_macos_app] ERROR at line ${LINENO}: ${BASH_COMMAND}" >&2' ERR

APP_NAME="IsaacLab Trace Monitor"
BUNDLE_ID="${BUNDLE_ID:-org.isaaclabtracemonitor.desktop}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv-build"
DIST_DIR="${SCRIPT_DIR}/dist"
ICON_ICNS="${SCRIPT_DIR}/src/isaaclab_trace_monitor/assets/app_icon.icns"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script must be run on macOS." >&2
  exit 1
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Python was not found: ${PYTHON_BIN}" >&2
  echo "Set PYTHON_BIN to a Python 3.10+ executable." >&2
  exit 1
fi

if [[ ! -f "${ICON_ICNS}" ]]; then
  echo "Application icon is missing: ${ICON_ICNS}" >&2
  exit 1
fi

PYTHON_VERSION="$(${PYTHON_BIN} -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PYTHON_ARCH="$(${PYTHON_BIN} -c 'import platform; print(platform.machine())')"
HOST_ARCH="$(uname -m)"

if ! "${PYTHON_BIN}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "Python 3.10 or newer is required. Found Python ${PYTHON_VERSION}." >&2
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

if [[ "${HOST_ARCH}" == "arm64" && "${PYTHON_ARCH}" == "x86_64" ]]; then
  echo "Warning: the Mac is arm64, but Python is running as x86_64." >&2
  echo "The resulting application will require Rosetta 2." >&2
fi

BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/isaaclab-trace-monitor.XXXXXX")"
BUILD_SUCCEEDED=false

cleanup() {
  if [[ "${BUILD_SUCCEEDED}" == "true" ]]; then
    rm -rf "${BUILD_ROOT}"
  else
    echo "Build diagnostics were kept at: ${BUILD_ROOT}" >&2
  fi
}
trap cleanup EXIT

WORK_DIR="${BUILD_ROOT}/work"
SPEC_DIR="${BUILD_ROOT}/spec"
DMG_STAGE="${BUILD_ROOT}/dmg"
mkdir -p "${WORK_DIR}" "${SPEC_DIR}" "${DMG_STAGE}" "${DIST_DIR}"

APP_PATH="${DIST_DIR}/${APP_NAME}.app"
DMG_PATH="${DIST_DIR}/IsaacLab-Trace-Monitor-${APP_VERSION}-macOS.dmg"
ZIP_PATH="${DIST_DIR}/IsaacLab-Trace-Monitor-${APP_VERSION}-macOS.zip"

rm -rf "${VENV_DIR}" "${APP_PATH}" "${DMG_PATH}" "${ZIP_PATH}"

printf 'Building %s %s\n' "${APP_NAME}" "${APP_VERSION}"
printf 'Bundle identifier:   %s\n' "${BUNDLE_ID}"
printf 'Host architecture:   %s\n' "${HOST_ARCH}"
printf 'Python architecture: %s\n' "${PYTHON_ARCH}"
printf 'Python version:      %s\n' "${PYTHON_VERSION}"

"${PYTHON_BIN}" -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip wheel
"${VENV_DIR}/bin/python" -m pip install "${SCRIPT_DIR}[build]"

"${VENV_DIR}/bin/pyinstaller" \
  --noconfirm \
  --clean \
  --onedir \
  --windowed \
  --noupx \
  --name "${APP_NAME}" \
  --icon "${ICON_ICNS}" \
  --osx-bundle-identifier "${BUNDLE_ID}" \
  --paths "${SCRIPT_DIR}/src" \
  --collect-data isaaclab_trace_monitor \
  --collect-all matplotlib \
  --hidden-import matplotlib.backends.backend_qtagg \
  --exclude-module PyQt5 \
  --exclude-module PyQt6 \
  --exclude-module tkinter \
  --distpath "${DIST_DIR}" \
  --workpath "${WORK_DIR}" \
  --specpath "${SPEC_DIR}" \
  "${SCRIPT_DIR}/launcher.py"

if [[ ! -d "${APP_PATH}" ]]; then
  echo "PyInstaller did not create the expected application bundle:" >&2
  echo "  ${APP_PATH}" >&2
  find "${DIST_DIR}" -maxdepth 2 -print >&2 || true
  exit 1
fi

APP_EXECUTABLE="${APP_PATH}/Contents/MacOS/${APP_NAME}"
INFO_PLIST="${APP_PATH}/Contents/Info.plist"
LICENSE_DIR="${APP_PATH}/Contents/Resources/licenses"

if [[ ! -x "${APP_EXECUTABLE}" ]]; then
  echo "Application executable is missing: ${APP_EXECUTABLE}" >&2
  exit 1
fi

if [[ ! -f "${INFO_PLIST}" ]]; then
  echo "Application Info.plist is missing: ${INFO_PLIST}" >&2
  exit 1
fi

"${VENV_DIR}/bin/python" - "${INFO_PLIST}" "${APP_NAME}" "${APP_VERSION}" <<'PY'
from __future__ import annotations

import plistlib
import sys
from pathlib import Path

plist_path = Path(sys.argv[1])
app_name = sys.argv[2]
app_version = sys.argv[3]

with plist_path.open("rb") as stream:
    values = plistlib.load(stream)

values.update(
    {
        "CFBundleName": app_name,
        "CFBundleDisplayName": app_name,
        "CFBundleShortVersionString": app_version,
        "CFBundleVersion": app_version,
        "LSApplicationCategoryType": "public.app-category.developer-tools",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Copyright © 2026 Martin Økter",
    }
)

with plist_path.open("wb") as stream:
    plistlib.dump(values, stream, sort_keys=False)
PY

mkdir -p "${LICENSE_DIR}"
"${VENV_DIR}/bin/python" "${SCRIPT_DIR}/tools/collect_licenses.py" \
  --output "${LICENSE_DIR}/third-party"
cp "${SCRIPT_DIR}/LICENSE" "${LICENSE_DIR}/PROJECT-LICENSE.txt"
cp "${SCRIPT_DIR}/THIRD_PARTY_NOTICES.md" "${LICENSE_DIR}/THIRD_PARTY_NOTICES.md"
cp "${SCRIPT_DIR}/AI_ASSISTANCE.md" "${LICENSE_DIR}/AI_ASSISTANCE.md"

plutil -lint "${INFO_PLIST}" >/dev/null
xattr -cr "${APP_PATH}"

codesign \
  --force \
  --deep \
  --sign - \
  --timestamp=none \
  "${APP_PATH}"

codesign --verify --deep --strict --verbose=1 "${APP_PATH}"
"${APP_EXECUTABLE}" --version >/dev/null

ditto "${APP_PATH}" "${DMG_STAGE}/${APP_NAME}.app"
ln -s /Applications "${DMG_STAGE}/Applications"
hdiutil create \
  -volname "${APP_NAME}" \
  -srcfolder "${DMG_STAGE}" \
  -ov \
  -format UDZO \
  "${DMG_PATH}" >/dev/null

ditto \
  -c \
  -k \
  --sequesterRsrc \
  --keepParent \
  "${APP_PATH}" \
  "${ZIP_PATH}"

BUILD_SUCCEEDED=true

cat <<OUTPUT

Build completed successfully.

Application:
  ${APP_PATH}

Drag-to-install disk image:
  ${DMG_PATH}

Portable archive:
  ${ZIP_PATH}

Open the application directly with:
  open "${APP_PATH}"

Only products under dist/ are runnable/distributable. Files in a PyInstaller
work directory are internal build artifacts.
OUTPUT

open -R "${APP_PATH}" >/dev/null 2>&1 || true
