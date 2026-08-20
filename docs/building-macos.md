# Building the macOS application

## Local build

Use a native Python interpreter for the desired architecture:

```bash
PYTHON_BIN=/opt/homebrew/bin/python3 ./build_macos_app.sh
```

The script creates a fresh `.venv-build`, installs the project and build extras,
and writes finished products below `dist/`.

Do not run files from a PyInstaller work directory. Only these are finished
artifacts:

```text
dist/IsaacLab Trace Monitor.app
dist/IsaacLab-Trace-Monitor-<version>-macOS.dmg
dist/IsaacLab-Trace-Monitor-<version>-macOS.zip
```

## Bundle identifier

The default is:

```text
org.isaaclabtracemonitor.desktop
```

Override it for your public namespace:

```bash
BUNDLE_ID=io.github.youruser.isaaclabtracemonitor \
  ./build_macos_app.sh
```

## Signing

The default build applies an ad-hoc signature for local use. This is not a
Developer ID signature and is not notarized.

For a public binary release, configure a Developer ID signing identity and
notarization in a separate release workflow. Do not commit certificates,
private keys, App Store Connect credentials, or notarization passwords.

## Third-party notices

The build executes `tools/collect_licenses.py` after dependency installation.
The discovered license and notice files are copied to:

```text
IsaacLab Trace Monitor.app/Contents/Resources/licenses/
```

Review that directory before distributing the binary.
