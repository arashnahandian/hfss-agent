"""Layer-3 import audit (W-4): the broker imports only ``session``,
``adapter``, and ``contract`` (and its own submodules) — never pyaedt, never
server, never any Layer-4+ unit.

System Design §5 places the broker at Layer 3 (broker -> session, adapter,
contract; anything unlisted is prohibited), and §4 homes import audits in
this ``tests/boundary/`` suite. This is a structural clone of
``test_session_import_audit.py``: parse each glob-discovered source file's
imports statically (AST, no exec) — the approach that can assert imports are
*only* the allowed roots, not merely that a denylisted module is absent. Both
AEDT-API name shapes are denied (``pyaedt`` and ``ansys.aedt``, ADR-17
decision 8).
"""

from __future__ import annotations

import ast
from pathlib import Path

_BROKER = Path(__file__).resolve().parents[2] / "src" / "hfss_agent" / "broker"

# hfss_agent roots the broker may depend on (§5 Layer 3). ``hfss_agent.broker``
# is itself allowed (a package importing its own submodules is not a boundary
# break).
_ALLOWED_HFSS_ROOTS = (
    "hfss_agent.adapter",
    "hfss_agent.broker",
    "hfss_agent.contract",
    "hfss_agent.session",
)

# Roots that must never appear: the AEDT API (both name shapes) and every
# layer the broker sits below or beside.
_FORBIDDEN_ROOTS = (
    "pyaedt",
    "ansys.aedt",
    "hfss_agent.server",
    "hfss_agent.inspect",
    "hfss_agent.metrics",
    "hfss_agent.gating",
    "hfss_agent.snapshot",
    "hfss_agent.findings",
    "hfss_agent.preflight",
    "hfss_agent.validate_native",
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


def _broker_sources() -> list[Path]:
    files = sorted(_BROKER.rglob("*.py"))
    assert files, f"no broker source files found under {_BROKER}"
    return files


def test_broker_imports_only_session_adapter_and_contract() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _broker_sources():
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
        f"broker imported hfss_agent modules outside session/adapter/contract: "
        f"{offenders}"
    )


def test_broker_imports_nothing_forbidden() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _broker_sources():
        modules = _imported_modules(path.read_text(encoding="utf-8"))
        bad = [
            module
            for module in modules
            if any(_under(module, root) for root in _FORBIDDEN_ROOTS)
        ]
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"broker imported forbidden modules: {offenders}"


def test_audit_would_catch_a_forbidden_import() -> None:
    # The audit is only meaningful if it actually detects a violation — in
    # both AEDT name shapes and for an upper layer.
    assert _imported_modules("import pyaedt") == ["pyaedt"]
    assert _imported_modules("from ansys.aedt.core import Hfss") == [
        "ansys.aedt.core"
    ]
    assert _imported_modules("from hfss_agent.server import app") == [
        "hfss_agent.server"
    ]
    assert any(_under("ansys.aedt.core", root) for root in _FORBIDDEN_ROOTS)
    assert any(_under("hfss_agent.server", root) for root in _FORBIDDEN_ROOTS)
