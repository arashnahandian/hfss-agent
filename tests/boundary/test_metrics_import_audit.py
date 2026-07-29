"""Layer-4 import audit (W-7): the metrics module imports only ``broker`` and
``contract`` (and its own submodules) — never pyaedt, never session or adapter,
never server or any Layer-5+ unit — and the formula files themselves import
``contract`` only.

System Design §5 places metrics at Layer 4 (metrics -> broker, contract;
anything unlisted is prohibited), and §4 homes import audits in this
``tests/boundary/`` suite. This is a structural clone of
``test_validate_native_import_audit.py`` and ``test_inspect_import_audit.py``:
parse each glob-discovered source file's imports statically (AST, no exec) — the
approach that can assert imports are *only* the allowed roots, not merely that a
denylisted module is absent. No second mechanism is introduced here; the three
Layer-4 audits must stay comparable line for line, because the day they diverge
is the day nobody can tell whether a difference is a decision or a drift.

``hfss_agent.session`` and ``hfss_agent.adapter`` are LOWER layers that W-7
nonetheless may not import, for the same reason W-5 and W-6 may not: the only
route to HFSS is ``adapter -> session -> broker -> W-7``. A direct session
import would let a metric be computed outside the tier gate, outside the audit
log, and outside the selection-state capture that makes the record mean
anything. Denying it here is what keeps that path the only path.

THE PEER SYMMETRY. This file forbids ``hfss_agent.inspect`` and
``hfss_agent.validate_native``, exactly as both of those already forbid
``hfss_agent.metrics``. The three are Layer-4 SIBLINGS — peers, not a stack — so
none may depend on another, in any direction, and the ban has to be stated once
per sibling because there is no single place that could state it once.

WHY THIS FILE HAS A TEST ITS TWO SIBLINGS DO NOT.
``test_formula_files_import_contract_only`` has no counterpart in the inspect or
validate_native audits, and the asymmetry is deliberate: §5's Layer-4 line for
metrics is the only one carrying a parenthetical — "metrics (W-7) -> broker,
contract   (formulas themselves: pure)". W-5 and W-6 have no comparable inner
constraint to protect, because every part of them is assembly. W-7 is two things
at once: open formulas that must stay computable from nothing but numbers, and
(from Part 2 of this step onward) the broker-facing wiring that fetches those
numbers from a live session. The module-wide audit below permits ``broker``,
because the wiring legitimately needs it. That permission is exactly what would
let a later edit quietly reach the broker from inside a formula, and the
module-wide test could never object. This one can.

``hfss_agent.gating`` is forbidden here, and the consequence is worth stating
because it looks like a contradiction: §1.1 says W-7 refuses to run before the
gates pass, yet W-7 may not import the module that evaluates them. Both are
intended. A gate OUTCOME reaches W-7 as data passed in by its caller, never as a
call W-7 makes — which is also why ``MetricRecord`` carries
``gate_status_at_computation`` as a recorded field rather than something the
metric layer could look up for itself.
"""

from __future__ import annotations

import ast
from pathlib import Path

_METRICS = Path(__file__).resolve().parents[2] / "src" / "hfss_agent" / "metrics"

# hfss_agent roots the metrics module may depend on (§5 Layer 4).
# ``hfss_agent.metrics`` is itself allowed (a package importing its own
# submodules is not a boundary break).
_ALLOWED_HFSS_ROOTS = (
    "hfss_agent.broker",
    "hfss_agent.contract",
    "hfss_agent.metrics",
)

# Roots that must never appear: the AEDT API (both name shapes, ADR-17
# decision 8), the two lower layers metrics must reach only THROUGH the broker,
# the two Layer-4 siblings it may not depend on, and every layer it sits below
# or beside.
_FORBIDDEN_ROOTS = (
    "pyaedt",
    "ansys.aedt",
    "hfss_agent.adapter",
    "hfss_agent.session",
    "hfss_agent.server",
    "hfss_agent.inspect",
    "hfss_agent.validate_native",
    "hfss_agent.gating",
    "hfss_agent.snapshot",
    "hfss_agent.findings",
    "hfss_agent.preflight",
)

# The files that must stay computable from their arguments alone. Listed by name
# rather than discovered, so that adding one is a deliberate act that names
# itself here — a new file is not silently exempt, and is not silently covered
# either.
#
#   sparams.py — the open formulas, which must stay pure per §5's parenthetical.
#   export.py  — the Touchstone/CSV content generators. §1.1 splits export in
#                two: this module owns the CONTENT, the broker owns the WRITE.
#                Keeping the broker out by audit is what makes that split a
#                property of the code rather than a note in a docstring.
_PURE_FORMULA_FILES = ("sparams.py", "export.py")

# Modules that would give a file a way to reach the disk on its own. None is an
# hfss_agent module, so the allowed/forbidden root lists above cannot express
# this; it is checked separately against the same parsed import list.
_IO_CAPABLE_MODULES = (
    "os",
    "io",
    "pathlib",
    "shutil",
    "tempfile",
    "subprocess",
    "socket",
    "urllib",
    "http",
    "requests",
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


def _metrics_sources() -> list[Path]:
    files = sorted(_METRICS.rglob("*.py"))
    assert files, f"no metrics source files found under {_METRICS}"
    return files


def test_metrics_imports_only_broker_and_contract() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _metrics_sources():
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
        f"metrics imported hfss_agent modules outside broker/contract: {offenders}"
    )


def test_metrics_imports_nothing_forbidden() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _metrics_sources():
        modules = _imported_modules(path.read_text(encoding="utf-8"))
        bad = [
            module
            for module in modules
            if any(_under(module, root) for root in _FORBIDDEN_ROOTS)
        ]
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"metrics imported forbidden modules: {offenders}"


def test_metrics_does_not_reach_session_or_adapter_directly() -> None:
    # Stated as its own test, not folded into the list above, because it is the
    # specific structural claim ADR-20 decision 1 makes and W-7 inherits: the
    # ONLY route to the numbers a metric is computed from is a broker dispatch.
    # A regression here would still be caught by the blanket test, but not named
    # as the thing it actually broke.
    for root in ("hfss_agent.session", "hfss_agent.adapter"):
        assert root in _FORBIDDEN_ROOTS
    for path in _metrics_sources():
        modules = _imported_modules(path.read_text(encoding="utf-8"))
        assert not [
            module
            for module in modules
            if _under(module, "hfss_agent.session")
            or _under(module, "hfss_agent.adapter")
        ], f"{path.name} reaches the session/adapter without going through the broker"


def test_formula_files_import_contract_only() -> None:
    """§5's "(formulas themselves: pure)" parenthetical, made enforceable.

    See the module docstring for why this test exists here and nowhere else. It
    is narrower than the module-wide audit above in exactly one way that matters:
    ``hfss_agent.broker`` is allowed there and forbidden here.
    """
    for name in _PURE_FORMULA_FILES:
        path = _METRICS / name
        assert path.exists(), f"declared pure file {name} is missing from {_METRICS}"
        hfss = [
            module
            for module in _imported_modules(path.read_text(encoding="utf-8"))
            if _under(module, "hfss_agent")
        ]
        assert all(_under(module, "hfss_agent.contract") for module in hfss), (
            f"{name} must import hfss_agent.contract only, but imports {hfss}"
        )


def test_pure_files_import_nothing_io_capable() -> None:
    """No file, network, or process handle is reachable from a pure file.

    The contract-only check above constrains the ``hfss_agent`` imports and says
    nothing about the standard library, where ``open`` is one ``import os`` away.
    ``export.py`` is the file that makes this worth asserting rather than
    assuming: it generates the exact strings that are about to become files, so
    it is the one place where writing them directly would look like a
    convenience rather than a boundary break.

    ``open`` itself is a builtin and needs no import, so the name is checked for
    directly rather than only its usual companions.
    """
    for name in _PURE_FORMULA_FILES:
        source = (_METRICS / name).read_text(encoding="utf-8")
        modules = _imported_modules(source)
        bad = [
            module
            for module in modules
            if any(_under(module, root) for root in _IO_CAPABLE_MODULES)
        ]
        assert not bad, f"{name} imports I/O-capable modules: {bad}"
        called = {
            node.func.id
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "open" not in called, f"{name} calls open(); the write is the broker's"


def test_audit_would_catch_a_forbidden_import() -> None:
    # The audit is only meaningful if it actually detects a violation — in both
    # AEDT name shapes, for an upper layer, for the bypass this suite exists to
    # prevent, and for the two Layer-4 siblings this file adds to the list.
    assert _imported_modules("import pyaedt") == ["pyaedt"]
    assert _imported_modules("from ansys.aedt.core import Hfss") == ["ansys.aedt.core"]
    assert _imported_modules("from hfss_agent.server import app") == [
        "hfss_agent.server"
    ]
    assert _imported_modules("from hfss_agent.session import Session") == [
        "hfss_agent.session"
    ]
    assert _imported_modules("from hfss_agent.inspect import inspect_design") == [
        "hfss_agent.inspect"
    ]
    sibling = "from hfss_agent.validate_native import validate_native"
    assert _imported_modules(sibling) == ["hfss_agent.validate_native"]
    assert any(_under("ansys.aedt.core", root) for root in _FORBIDDEN_ROOTS)
    assert any(_under("hfss_agent.session", root) for root in _FORBIDDEN_ROOTS)
    assert any(_under("hfss_agent.validate_native", root) for root in _FORBIDDEN_ROOTS)


def test_stdlib_names_are_not_caught_by_the_hfss_agent_bans() -> None:
    """``hfss_agent.inspect`` is banned; the stdlib ``inspect`` is not.

    Every hfss_agent entry in the two root tuples is fully qualified, and
    ``_under`` matches on equality or a dotted-prefix boundary — so a bare
    stdlib name that happens to collide with one of our module names cannot
    trigger it. ``inspect`` is the live collision (W-5's package is named after
    it); ``contextlib`` stands in for the general case.
    """
    for stdlib_name in ("inspect", "inspect.signature", "contextlib", "types"):
        assert not any(
            _under(stdlib_name, root) for root in _FORBIDDEN_ROOTS
        ), f"the stdlib module {stdlib_name!r} must not trip the hfss_agent bans"
    # And the ban it could have been confused with does still fire.
    assert any(_under("hfss_agent.inspect", root) for root in _FORBIDDEN_ROOTS)
    # The audits only ever consider hfss_agent-rooted modules for the
    # allowed-roots check, so a stdlib import is not an "outside broker/contract"
    # offender either.
    assert not _under("inspect", "hfss_agent")


def test_the_io_check_would_catch_a_write_path() -> None:
    # The I/O check is only meaningful if it detects the shortcuts it forbids.
    assert _imported_modules("import os") == ["os"]
    assert _imported_modules("from pathlib import Path") == ["pathlib"]
    assert _imported_modules("import io") == ["io"]
    for name in ("os", "pathlib", "io"):
        assert any(_under(name, root) for root in _IO_CAPABLE_MODULES)
    # ``re`` and ``math`` are what these files legitimately import; the check
    # must not object to them.
    for name in ("re", "math", "bisect", "dataclasses"):
        assert not any(_under(name, root) for root in _IO_CAPABLE_MODULES)


def test_the_pure_formula_check_would_catch_a_broker_import() -> None:
    # The narrower check's whole value is that it rejects something the
    # module-wide audit accepts. Asserting that difference directly, so the two
    # can never silently converge into one.
    broker_import = "from hfss_agent.broker import Broker"
    assert _imported_modules(broker_import) == ["hfss_agent.broker"]
    assert any(
        _under("hfss_agent.broker", root) for root in _ALLOWED_HFSS_ROOTS
    ), "the module-wide audit must keep allowing the broker; Part 2 wiring needs it"
    assert not _under("hfss_agent.broker", "hfss_agent.contract"), (
        "the pure-formula check must reject the broker import the module-wide "
        "audit allows"
    )
