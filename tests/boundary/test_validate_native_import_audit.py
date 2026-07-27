"""Layer-4 import audit (W-6): the validate_native module imports only ``broker``
and ``contract`` (and its own submodules) — never pyaedt, never session or
adapter, never server or any Layer-5+ unit.

System Design §5 places validate_native at Layer 4 (validate_native -> broker,
contract; anything unlisted is prohibited), and §4 homes import audits in this
``tests/boundary/`` suite. This is a structural clone of
``test_inspect_import_audit.py``: parse each glob-discovered source file's
imports statically (AST, no exec) — the approach that can assert imports are
*only* the allowed roots, not merely that a denylisted module is absent.

``hfss_agent.session`` and ``hfss_agent.adapter`` are LOWER layers that W-6
nonetheless may not import, for the same reason W-5 may not: the only route to
HFSS is ``adapter -> session -> broker -> W-6``. A direct session import would
let a native validation run outside the tier gate, outside the audit log, and
outside the selection-state capture that makes the record mean anything. Denying
it here is what keeps that path the only path.

THE PEER SYMMETRY, and why it is load-bearing rather than tidy. This file
forbids ``hfss_agent.inspect`` exactly as ``test_inspect_import_audit.py``
forbids ``hfss_agent.validate_native``. The two are Layer-4 SIBLINGS — peers,
not a stack — so neither may depend on the other, in either direction, and the
ban has to be stated twice because there is no single place that could state it
once. That symmetry is precisely what makes
``NativeValidationAssemblyError``'s near-duplication of
``InspectionAssemblyError`` justified rather than lazy: sharing the type is not
merely unappealing, it is structurally unavailable, and this pair of audits is
what makes that true rather than merely intended. A future maintainer who wants
to unify them must first find a package both siblings may legally import — and
must change one of these two files to do it, which is exactly the reviewable
event that should be required.
"""

from __future__ import annotations

import ast
from pathlib import Path

_VALIDATE_NATIVE = (
    Path(__file__).resolve().parents[2] / "src" / "hfss_agent" / "validate_native"
)

# hfss_agent roots the validate_native module may depend on (§5 Layer 4).
# ``hfss_agent.validate_native`` is itself allowed (a package importing its own
# submodules is not a boundary break).
_ALLOWED_HFSS_ROOTS = (
    "hfss_agent.broker",
    "hfss_agent.contract",
    "hfss_agent.validate_native",
)

# Roots that must never appear: the AEDT API (both name shapes, ADR-17
# decision 8), the two lower layers W-6 must reach only THROUGH the broker, the
# Layer-4 sibling it may not depend on, and every layer it sits below or beside.
_FORBIDDEN_ROOTS = (
    "pyaedt",
    "ansys.aedt",
    "hfss_agent.adapter",
    "hfss_agent.session",
    "hfss_agent.server",
    "hfss_agent.inspect",
    "hfss_agent.metrics",
    "hfss_agent.gating",
    "hfss_agent.snapshot",
    "hfss_agent.findings",
    "hfss_agent.preflight",
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


def _validate_native_sources() -> list[Path]:
    files = sorted(_VALIDATE_NATIVE.rglob("*.py"))
    assert files, f"no validate_native source files found under {_VALIDATE_NATIVE}"
    return files


def test_validate_native_imports_only_broker_and_contract() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _validate_native_sources():
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
        "validate_native imported hfss_agent modules outside broker/contract: "
        f"{offenders}"
    )


def test_validate_native_imports_nothing_forbidden() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _validate_native_sources():
        modules = _imported_modules(path.read_text(encoding="utf-8"))
        bad = [
            module
            for module in modules
            if any(_under(module, root) for root in _FORBIDDEN_ROOTS)
        ]
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"validate_native imported forbidden modules: {offenders}"


def test_validate_native_does_not_reach_session_or_adapter_directly() -> None:
    # Stated as its own test, not folded into the list above, because it is the
    # specific structural claim ADR-20 decision 1 makes and W-6 inherits: the
    # ONLY route to a native validation run is a broker dispatch. A regression
    # here would still be caught by the blanket test, but not named as the thing
    # it actually broke.
    for root in ("hfss_agent.session", "hfss_agent.adapter"):
        assert root in _FORBIDDEN_ROOTS
    for path in _validate_native_sources():
        modules = _imported_modules(path.read_text(encoding="utf-8"))
        assert not [
            module
            for module in modules
            if _under(module, "hfss_agent.session")
            or _under(module, "hfss_agent.adapter")
        ], f"{path.name} reaches the session/adapter without going through the broker"


def test_the_sanitizer_is_out_of_reach_by_prefix_not_by_a_second_entry() -> None:
    """The one temptation the assembler documents by name.

    ``native_template_text``'s sanitization notice describes a per-message
    length cap but states no number, because the number is
    ``hfss_agent.adapter.sanitize.MAX_UNTRUSTED_STR_LEN`` and importing it would
    break this boundary. That makes the submodule a live temptation rather than
    a hypothetical one, so it gets a named test.

    It gets no second ``_FORBIDDEN_ROOTS`` entry, though: ``_under`` matches on
    a dotted-prefix boundary, so the existing ``hfss_agent.adapter`` ban already
    covers every submodule beneath it. Adding ``hfss_agent.adapter.sanitize``
    alongside it would be redundant AND actively misleading — it would imply
    that submodules are not otherwise covered, inviting someone to "complete"
    the list root by root. The prefix rule is asserted here instead, so the
    coverage is proven rather than assumed.
    """
    assert _under("hfss_agent.adapter.sanitize", "hfss_agent.adapter")
    assert "hfss_agent.adapter.sanitize" not in _FORBIDDEN_ROOTS
    for path in _validate_native_sources():
        modules = _imported_modules(path.read_text(encoding="utf-8"))
        assert "hfss_agent.adapter.sanitize" not in modules, (
            f"{path.name} imports the sanitizer directly; the cap's value is not "
            "reachable from Layer 4, and the notice must stay number-free"
        )


def test_audit_would_catch_a_forbidden_import() -> None:
    # The audit is only meaningful if it actually detects a violation — in both
    # AEDT name shapes, for an upper layer, for the bypass this suite exists to
    # prevent, and for the Layer-4 sibling this file adds to the list.
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
    assert any(_under("ansys.aedt.core", root) for root in _FORBIDDEN_ROOTS)
    assert any(_under("hfss_agent.session", root) for root in _FORBIDDEN_ROOTS)
    assert any(_under("hfss_agent.inspect", root) for root in _FORBIDDEN_ROOTS)
