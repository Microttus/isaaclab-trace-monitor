# Security policy

## Supported version

Security fixes are applied to the newest released version.

## Reporting a vulnerability

Do not report credentials, command-injection details, or other sensitive
security information in a public issue.

Use GitHub private vulnerability reporting for this repository. If that feature
is unavailable, open a minimal public issue asking the maintainer to establish
a private reporting channel; do not include exploit details in that issue.

Include:

- application version;
- operating system;
- whether the source was local or remote;
- minimal reproduction steps;
- expected impact; and
- sanitized logs with hostnames, usernames, paths, and credentials removed.

## Remote-source model

The application invokes `rsync` directly through Qt's process API, without a
local shell. Remote source syntax is constrained, and an end-of-options marker
is inserted before source and destination arguments. Users must still treat SSH
configuration, remote hosts, and trace files as trusted administrative inputs.
