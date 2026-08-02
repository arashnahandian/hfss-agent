"""The narrow ``os`` surface audit (W-11): "preflight may import os" must not
silently mean "preflight may do anything os can do".

WHY THIS FILE EXISTS, stated first because the gap it closes is invisible from
either of the audits it sits beside:

  * the module-wide import audits constrain ``hfss_agent.*`` roots and say
    NOTHING about the standard library;
  * the file-I/O audit (``test_file_io_audit.py``) explicitly permits
    ``import os`` — its own self-test pins ``_io_violations("import os") == []``
    — because its denylist targets file CONTENT and NAMESPACE mutation, and it
    deliberately allows metadata-only reads so ``paths.py``'s parent-directory
    check stays legal.

Both decisions are right for their own scope, and together they leave
``probes.py`` holding an unbounded ``os``. ``os.getcwd``, ``os.listdir``,
``os.walk``, ``os.scandir``, ``os.getlogin``, ``os.environ`` wholesale — none of
these is file I/O under that audit's definition, and none is an ``hfss_agent``
import. Every one of them would leak machine state into a module whose entire
contract is that it returns install-root NAMES and nothing else.

So this audit is an ALLOW-LIST over attribute access, derived from what the code
actually uses, and widening it is a reviewable edit to this file rather than a
line someone adds in passing.

DERIVED FROM THE CODE, NOT TRANSCRIBED FROM A PLAN. The build-progress note
that scheduled this check proposed ``{environ, name, path, sep}`` for ``os`` and
``{expanduser}`` for ``os.path``. Both were wrong when checked against the
source: preflight uses ``os.environ`` and ``os.path`` only, and under
``os.path`` it uses ``isdir`` and ``join`` — ``name``, ``sep`` and
``expanduser`` appear nowhere in the package. (``expanduser`` belongs to
``broker/files/locations.py``, which is not preflight.) Pre-authorising three
attributes nothing uses would defeat the purpose: an allow-list is only as good
as its narrowness, and every unused entry is a permission granted without a
reason.

WHAT THIS DOES NOT COVER, stated so the guarantee is not overread: a bare
``import os`` followed by ``getattr(os, name)`` would evade an AST attribute
check. That is not a gap worth closing here — this repo forbids arbitrary
execution outright, and a dynamic attribute lookup on ``os`` in a module whose
subject is machine-state discipline would fail review long before it failed a
test.
"""

from __future__ import annotations

import ast
from pathlib import Path

_PREFLIGHT = Path(__file__).resolve().parents[2] / "src" / "hfss_agent" / "preflight"

# Every ``os.<attr>`` preflight may name. Derived from ``probes.py``:
#
#   environ — the install-root scan, which reads KEYS and returns only names;
#   path    — the namespace under which the two calls below live.
#
# ``os.environ`` is the widest entry here and it is the one that matters most.
# It is permitted because the scan must enumerate variable names; what keeps it
# safe is not this audit but ``probes.real_aedt_env_var_names``, which returns a
# ``frozenset[str]`` of NAMES and never a value. This list stops a second,
# unreviewed reader of the environment appearing elsewhere.
_ALLOWED_OS_ATTRS = frozenset({"environ", "path"})

# Every ``os.path.<attr>`` preflight may name. Derived from ``probes.py``:
#
#   isdir — the AWP_ROOT AnsysEM-subdirectory check, a metadata-only read the
#           file-I/O audit self-tests as legal;
#   join  — building the path that check looks at.
#
# Notably ABSENT and deliberately so: ``exists``. PyAEDT's own scan uses
# ``Path(...).exists()``, and W-11 chose ``isdir`` instead — a known divergence
# recorded in ``docs/pyaedt-coverage.md`` as a live-pass question. If a future
# edit switches to ``exists`` to match PyAEDT, this audit fails, which is
# correct: that is a decision with a recorded rationale, not a refactor.
_ALLOWED_OS_PATH_ATTRS = frozenset({"isdir", "join"})

# ``from os import X`` and ``from os.path import X`` bypass attribute access
# entirely, so the same allow-lists are applied to imported names.
_OS_MODULES = {"os": _ALLOWED_OS_ATTRS, "os.path": _ALLOWED_OS_PATH_ATTRS}


def _preflight_sources() -> list[Path]:
    files = sorted(_PREFLIGHT.rglob("*.py"))
    assert files, f"no preflight source files found under {_PREFLIGHT}"
    return files


def _is_os_path(node: ast.expr) -> bool:
    """True for the ``os.path`` expression itself."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "path"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def os_surface_violations(source: str) -> list[str]:
    """Every ``os`` attribute or imported name outside the allow-lists.

    Checked in the order most-specific-first: ``os.path.isdir`` must be judged
    against the ``os.path`` list, not the ``os`` one, and the outer ``os.path``
    node it contains is judged separately (and permitted, since ``path`` is on
    the ``os`` list).
    """
    out: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute):
            if _is_os_path(node.value) and node.attr not in _ALLOWED_OS_PATH_ATTRS:
                out.append(f"os.path.{node.attr}")
            elif (
                isinstance(node.value, ast.Name)
                and node.value.id == "os"
                and node.attr not in _ALLOWED_OS_ATTRS
            ):
                out.append(f"os.{node.attr}")
        elif isinstance(node, ast.ImportFrom) and node.module in _OS_MODULES:
            allowed = _OS_MODULES[node.module]
            out += [
                f"from {node.module} import {alias.name}"
                for alias in node.names
                if alias.name not in allowed
            ]
    return out


def test_preflight_names_only_the_allowed_os_surface() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _preflight_sources():
        violations = os_surface_violations(path.read_text(encoding="utf-8"))
        if violations:
            offenders[path.name] = violations
    assert not offenders, (
        "preflight reached os attributes outside the allow-list — widening it "
        f"is an edit to this file, not a line added in passing: {offenders}"
    )


def test_the_allow_lists_match_what_the_code_actually_uses() -> None:
    """No entry is granted without a use, in either direction.

    An allow-list that permits more than the code needs has stopped being a
    boundary and become a wish list — every unused entry is a permission granted
    without a reason, and the next reader cannot tell which entries were decided
    and which were copied from a draft. This is the check that would have caught
    ``name``, ``sep`` and ``expanduser`` being carried over from the plan.
    """
    used_os: set[str] = set()
    used_os_path: set[str] = set()
    for path in _preflight_sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Attribute):
                continue
            if _is_os_path(node.value):
                used_os_path.add(node.attr)
            elif isinstance(node.value, ast.Name) and node.value.id == "os":
                used_os.add(node.attr)
    assert used_os == _ALLOWED_OS_ATTRS, (
        f"os attributes used {sorted(used_os)} but allowed {sorted(_ALLOWED_OS_ATTRS)}"
    )
    assert used_os_path == _ALLOWED_OS_PATH_ATTRS, (
        f"os.path attributes used {sorted(used_os_path)} but allowed "
        f"{sorted(_ALLOWED_OS_PATH_ATTRS)}"
    )


def test_the_audit_catches_the_reads_that_are_not_file_io() -> None:
    """The negative control, in memory: every one of these is invisible to BOTH
    neighbouring audits.

    None is an ``hfss_agent`` import, so the module-wide audit cannot see it;
    none opens, writes, deletes or renames, so the file-I/O audit permits it by
    its own stated definition. They are exactly the machine-state leaks this
    file exists to stop.
    """
    for planted, expected in (
        ("os.getcwd()", "os.getcwd"),
        ("os.listdir(p)", "os.listdir"),
        ("os.scandir(p)", "os.scandir"),
        ("os.walk(p)", "os.walk"),
        ("os.getlogin()", "os.getlogin"),
        ("os.uname()", "os.uname"),
        ("os.get_exec_path()", "os.get_exec_path"),
        ("os.path.expanduser(p)", "os.path.expanduser"),
        ("os.path.realpath(p)", "os.path.realpath"),
        ("os.path.abspath(p)", "os.path.abspath"),
    ):
        assert os_surface_violations(planted) == [expected], planted


def test_the_audit_catches_the_from_import_bypass() -> None:
    """``from os import getcwd`` never produces an ``os.<attr>`` node, so the
    attribute check alone would miss it entirely."""
    assert os_surface_violations("from os import getcwd") == [
        "from os import getcwd"
    ]
    assert os_surface_violations("from os.path import expanduser") == [
        "from os.path import expanduser"
    ]
    # The allowed names must still pass through the same door.
    assert os_surface_violations("from os import environ") == []
    assert os_surface_violations("from os.path import isdir, join") == []


def test_the_audit_permits_exactly_what_probes_does() -> None:
    """Green on the real idioms, so the guard is not merely strict."""
    assert os_surface_violations("os.environ.get(name)") == []
    assert os_surface_violations("for name in os.environ: pass") == []
    assert os_surface_violations("os.path.isdir(os.path.join(root, 'AnsysEM'))") == []
    # A local variable named ``os`` is not the module, but the audit cannot tell
    # them apart and would flag it. Pinned as accepted over-breadth, following
    # the file-I/O audit's own ``.replace`` precedent: if a preflight file ever
    # legitimately needs a variable named ``os``, this audit will say so loudly
    # and the exemption becomes a reviewable decision.
    assert os_surface_violations("os = Thing()\nos.getcwd()") == ["os.getcwd"]
