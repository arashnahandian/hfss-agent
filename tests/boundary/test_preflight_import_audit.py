"""Layer-4 import audit (W-11): the preflight module imports only ``broker`` and
``contract`` (and its own submodules) — never pyaedt, never session or adapter,
never server or any Layer-5+ unit — and every file EXCEPT ``probes.py`` reaches
no machine state at all.

System Design §5 places preflight at Layer 4 (preflight -> broker, contract;
anything unlisted is prohibited), and §4 homes import audits in this
``tests/boundary/`` suite. Parse each glob-discovered source file's imports
statically (AST, no exec) — the approach that can assert imports are *only* the
allowed roots, not merely that a denylisted module is absent. No new mechanism
is introduced; the four Layer-4 audits must stay comparable line for line,
because the day they diverge is the day nobody can tell whether a difference is
a decision or a drift.

FOLLOWS W-7's TEMPLATE, NOT W-6's, AND THE CHOICE IS SUBSTANTIVE. W-6's audit is
module-wide only, because every part of ``validate_native`` is assembly and there
is no inner boundary to protect. W-7's adds a per-file check because §5's Layer-4
line for metrics carries a parenthetical — "(formulas themselves: pure)" — naming
an inner constraint the module-wide audit is too coarse to enforce. W-11 has the
same shape: ``probes.py`` is the ONLY file permitted to read the environment, the
filesystem or installed metadata, and every other file in the package is
injected with what it needs. The module-wide audit below cannot express that,
because it constrains ``hfss_agent`` roots and says nothing about the standard
library. So the per-file check is here for W-7's reason, not by imitation.

WHERE THE INNER CONSTRAINT IS ALSO ASSERTED, so a reader finding both does not
think one is redundant. ``tests/preflight/test_support_matrix.py`` carries a
narrower version beside the code it constrains: it globs ``preflight/*.py``
minus ``probes.py`` and forbids four host-reading modules by name. This file is
the canonical statement — broader (every I/O-capable module, not four), homed
where §4 says import audits live, and paired with the ``os``-attribute audit in
``test_preflight_os_surface_audit.py`` that closes the gap ``import os`` leaves
open. The unit-suite copy stays because it fails FIRST and closest to the edit.

``hfss_agent.session`` and ``hfss_agent.adapter`` are LOWER layers that W-11
nonetheless may not import, for the same reason W-5, W-6 and W-7 may not. The
reason differs slightly here and is worth stating: preflight makes no adapter
call at all (ADR-26 decision 1), so this is not "reach HFSS only through the
broker" — it is that preflight must remain constructible with NO session in
existence, which is what Journey 1.0 requires. An adapter import would not merely
bypass a gate; it would couple the pre-attach tool to the attached world.

THE PEER SYMMETRY. This file forbids ``hfss_agent.inspect``,
``hfss_agent.validate_native`` and ``hfss_agent.metrics``, exactly as all three
already forbid ``hfss_agent.preflight``. The four are Layer-4 SIBLINGS — peers,
not a stack — so none may depend on another, in any direction. That symmetry is
what makes the forced duplication ADR-26 alternative (h) records — preflight's
wrapper-version probe beside the real adapter's — structurally unavoidable
rather than lazy: unifying them requires a package both may legally import, and
there is none.
"""

from __future__ import annotations

import ast
from pathlib import Path

_PREFLIGHT = Path(__file__).resolve().parents[2] / "src" / "hfss_agent" / "preflight"

# hfss_agent roots the preflight module may depend on (§5 Layer 4).
# ``hfss_agent.preflight`` is itself allowed (a package importing its own
# submodules is not a boundary break).
_ALLOWED_HFSS_ROOTS = (
    "hfss_agent.broker",
    "hfss_agent.contract",
    "hfss_agent.preflight",
)

# Roots that must never appear: the AEDT API (both name shapes, ADR-17
# decision 8), the two lower layers preflight must not couple to, the three
# Layer-4 siblings it may not depend on, and every layer it sits below or beside.
_FORBIDDEN_ROOTS = (
    "pyaedt",
    "ansys.aedt",
    "hfss_agent.adapter",
    "hfss_agent.session",
    "hfss_agent.server",
    "hfss_agent.inspect",
    "hfss_agent.validate_native",
    "hfss_agent.metrics",
    "hfss_agent.gating",
    "hfss_agent.snapshot",
    "hfss_agent.findings",
)

# The ONE file permitted to read machine state. Named rather than discovered, so
# that adding a second is a deliberate act which names itself here — a new
# host-reading file is not silently exempt, and a new pure file is not silently
# covered either. This mirrors W-7's ``_PURE_FORMULA_FILES``, inverted: W-7 lists
# the files that must stay pure, W-11 lists the one that need not.
_HOST_READING_FILES = ("probes.py",)

# Modules that would let a file reach the machine on its own: the filesystem, the
# environment, the interpreter's own identity, installed metadata, the network, a
# subprocess. None is an hfss_agent module, so the root lists above cannot
# express this; it is checked separately against the same parsed import list.
_HOST_CAPABLE_MODULES = (
    "os",
    "io",
    "sys",
    "platform",
    "importlib",
    "pathlib",
    "shutil",
    "tempfile",
    "subprocess",
    "socket",
    "urllib",
    "http",
    "requests",
    "sysconfig",
    "site",
)


def _under(module: str, root: str) -> bool:
    return module == root or module.startswith(root + ".")


def _imported_modules(source: str) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module)
    return modules


def _preflight_sources() -> list[Path]:
    files = sorted(_PREFLIGHT.rglob("*.py"))
    assert files, f"no preflight source files found under {_PREFLIGHT}"
    return files


def test_preflight_imports_only_broker_and_contract() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _preflight_sources():
        hfss = [
            module
            for module in _imported_modules(path.read_text(encoding="utf-8"))
            if _under(module, "hfss_agent")
        ]
        bad = [
            module
            for module in hfss
            if not any(_under(module, root) for root in _ALLOWED_HFSS_ROOTS)
        ]
        if bad:
            offenders[path.name] = bad
    assert not offenders, (
        f"preflight imported hfss_agent modules outside broker/contract: {offenders}"
    )


def test_preflight_imports_nothing_forbidden() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _preflight_sources():
        modules = _imported_modules(path.read_text(encoding="utf-8"))
        bad = [
            module
            for module in modules
            if any(_under(module, root) for root in _FORBIDDEN_ROOTS)
        ]
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"preflight imported forbidden modules: {offenders}"


def test_preflight_does_not_reach_session_or_adapter_directly() -> None:
    # Stated as its own test, not folded into the list above, because it is the
    # specific structural claim ADR-26 decision 1 makes: preflight does not reach
    # the AEDT API at all, and must stay usable with no session in existence. A
    # regression here would still be caught by the blanket test, but not named as
    # the thing it actually broke.
    for root in ("hfss_agent.session", "hfss_agent.adapter"):
        assert root in _FORBIDDEN_ROOTS
    for path in _preflight_sources():
        modules = _imported_modules(path.read_text(encoding="utf-8"))
        assert not [
            module
            for module in modules
            if _under(module, "hfss_agent.session")
            or _under(module, "hfss_agent.adapter")
        ], f"{path.name} couples the pre-attach tool to the attached world"


def test_only_the_probe_file_reads_machine_state() -> None:
    """The injection seam, made a boundary rather than a convention.

    ``EnvironmentProbes`` exists so every band, verdict and rendered line is a
    pure function of injected data — which is what lets W-11's whole suite run
    identically on a Windows laptop carrying PyAEDT and no AEDT and on a Linux
    runner carrying neither. That guarantee is only as strong as the claim that
    nothing outside ``probes.py`` can go around the seam, and this is where that
    claim stops being a convention.

    Discovered by glob, so a file added tomorrow is covered without this test
    being edited.
    """
    offenders: dict[str, list[str]] = {}
    for path in _preflight_sources():
        if path.name in _HOST_READING_FILES:
            continue
        bad = [
            module
            for module in _imported_modules(path.read_text(encoding="utf-8"))
            if any(_under(module, root) for root in _HOST_CAPABLE_MODULES)
        ]
        if bad:
            offenders[path.name] = bad
    assert not offenders, (
        "only probes.py may read machine state; these files import host-capable "
        f"modules: {offenders}"
    )


def test_the_declared_host_reading_file_exists_and_actually_reads() -> None:
    """The exemption cannot silently hollow out.

    W-7's audit makes the same move from the other direction (its positive check
    that ``broker/files`` really does contain file I/O). If ``probes.py`` ever
    stopped importing anything host-capable, the exemption above would be
    permitting something nothing uses, and the next file added to the list would
    inherit an unexamined allowance.
    """
    for name in _HOST_READING_FILES:
        path = _PREFLIGHT / name
        assert path.exists(), f"declared host-reading file {name} is missing"
        modules = _imported_modules(path.read_text(encoding="utf-8"))
        assert any(
            any(_under(module, root) for root in _HOST_CAPABLE_MODULES)
            for module in modules
        ), f"{name} is exempted as host-reading but imports nothing host-capable"


def test_no_preflight_file_calls_open() -> None:
    """``open`` is a builtin and needs no import, so the module list above cannot
    see it. Only the broker writes files, and preflight hands its bundle payload
    to ``Broker.write_export`` as a string — the same split ``metrics/export.py``
    keeps between content and write."""
    for path in _preflight_sources():
        called = {
            node.func.id
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "open" not in called, (
            f"{path.name} calls open(); every write is the broker's"
        )


def test_audit_would_catch_a_forbidden_import() -> None:
    # The audit is only meaningful if it actually detects a violation — in both
    # AEDT name shapes, for an upper layer, for the coupling this file exists to
    # prevent, and for the three Layer-4 siblings.
    assert _imported_modules("import pyaedt") == ["pyaedt"]
    assert _imported_modules("from ansys.aedt.core import Hfss") == ["ansys.aedt.core"]
    assert _imported_modules("from hfss_agent.server import app") == [
        "hfss_agent.server"
    ]
    assert _imported_modules("from hfss_agent.session import Session") == [
        "hfss_agent.session"
    ]
    for sibling in ("inspect", "validate_native", "metrics"):
        assert any(
            _under(f"hfss_agent.{sibling}", root) for root in _FORBIDDEN_ROOTS
        ), f"the Layer-4 sibling hfss_agent.{sibling} must be forbidden"
    assert any(_under("ansys.aedt.core", root) for root in _FORBIDDEN_ROOTS)
    assert any(_under("hfss_agent.session", root) for root in _FORBIDDEN_ROOTS)


def test_the_host_state_check_would_catch_a_probe_bypass() -> None:
    # The narrower check's whole value is that it rejects something the
    # module-wide audit accepts: ``import os`` is invisible to the hfss_agent
    # root lists. Asserting that difference directly, so the two can never
    # silently converge into one.
    for bypass in ("import os", "import platform", "from pathlib import Path"):
        modules = _imported_modules(bypass)
        assert any(
            any(_under(module, root) for root in _HOST_CAPABLE_MODULES)
            for module in modules
        ), f"{bypass!r} must be caught by the host-state check"
        assert not any(_under(module, "hfss_agent") for module in modules), (
            f"{bypass!r} is invisible to the module-wide audit, which is why "
            "the narrower check exists"
        )
    # And the imports the pure files legitimately use must not trip it.
    for allowed in ("json", "re", "dataclasses", "collections.abc", "typing"):
        assert not any(
            _under(allowed, root) for root in _HOST_CAPABLE_MODULES
        ), f"{allowed!r} is legitimate in a pure preflight file"


def test_stdlib_names_are_not_caught_by_the_hfss_agent_bans() -> None:
    """``hfss_agent.inspect`` is banned; the stdlib ``inspect`` is not.

    Every hfss_agent entry is fully qualified and ``_under`` matches on equality
    or a dotted-prefix boundary, so a bare stdlib name colliding with one of our
    package names cannot trigger it. ``inspect`` is the live collision (W-5's
    package is named after it).
    """
    for stdlib_name in ("inspect", "inspect.signature", "contextlib", "types"):
        assert not any(_under(stdlib_name, root) for root in _FORBIDDEN_ROOTS), (
            f"the stdlib module {stdlib_name!r} must not trip the hfss_agent bans"
        )
    assert any(_under("hfss_agent.inspect", root) for root in _FORBIDDEN_ROOTS)
    assert not _under("inspect", "hfss_agent")
