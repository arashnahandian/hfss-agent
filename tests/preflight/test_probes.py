"""W-11's four probes: totality, the three-state metadata read, and the seam.

NO TEST HERE READS THE HOST MACHINE. Every probe that touches the environment is
driven against an ``os.environ`` replaced wholesale with a plain dict, and every
metadata read against a substituted ``importlib.metadata.version``. That is
deliberate and not fastidiousness: a Windows development laptop may carry PyAEDT
and no AEDT while a Linux CI runner carries neither, so a suite that read either
machine would assert different things in the two places and be green in both.
"""

from __future__ import annotations

import ast
import importlib.metadata
import inspect
import os
import platform
from dataclasses import FrozenInstanceError

import pytest

from hfss_agent.preflight.probes import (
    REAL_PROBES,
    WRAPPER_VERSION_FALLBACK,
    EnvironmentProbes,
    VersionRead,
    real_aedt_env_var_names,
    real_pyaedt_version,
    real_python_version,
    real_wrapper_version,
)

# --- the two seam types ------------------------------------------------------


def test_version_read_keeps_absent_and_unreadable_apart() -> None:
    """The reason the type exists: both carry ``version=None``.

    A nullable string could not distinguish them, and the two send a user to
    different fixes — install a missing package, or reinstall a damaged one.
    """
    absent = VersionRead(None, "absent")
    unreadable = VersionRead(None, "unreadable")
    assert absent.version is None and unreadable.version is None
    assert absent != unreadable
    assert absent.state == "absent"
    assert unreadable.state == "unreadable"


def test_version_read_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        VersionRead(None, "absent").version = "1.0.0"  # type: ignore[misc]


def test_environment_probes_requires_every_probe() -> None:
    """No defaults, so a half-substituted set is unconstructible.

    A test that overrode two probes and inherited the host for the other two is
    exactly the failure the seam exists to prevent, so it is made impossible
    rather than discouraged.
    """
    with pytest.raises(TypeError):
        EnvironmentProbes(  # type: ignore[call-arg]
            aedt_env_var_names=frozenset,
            pyaedt_version=lambda: VersionRead("1.2.0", "found"),
        )


def test_environment_probes_is_frozen() -> None:
    probes = EnvironmentProbes(
        aedt_env_var_names=frozenset,
        pyaedt_version=lambda: VersionRead("1.2.0", "found"),
        python_version=lambda: "3.12.10",
        wrapper_version=lambda: "0.3.0",
    )
    with pytest.raises(FrozenInstanceError):
        probes.python_version = lambda: "3.13.0"  # type: ignore[misc]


def test_real_probes_bundles_the_four_real_functions() -> None:
    """The one obvious thing a caller passes — and importing it is visible, which
    is the point of it not being a default."""
    assert REAL_PROBES.aedt_env_var_names is real_aedt_env_var_names
    assert REAL_PROBES.pyaedt_version is real_pyaedt_version
    assert REAL_PROBES.python_version is real_python_version
    assert REAL_PROBES.wrapper_version is real_wrapper_version


# --- the AEDT install scan ---------------------------------------------------


def _environ(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    """Replace ``os.environ`` wholesale, so no host variable can leak in."""
    monkeypatch.setattr(os, "environ", dict(values))


def test_the_scan_is_empty_without_any_install_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty result is the ANSWER for a machine with no AEDT, not a failure.
    That is what makes the ``aedt`` check ``incompatible`` rather than
    ``unavailable``."""
    _environ(monkeypatch, PATH="/usr/bin", HOME="/home/someone")
    assert real_aedt_env_var_names() == frozenset()


def test_the_scan_returns_keys_only_as_a_frozenset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The leak guard, asserted on the type and on the contents.

    The values here are absolute paths — exactly the identifying strings a
    diagnostics bundle must not carry — and none of them appears in the result.
    A probe that cannot return a value cannot leak one.
    """
    _environ(
        monkeypatch,
        ANSYSEM_ROOT261=r"C:\Program Files\AnsysEM\v261\Win64",
        PATH="/usr/bin",
    )
    names = real_aedt_env_var_names()
    assert isinstance(names, frozenset)
    assert names == {"ANSYSEM_ROOT261"}
    assert all("Program Files" not in name for name in names)


def test_the_scan_finds_every_recognised_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _environ(
        monkeypatch,
        ANSYSEM_ROOT261="/opt/a",
        ANSYSEMSV_ROOT251="/opt/b",
        ANSYSEM_PY_CLIENT_ROOT242="/opt/c",
        UNRELATED="/opt/d",
    )
    assert real_aedt_env_var_names() == {
        "ANSYSEM_ROOT261",
        "ANSYSEMSV_ROOT251",
        "ANSYSEM_PY_CLIENT_ROOT242",
    }


def test_the_scan_ignores_names_that_are_not_install_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _environ(
        monkeypatch,
        ANSYSEM_ROOT="/opt/a",
        ANSYSEM_ROOT26="/opt/b",
        ANSYSEM_ROOT2611="/opt/c",
        ansysem_root261="/opt/d",
    )
    assert real_aedt_env_var_names() == frozenset()


def test_an_awp_root_counts_only_with_an_ansysem_subdirectory(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """PyAEDT's own scan requires it, so ours does too.

    Skipping the check would over-report an install PyAEDT will refuse — telling
    a user their environment is ready for an attach that cannot happen.
    """
    (tmp_path / "AnsysEM").mkdir()
    _environ(monkeypatch, AWP_ROOT261=str(tmp_path))
    assert real_aedt_env_var_names() == {"AWP_ROOT261"}


def test_an_awp_root_without_the_subdirectory_is_dropped(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _environ(monkeypatch, AWP_ROOT261=str(tmp_path))
    assert real_aedt_env_var_names() == frozenset()


def test_an_awp_root_with_an_empty_value_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _environ(monkeypatch, AWP_ROOT261="")
    assert real_aedt_env_var_names() == frozenset()


def test_a_broken_awp_root_drops_only_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One bad entry must not hide the good ones beside it."""
    _environ(monkeypatch, AWP_ROOT261="/nonexistent", ANSYSEM_ROOT251="/opt/a")
    assert real_aedt_env_var_names() == {"ANSYSEM_ROOT251"}


def test_the_scan_survives_an_isdir_that_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed root — an embedded null, a path past the OS limit — is not an
    install, and is not a crash either."""

    def raising_isdir(_path: str) -> bool:
        raise OSError("embedded null byte")

    _environ(monkeypatch, AWP_ROOT261="/opt/broken", ANSYSEM_ROOT251="/opt/a")
    monkeypatch.setattr(os.path, "isdir", raising_isdir)
    assert real_aedt_env_var_names() == {"ANSYSEM_ROOT251"}


def test_the_scan_survives_an_environ_that_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole-probe backstop (ADR-26 decision 18(a)).

    Per-variable failures are already handled; this is the case where the
    mapping itself is hostile. The probe degrades to "no install roots found" —
    the same answer a clean machine without AEDT gives — because the response
    this feeds has no ``cannot_evaluate`` arm, so a raise would surface as a
    traceback on the first tool of Journey 1.0.
    """

    # A dict subclass, not a bare object: pytest's own machinery reads
    # ``os.environ.get`` while this patch is live, so the mapping stays usable
    # everywhere except the one operation the probe performs.
    class HostileEnviron(dict):
        def __iter__(self):
            raise RuntimeError("environ is unreadable")

    monkeypatch.setattr(os, "environ", HostileEnviron())
    assert real_aedt_env_var_names() == frozenset()


# --- the metadata probes -----------------------------------------------------


def _version_raises(monkeypatch: pytest.MonkeyPatch, error: BaseException) -> None:
    def raising(_distribution: str) -> str:
        raise error

    monkeypatch.setattr(importlib.metadata, "version", raising)


def _version_returns(monkeypatch: pytest.MonkeyPatch, value: object) -> None:
    monkeypatch.setattr(importlib.metadata, "version", lambda _d: value)


def test_pyaedt_probe_reports_a_found_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _version_returns(monkeypatch, "1.2.0")
    assert real_pyaedt_version() == VersionRead("1.2.0", "found")


def test_pyaedt_probe_reports_absent_when_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ORDINARY case in this project's own CI: both OS legs run ``uv sync``
    without the ``live`` extra, so PyAEDT is genuinely not installed there."""
    _version_raises(monkeypatch, importlib.metadata.PackageNotFoundError("pyaedt"))
    assert real_pyaedt_version() == VersionRead(None, "absent")


def test_pyaedt_probe_reports_unreadable_when_metadata_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``importlib.metadata.version()`` RETURNS None — it does not raise — when a
    ``.dist-info`` has no ``Version:`` field or no ``METADATA`` file.

    This is the case an ``except`` alone cannot catch, and the reason the probes
    check ``is None`` as well (ADR-26 decision 18(b)). The shipped adapter's
    equivalent read misses exactly this.
    """
    _version_returns(monkeypatch, None)
    assert real_pyaedt_version() == VersionRead(None, "unreadable")


def test_pyaedt_probe_reports_unreadable_when_metadata_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anything that is not ``PackageNotFoundError`` is "present but not
    readable", never "not installed"."""
    _version_raises(monkeypatch, RuntimeError("broken finder on sys.meta_path"))
    assert real_pyaedt_version() == VersionRead(None, "unreadable")


@pytest.mark.parametrize(
    "failure",
    ["absent", "none", "raises"],
)
def test_wrapper_probe_falls_back_rather_than_failing(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Always a string, because the contract's ``wrapper_version`` has no absent
    state and needs none — this code is running, so a wrapper exists.

    The three-state read still runs underneath; nothing consumes the
    distinction, because the wrapper is not one of the six checked components.
    """
    if failure == "absent":
        _version_raises(
            monkeypatch, importlib.metadata.PackageNotFoundError("hfss-agent")
        )
    elif failure == "none":
        _version_returns(monkeypatch, None)
    else:
        _version_raises(monkeypatch, RuntimeError("unreadable metadata directory"))
    assert real_wrapper_version() == WRAPPER_VERSION_FALLBACK


def test_wrapper_probe_reports_a_real_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _version_returns(monkeypatch, "0.3.0")
    assert real_wrapper_version() == "0.3.0"


# --- the version shape check -------------------------------------------------


@pytest.mark.parametrize(
    ("hostile", "why"),
    [
        ("1.2.0\nS 2 5.0 0.0", "a newline forging a second rendered line"),
        ("1.2.0\r\nVersion: 9.9.9", "a carriage return and a fake field"),
        ("1.2.0\tinjected", "a tab"),
        ("1.2.0; rm -rf /", "shell metacharacters"),
        ("1.2.0 $(whoami)", "command substitution"),
        ("1.2.0" + "9" * 200, "over-long"),
        ("1.2.0\x00", "an embedded null"),
        ("<script>alert(1)</script>", "markup"),
    ],
)
def test_a_hostile_version_string_reads_as_unreadable(
    monkeypatch: pytest.MonkeyPatch, hostile: str, why: str
) -> None:
    """``importlib.metadata`` returns whatever a ``.dist-info`` holds, which this
    package did not write — the one place foreign bytes can enter W-11.

    Constrained AT THE PROBE rather than at the renderer: W-11 renders no
    ``UntrustedStr`` (an AEDT version is rebuilt from two integers, and the
    contract types all four ``Environment`` version fields as plain ``str``), so
    guarding the text would invent a third rendering pattern for what is really
    an input problem. Reporting ``unreadable`` is not a loss of information —
    it is the accurate description of metadata that cannot be turned into a
    version.
    """
    _version_returns(monkeypatch, hostile)
    assert real_pyaedt_version() == VersionRead(None, "unreadable"), why


@pytest.mark.parametrize(
    "legitimate",
    ["1.2.0", "0.3.0", "1.3.0rc1", "1.2.0.post1", "1.2.0+local.1", "1!2.0", "2026.1"],
)
def test_a_legitimate_version_string_reads_as_found(
    monkeypatch: pytest.MonkeyPatch, legitimate: str
) -> None:
    """The check must not cost real versions. PEP 440's alphabet passes whole,
    including epochs, local versions and pre-releases."""
    _version_returns(monkeypatch, legitimate)
    assert real_pyaedt_version() == VersionRead(legitimate, "found")


# --- the interpreter probe ---------------------------------------------------


def test_python_probe_reports_the_running_interpreter() -> None:
    assert real_python_version() == platform.python_version()


def test_python_probe_is_deliberately_unwrapped() -> None:
    """Pins the DECISION, not just the behaviour (ADR-26 decision 18(a)).

    "None raises" reads universal, and this probe is the one exception, so the
    reasoning is pinned where a future maintainer "restoring consistency" will
    trip over it: ``platform.python_version()`` formats ``sys.version_info``,
    which the interpreter always has because it IS the interpreter. There is no
    failure mode to catch, and a ``try`` would need a fallback — which could
    only be a FABRICATED VERSION reported as a measured one. That is strictly
    worse than the crash it would prevent, because a crash is visible and a
    wrong version string is not.
    """
    tree = ast.parse(inspect.getsource(real_python_version))
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Try)]


def test_the_real_probes_hold_the_version_read_invariant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``version is not None`` exactly when ``state == "found"``.

    Held by the construction sites rather than by a validator, deliberately: a
    raising ``__post_init__`` would be reachable from inside a probe, and a
    probe that can raise is not total. So the invariant is pinned here instead,
    across every state the real read can produce.
    """
    cases: list[VersionRead] = []
    _version_returns(monkeypatch, "1.2.0")
    cases.append(real_pyaedt_version())
    _version_returns(monkeypatch, None)
    cases.append(real_pyaedt_version())
    _version_raises(monkeypatch, importlib.metadata.PackageNotFoundError("pyaedt"))
    cases.append(real_pyaedt_version())
    _version_returns(monkeypatch, "1.2.0\nbad")
    cases.append(real_pyaedt_version())

    assert {case.state for case in cases} == {"found", "unreadable", "absent"}
    for case in cases:
        assert (case.version is not None) == (case.state == "found")
