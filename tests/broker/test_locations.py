"""Default data-directory resolution (plan §6e). The WHY (OneDrive Known
Folder Move never covers LocalAppData; Roaming syncs under domain profiles)
lives in the module docstring; these tests pin the resolved shapes. Each CI
leg exercises its own platform branch."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hfss_agent.broker.files import (
    default_data_dir,
    default_intent_path,
    ensure_data_dir,
)


def _set_platform_base(monkeypatch: pytest.MonkeyPatch, base: Path) -> None:
    if os.name == "nt":
        monkeypatch.setenv("LOCALAPPDATA", str(base))
    else:
        monkeypatch.setenv("XDG_STATE_HOME", str(base))


def test_default_data_dir_honors_the_platform_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _set_platform_base(monkeypatch, tmp_path)
    assert default_data_dir() == os.path.join(str(tmp_path), "hfss-agent")


def test_default_data_dir_never_resolves_to_roaming() -> None:
    # APPDATA (Roaming) is the domain-roaming sync hazard the docstring names.
    path = default_data_dir()
    assert path.endswith("hfss-agent")
    assert f"{os.sep}Roaming{os.sep}" not in path


def test_ensure_data_dir_creates_the_brokers_own_directory(
    tmp_path: Path,
) -> None:
    target = str(tmp_path / "state" / "hfss-agent")
    assert ensure_data_dir(target) == target
    assert os.path.isdir(target)


def test_default_intent_path_sits_inside_an_ensured_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _set_platform_base(monkeypatch, tmp_path)
    path = default_intent_path()
    assert path == os.path.join(str(tmp_path), "hfss-agent", "intent.json")
    assert os.path.isdir(os.path.dirname(path))
