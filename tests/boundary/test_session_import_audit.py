"""Layer-2 import audit (W-2): the session module imports only ``adapter`` and
``contract`` (and its own submodules) — never pyaedt, never broker/server, never
any other hfss_agent unit.

System Design §4 homes import audits in this ``tests/boundary/`` suite, so this
lives here alongside ``test_adapter_import_audit.py`` (the AEDT-API boundary)
rather than under ``tests/session/``. It follows that file's self-contained AST
pattern: parse each source file's imports statically rather than executing it. The
AST approach is what lets us assert imports are *only* adapter/contract — a
runtime ``sys.modules`` scan (as in ``test_contract_purity.py``) can assert the
*absence* of a denylisted module but not that nothing else is imported.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SESSION = Path(__file__).resolve().parents[2] / "src" / "hfss_agent" / "session"

# hfss_agent roots the session module may depend on. ``hfss_agent.session`` is
# itself allowed (a package importing its own submodules is not a boundary break).
_ALLOWED_HFSS_ROOTS = (
    "hfss_agent.adapter",
    "hfss_agent.contract",
    "hfss_agent.session",
)

# Roots that must never appear: the AEDT API (both name shapes) and any layer the
# session sits below or beside.
_FORBIDDEN_ROOTS = (
    "pyaedt",
    "ansys.aedt",
    "hfss_agent.broker",
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


def _session_sources() -> list[Path]:
    files = sorted(_SESSION.rglob("*.py"))
    assert files, f"no session source files found under {_SESSION}"
    return files


def test_session_imports_only_adapter_and_contract() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _session_sources():
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
        f"session imported hfss_agent modules outside adapter/contract: {offenders}"
    )


def test_session_imports_nothing_forbidden() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _session_sources():
        modules = _imported_modules(path.read_text(encoding="utf-8"))
        bad = [
            module
            for module in modules
            if any(_under(module, root) for root in _FORBIDDEN_ROOTS)
        ]
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"session imported forbidden modules: {offenders}"


def test_audit_would_catch_a_forbidden_import() -> None:
    # The audit is only meaningful if it actually detects a violation.
    assert _imported_modules("import pyaedt") == ["pyaedt"]
    assert _imported_modules("from hfss_agent.broker import Broker") == [
        "hfss_agent.broker"
    ]
    assert any(_under("hfss_agent.broker", root) for root in _FORBIDDEN_ROOTS)
