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
    assert __version__ == "1.2.0"
