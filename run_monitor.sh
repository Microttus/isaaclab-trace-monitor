#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
PYPROJECT="${SCRIPT_DIR}/pyproject.toml"
INSTALL_MARKER="${VENV_DIR}/.isaaclab-trace-monitor-pyproject.toml"
PYTHON="${VENV_DIR}/bin/python"
ENTRY_POINT="${VENV_DIR}/bin/isaaclab-trace-monitor"

new_environment=false
if [[ ! -x "${PYTHON}" ]]; then
  rm -rf "${VENV_DIR}"
  python3 -m venv "${VENV_DIR}"
  new_environment=true
fi

if [[ "${new_environment}" == "true" ]]; then
  "${PYTHON}" -m pip install --upgrade pip
fi

if [[ ! -x "${ENTRY_POINT}" ]] || ! cmp -s "${PYPROJECT}" "${INSTALL_MARKER}"; then
  "${PYTHON}" -m pip install -e "${SCRIPT_DIR}"
  cp "${PYPROJECT}" "${INSTALL_MARKER}"
fi

exec "${ENTRY_POINT}" "$@"
