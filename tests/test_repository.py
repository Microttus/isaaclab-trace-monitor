from __future__ import annotations

from pathlib import Path

from isaaclab_trace_monitor import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_public_disclosures_are_present() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    disclosure = (ROOT / "AI_ASSISTANCE.md").read_text(encoding="utf-8")
    assert "OpenAI's ChatGPT" in readme
    assert "substantial assistance" in disclosure
    assert "does not use an OpenAI API at runtime" in disclosure


def test_source_version_matches_release() -> None:
    assert __version__ == "1.3.0"


def test_linux_support_files_are_present() -> None:
    expected = (
        "build_linux_app.sh",
        "install_linux_dependencies.sh",
        "docs/building-linux.md",
        ".github/workflows/linux-bundle.yml",
        "packaging/linux/install.sh",
        "packaging/linux/uninstall.sh",
    )
    for relative_path in expected:
        assert (ROOT / relative_path).is_file(), relative_path


def test_linux_dependency_and_cli_configuration() -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"PySide6-Essentials>=6.8.2,<7"' in project
    assert (
        'isaaclab-trace-monitor = "isaaclab_trace_monitor.cli:main"' in project
    )

    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "install_linux_dependencies.sh" in workflow
    assert "xvfb-run" in workflow
