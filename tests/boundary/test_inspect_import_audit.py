"""Layer-4 import audit (W-5): the inspect module imports only ``broker`` and
``contract`` (and its own submodules) — never pyaedt, never session or adapter,
never server or any Layer-5+ unit.

System Design §5 places inspect at Layer 4 (inspect -> broker, contract;
anything unlisted is prohibited), and §4 homes import audits in this
``tests/boundary/`` suite. This is a structural clone of
``test_broker_import_audit.py``: parse each glob-discovered source file's
imports statically (AST, no exec) — the approach that can assert imports are
*only* the allowed roots, not merely that a denylisted module is absent.

Two entries in the forbidden list are worth stating outright, because they are
the ones a well-meaning shortcut would reach for. ``hfss_agent.session`` and
``hfss_agent.adapter`` are LOWER layers that inspect nonetheless may not import:
the whole point of ADR-20 decision 1 is that W-5's only data path is
``adapter -> session -> broker -> W-5``. A direct session import would let an
inspection read run without a broker dispatch — outside the tier gate, outside
the audit log, and outside the selection-state capture that makes the record
mean anything. Denying it here is what keeps that path the only path.
"""

from __future__ import annotations

import ast
from pathlib import Path

_INSPECT = Path(__file__).resolve().parents[2] / "src" / "hfss_agent" / "inspect"

# hfss_agent roots the inspect module may depend on (§5 Layer 4).
# ``hfss_agent.inspect`` is itself allowed (a package importing its own
# submodules is not a boundary break).
_ALLOWED_HFSS_ROOTS = (
    "hfss_agent.broker",
    "hfss_agent.contract",
    "hfss_agent.inspect",
)

# Roots that must never appear: the AEDT API (both name shapes, ADR-17
# decision 8), the two lower layers inspect must reach only THROUGH the broker,
# and every layer inspect sits below or beside.
_FORBIDDEN_ROOTS = (
    "pyaedt",
    "ansys.aedt",
    "hfss_agent.adapter",
    "hfss_agent.session",
    "hfss_agent.server",
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


def _inspect_sources() -> list[Path]:
    files = sorted(_INSPECT.rglob("*.py"))
    assert files, f"no inspect source files found under {_INSPECT}"
    return files


def test_inspect_imports_only_broker_and_contract() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _inspect_sources():
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
        f"inspect imported hfss_agent modules outside broker/contract: {offenders}"
    )


def test_inspect_imports_nothing_forbidden() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _inspect_sources():
        modules = _imported_modules(path.read_text(encoding="utf-8"))
        bad = [
            module
            for module in modules
            if any(_under(module, root) for root in _FORBIDDEN_ROOTS)
        ]
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"inspect imported forbidden modules: {offenders}"


def test_inspect_does_not_reach_session_or_adapter_directly() -> None:
    # Stated as its own test, not folded into the list above, because it is the
    # specific structural claim ADR-20 decision 1 makes: the ONLY route to a
    # design read is a broker dispatch. A regression here would still be caught
    # by the blanket test, but not named as the thing it actually broke.
    for root in ("hfss_agent.session", "hfss_agent.adapter"):
        assert root in _FORBIDDEN_ROOTS
    for path in _inspect_sources():
        modules = _imported_modules(path.read_text(encoding="utf-8"))
        assert not [
            module
            for module in modules
            if _under(module, "hfss_agent.session")
            or _under(module, "hfss_agent.adapter")
        ], f"{path.name} reaches the session/adapter without going through the broker"


def test_audit_would_catch_a_forbidden_import() -> None:
    # The audit is only meaningful if it actually detects a violation — in both
    # AEDT name shapes, for an upper layer, and for the bypass this suite
    # exists to prevent.
    assert _imported_modules("import pyaedt") == ["pyaedt"]
    assert _imported_modules("from ansys.aedt.core import Hfss") == ["ansys.aedt.core"]
    assert _imported_modules("from hfss_agent.server import app") == [
        "hfss_agent.server"
    ]
    assert _imported_modules("from hfss_agent.session import Session") == [
        "hfss_agent.session"
    ]
    assert any(_under("ansys.aedt.core", root) for root in _FORBIDDEN_ROOTS)
    assert any(_under("hfss_agent.session", root) for root in _FORBIDDEN_ROOTS)
