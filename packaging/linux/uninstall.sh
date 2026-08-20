#!/usr/bin/env bash

set -euo pipefail

DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
BIN_HOME="${XDG_BIN_HOME:-${HOME}/.local/bin}"
APP_HOME="${DATA_HOME}/isaaclab-trace-monitor"
APPLICATIONS_HOME="${DATA_HOME}/applications"
ICON_HOME="${DATA_HOME}/icons/hicolor/256x256/apps"

rm -rf "${APP_HOME}"
rm -f \
  "${BIN_HOME}/isaaclab-trace-monitor" \
  "${APPLICATIONS_HOME}/isaaclab-trace-monitor.desktop" \
  "${ICON_HOME}/isaaclab-trace-monitor.png"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${APPLICATIONS_HOME}" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "${DATA_HOME}/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "IsaacLab Trace Monitor was removed for the current user."
