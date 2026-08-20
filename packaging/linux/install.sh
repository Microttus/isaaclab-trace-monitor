#!/usr/bin/env bash

set -euo pipefail

PACKAGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_APP="${PACKAGE_DIR}/app"
DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
BIN_HOME="${XDG_BIN_HOME:-${HOME}/.local/bin}"
APP_HOME="${DATA_HOME}/isaaclab-trace-monitor"
APPLICATIONS_HOME="${DATA_HOME}/applications"
ICON_HOME="${DATA_HOME}/icons/hicolor/256x256/apps"
EXECUTABLE="${BIN_HOME}/isaaclab-trace-monitor"
DESKTOP_FILE="${APPLICATIONS_HOME}/isaaclab-trace-monitor.desktop"
ICON_FILE="${ICON_HOME}/isaaclab-trace-monitor.png"

if [[ ! -x "${SOURCE_APP}/isaaclab-trace-monitor" ]]; then
  echo "Portable application payload is missing: ${SOURCE_APP}" >&2
  exit 1
fi

mkdir -p "${DATA_HOME}" "${BIN_HOME}" "${APPLICATIONS_HOME}" "${ICON_HOME}"
rm -rf "${APP_HOME}"
cp -a "${SOURCE_APP}" "${APP_HOME}"
install -m 0755 "${PACKAGE_DIR}/uninstall.sh" "${APP_HOME}/uninstall.sh"
install -m 0644 "${PACKAGE_DIR}/app_icon.png" "${ICON_FILE}"

cat > "${EXECUTABLE}" <<EOF
#!/usr/bin/env bash
exec "${APP_HOME}/isaaclab-trace-monitor" "\$@"
EOF
chmod 0755 "${EXECUTABLE}"

cat > "${DESKTOP_FILE}" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=IsaacLab Trace Monitor
Comment=Live and offline monitor for Isaac Lab object trajectory logs
Exec=${EXECUTABLE} %f
TryExec=${EXECUTABLE}
Icon=isaaclab-trace-monitor
Terminal=false
Categories=Development;Science;DataVisualization;
StartupNotify=true
StartupWMClass=isaaclab-trace-monitor
EOF
chmod 0644 "${DESKTOP_FILE}"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${APPLICATIONS_HOME}" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "${DATA_HOME}/icons/hicolor" >/dev/null 2>&1 || true
fi

cat <<EOF
IsaacLab Trace Monitor was installed for the current user.

Executable:
  ${EXECUTABLE}

Desktop entry:
  ${DESKTOP_FILE}

Run it with:
  isaaclab-trace-monitor

Uninstall with:
  ${APP_HOME}/uninstall.sh
EOF
