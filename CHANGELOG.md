# Changelog

All notable changes to this project are documented in this file.

## 1.2.0 - 2026-08-20

- Prepared the project as a public GitHub source repository.
- Added BSD-3-Clause licensing, citation metadata, security and contribution
  policies, third-party notices, and a publication checklist.
- Added an explicit ChatGPT development-assistance disclosure in the README,
  a dedicated disclosure file, and the application's About dialog.
- Added the generic Isaac Lab/Stable-Baselines3 bounded trace logger and a
  focused integration example.
- Added trace-format, Coder live-monitoring, and macOS build documentation.
- Hardened remote source validation and inserted an `rsync` end-of-options
  separator.
- Replaced affiliation-like application settings and bundle identifiers with
  independent project identifiers.
- Added GitHub Actions CI, Dependabot configuration, and issue templates.
- Added build-time collection of available third-party license files.
- Made package version reporting derive from installed metadata and made the
  macOS build derive its version from `pyproject.toml`.

## 1.1.0 - 2026-07-13

- Added a custom trajectory application icon for the macOS bundle, Dock,
  application switcher, and Qt windows.
- Moved PyInstaller work files to a temporary directory that is removed after a
  successful build.
- Added validation of the final `.app`, embedded Python runtime, property list,
  and ad-hoc code signature.
- Added creation of a drag-to-install `.dmg` and a symlink-preserving `.zip`.
- Documented that PyInstaller's work-directory `.pkg` file is an internal
  archive rather than an Apple Installer package.
- Added application and package version reporting with `--version`.
