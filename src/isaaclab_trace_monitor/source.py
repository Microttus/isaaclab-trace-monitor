"""Local and SSH/rsync source handling for the trace monitor."""

from __future__ import annotations

import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

_REMOTE_RE = re.compile(r"^(?P<host>(?:[^/@:]+@)?[^/:]+):(?P<path>/.*)$")
_HOST_RE = re.compile(r"^(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9._-]+$")
_REMOTE_PATH_RE = re.compile(r"^/[A-Za-z0-9._~+/@%=-]*$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class SourceSpec:
    """A local trace source or an rsync-compatible SSH source."""

    raw: str
    remote: bool
    local_path: Path | None = None
    remote_host: str | None = None
    remote_path: str | None = None

    @classmethod
    def parse(cls, value: str) -> "SourceSpec":
        """Parse local paths, ``host:/path``, and ``ssh://host/path`` syntax."""
        raw = value.strip()
        if not raw:
            raise ValueError("Enter a source folder.")
        if _CONTROL_RE.search(raw):
            raise ValueError("Source contains control characters.")

        if raw.startswith("ssh://"):
            parsed = urlparse(raw)
            if (
                parsed.scheme != "ssh"
                or not parsed.hostname
                or not parsed.path
                or parsed.password is not None
                or parsed.port is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "SSH sources must use ssh://[user@]host/absolute/path without "
                    "passwords, ports, queries, or fragments."
                )
            host = parsed.hostname
            if parsed.username:
                host = f"{parsed.username}@{host}"
            cls._validate_remote(host, parsed.path)
            return cls(
                raw=raw,
                remote=True,
                remote_host=host,
                remote_path=parsed.path,
            )

        match = _REMOTE_RE.match(raw)
        if match:
            host = match.group("host")
            path = match.group("path")
            cls._validate_remote(host, path)
            return cls(
                raw=raw,
                remote=True,
                remote_host=host,
                remote_path=path,
            )

        return cls(raw=raw, remote=False, local_path=Path(raw).expanduser())

    @staticmethod
    def _validate_remote(host: str, path: str) -> None:
        """Validate the constrained remote syntax accepted by the application."""
        if host.startswith("-") or "@-" in host or not _HOST_RE.fullmatch(host):
            raise ValueError(
                "Remote host must contain only letters, digits, '.', '_', '-', and "
                "an optional user@ prefix."
            )
        if not _REMOTE_PATH_RE.fullmatch(path):
            raise ValueError(
                "Remote path must be absolute and contain no spaces or shell "
                "metacharacters. Supported characters are letters, digits, '/', "
                "'.', '_', '-', '~', '+', '@', '%', and '='."
            )

    def rsync_source(self) -> str:
        """Return the normalized remote folder argument for rsync."""
        if not self.remote or not self.remote_host or not self.remote_path:
            raise ValueError("Source is not remote")
        return f"{self.remote_host}:{self.remote_path.rstrip('/')}/"


def default_cache_root() -> Path:
    """Return a platform-appropriate application cache directory."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "IsaacLabTraceMonitor"
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "IsaacLabTraceMonitor" / "Cache"
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "isaaclab-trace-monitor"


def cache_directory(source: SourceSpec) -> Path:
    """Return a stable cache directory for a remote source."""
    digest = hashlib.sha256(source.raw.encode("utf-8")).hexdigest()[:16]
    return default_cache_root() / digest


def rsync_arguments(
    source: SourceSpec, cache: Path, include_episodes: bool
) -> list[str]:
    """Build bounded live-sync arguments for rsync."""
    arguments = [
        "-az",
        "--delete",
        "--timeout=20",
    ]
    if not include_episodes:
        arguments.extend(("--exclude", "episodes/"))
    arguments.append("--")
    arguments.extend((source.rsync_source(), f"{cache.resolve()}/"))
    return arguments
