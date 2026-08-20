# Live monitoring over Coder SSH

The desktop application does not connect to Isaac Sim. It periodically copies
the bounded logger output from the training host and redraws the newest local
copy.

## Prerequisites

On the macOS or Linux monitoring computer:

- Python 3.10-3.14 for source execution, or a platform bundle
- `rsync`
- OpenSSH
- the Coder CLI when the SSH configuration uses it as a proxy command
- non-interactive SSH authentication

On Ubuntu/Debian, the repository helper installs the required desktop and
network tools:

```bash
./install_linux_dependencies.sh
```

Configure Coder SSH:

```bash
coder login https://coder.example.com
coder config-ssh --no-wildcard
ssh coder.<workspace> true
```

## Source syntax

Enter:

```text
coder.<workspace>:/absolute/path/to/object_traces
```

or:

```text
ssh://user@host/absolute/path/to/object_traces
```

For safety and predictable cross-platform handling, remote paths must be
absolute and may not contain whitespace or shell metacharacters.

## Restrictive synchronization

The default transfer excludes `episodes/` and retrieves only the files needed
for the live display. Enable **Sync retained episodes** only when historical
remote episode playback is required.

The cache is disposable. Removing it does not alter server files. `rsync`
receives `--delete`, so local cache files that no longer exist in the selected
remote subtree are removed.

Default cache roots:

```text
macOS: ~/Library/Caches/IsaacLabTraceMonitor/
Linux: ${XDG_CACHE_HOME:-~/.cache}/isaaclab-trace-monitor/
```

## Troubleshooting

Check the host alias:

```bash
ssh coder.<workspace> true
```

Check the log path:

```bash
ssh coder.<workspace> \
  'ls /absolute/path/to/object_traces/live/status.json'
```

Test the same bounded transfer manually on Linux:

```bash
rsync -az --delete --exclude episodes/ -- \
  coder.<workspace>:/absolute/path/to/object_traces/ \
  "${XDG_CACHE_HOME:-$HOME/.cache}/isaaclab-trace-monitor/manual-test/"
```

On macOS, use:

```bash
rsync -az --delete --exclude episodes/ -- \
  coder.<workspace>:/absolute/path/to/object_traces/ \
  "$HOME/Library/Caches/IsaacLabTraceMonitor/manual-test/"
```

Run the application diagnostics:

```bash
isaaclab-trace-monitor --diagnose
```

When a Finder-launched macOS application can open local files but cannot
synchronize, verify that the Coder CLI is installed in `/opt/homebrew/bin`,
`/usr/local/bin`, `~/.local/bin`, or `~/bin`. The monitor adds these locations,
plus normal Linux system paths, to the child-process environment.
