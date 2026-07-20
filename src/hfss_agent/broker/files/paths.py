"""Validation for USER-SUPPLIED export paths (W-4; ADR-8; plan §6c).

This module guards exactly one input class: the ``path`` a caller passes to an
export. The intent and audit paths are broker configuration and are never
user- or HFSS-derived — which is how ADR-9's "no tool ever derives a write
path from HFSS-sourced strings" is upheld STRUCTURALLY here: the only
free-form path on the whole file surface is validated below, and the rest are
constants chosen at composition time.

Refused, each with a typed reason naming the specific cause:
  * relative paths (``os.path.isabs`` also correctly rejects Windows
    drive-relative forms like ``C:foo``) — the server's working directory is
    opaque to the user, so a relative export would land somewhere surprising;
  * UNC / network-looking paths (``\\\\server\\share\\...`` and the
    forward-slash spelling) — MVP zero-egress policy: a write to a network
    share is bytes leaving the machine. Deliberately easy to loosen later:
    one predicate, one test;
  * Windows reserved device names, checked on EVERY component and on BOTH
    OSes (a Linux-written bundle may travel to Windows). Implemented
    explicitly, not via ``PurePath.is_reserved()`` (deprecated in 3.13,
    historically incomplete);
  * trailing dots or spaces in any component (Windows strips them silently,
    which aliases two spellings onto one file);
  * a missing parent directory — refused, naming the parent, never created:
    silently creating a directory tree is a small silent write.

Accepted and documented, NOT enforced:
  * case-insensitive collisions — NTFS makes ``Report.s2p`` and
    ``report.s2p`` one file and ext4 does not; we do not emulate NTFS on
    Linux (the ``"x"``-mode guard in ``writes.py`` already refuses
    case-insensitively where the filesystem does);
  * path length — no 260-char cap and no ``\\\\?\\`` prefixing: MAX_PATH is
    off by default on Windows 10 and commonly lifted on Windows 11 (both in
    use on this project), so we attempt the write and surface the OS error as
    a typed failure naming the real cause;
  * Windows alternate data streams — a path like ``C:\\out\\file.s2p:hidden``
    writes invisible content and is not covered by the reserved-name or
    trailing-character checks. Deliberately NOT refused: the user supplied
    the path and the effect is confined to their own directory — recorded so
    the list of what validation does not cover stays complete.
"""

from __future__ import annotations

import os
import re

from hfss_agent.broker.files.errors import BrokerFileError

# The classic reserved set (plan §6c): CON, PRN, AUX, NUL, COM1-9, LPT1-9 —
# reserved with or without an extension, case-insensitively.
_RESERVED_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{digit}" for digit in "123456789"}
    | {f"LPT{digit}" for digit in "123456789"}
)

# A drive designator ("C:") split out of a Windows absolute path — not a real
# component, so it is skipped by the per-component checks.
_DRIVE_ONLY = re.compile(r"^[A-Za-z]:$")


def _components(path: str) -> list[str]:
    """The path's components under either separator, minus drive designators."""
    parts = re.split(r"[\\/]+", path)
    return [part for part in parts if part and not _DRIVE_ONLY.match(part)]


def validate_export_path(path: str) -> None:
    """Refuse an invalid user-supplied export path with a specific, typed
    reason (module docstring); return None when the path is acceptable.

    Check order matters cross-platform: UNC is tested BEFORE absoluteness
    because on POSIX a backslash UNC spelling is not absolute and would
    otherwise be refused with the wrong (relative-path) reason.
    """
    if path.startswith(("\\\\", "//")):
        raise BrokerFileError(
            path,
            "UNC/network paths are refused (zero-egress MVP policy: a write "
            "to a network share is bytes leaving the machine)",
        )
    if not os.path.isabs(path):
        raise BrokerFileError(
            path,
            "the path is not absolute; relative paths are refused because "
            "the server's working directory is opaque to the user",
        )
    for component in _components(path):
        stem = component.split(".", 1)[0].rstrip(". ").upper()
        if stem in _RESERVED_DEVICE_NAMES:
            raise BrokerFileError(
                path,
                f"path component '{component}' is a Windows reserved device "
                "name (refused on every platform: an exported file may "
                "travel to Windows)",
            )
        if component != component.rstrip(". "):
            raise BrokerFileError(
                path,
                f"path component '{component}' ends with a dot or space, "
                "which Windows strips silently (path aliasing)",
            )
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        raise BrokerFileError(
            path,
            f"the parent directory '{parent}' does not exist; it will not be "
            "created on your behalf — create it explicitly and retry",
        )
