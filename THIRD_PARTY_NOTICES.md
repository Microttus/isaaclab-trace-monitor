# Third-party notices

IsaacLab Trace Monitor depends on third-party open-source software. Those
components remain subject to their own licenses and copyright notices.

Runtime dependencies include:

- PySide6 / Qt for Python and its Qt components;
- shiboken6;
- Matplotlib; and
- NumPy.

The macOS build process additionally uses:

- PyInstaller; and
- Pillow.

The source repository does not replace or modify the licenses of these
projects. The macOS build script runs `tools/collect_licenses.py` and copies the
license and notice files available from the installed Python distributions into
`IsaacLab Trace Monitor.app/Contents/Resources/licenses/`.

Review the collected files before publishing a binary release. A missing file
in that directory does not remove the obligation to comply with the relevant
third-party license.
