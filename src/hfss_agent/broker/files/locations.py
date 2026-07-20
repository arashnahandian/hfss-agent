"""Default on-disk locations for broker-owned files (W-4; plan §6e).

Windows resolves to ``%LOCALAPPDATA%\\hfss-agent\\``; everything else to
``$XDG_STATE_HOME/hfss-agent/``, falling back to ``~/.local/state/hfss-agent/``
(state, not config — the audit log and intent file are state). No
``platformdirs`` dependency: new dependencies are deliberate events in this
repo, and the resolution is two branches.

WHY LocalAppData: OneDrive Known Folder Move syncs Desktop/Documents/Pictures
but never LocalAppData, and cloud sync corrupts append-only files and atomic
replaces (the CLAUDE.md OneDrive rule, applied to our own data). APPDATA
(Roaming) is excluded from the other direction: domain roaming profiles sync
it — the same corruption class. If ``LOCALAPPDATA`` is unset (rare), the
resolver falls back to its documented default location under the user profile.

``os.makedirs(exist_ok=True)`` appears HERE AND NOWHERE ELSE in the repo: the
broker may create its OWN data directory, never a user's — a missing export
parent is a typed refusal in ``paths.py``, not a silent mkdir. Tests and Step
2.8 composition inject explicit paths into the file-layer collaborators (e.g.
``IntentStore(str(tmp_path / "intent.json"))``) rather than resolving these
defaults.
"""

from __future__ import annotations

import os


def default_data_dir() -> str:
    """The broker's default data directory for this platform (not created)."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(
            r"~\AppData\Local"
        )
        return os.path.join(base, "hfss-agent")
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "hfss-agent")


def ensure_data_dir(data_dir: str | None = None) -> str:
    """Create (if needed) and return the broker's OWN data directory — the one
    permitted ``makedirs`` site in the repo (module docstring)."""
    path = data_dir if data_dir is not None else default_data_dir()
    os.makedirs(path, exist_ok=True)
    return path


def default_intent_path(data_dir: str | None = None) -> str:
    """The default intent-file path, with its directory ensured."""
    return os.path.join(ensure_data_dir(data_dir), "intent.json")


def default_audit_log_path(data_dir: str | None = None) -> str:
    """The default audit-log path, with its directory ensured."""
    return os.path.join(ensure_data_dir(data_dir), "audit-log.jsonl")
