"""No-arbitrary-execution AST audit for the broker (W-4; ADR-7).

ADR-7 is absolute: no arbitrary-execution path exists anywhere in either repo.
The broker routes every capability and performs all file I/O, so an execution
hatch here would sit behind every tool at once. This audit enforces, on
source (AST, no exec), over glob-discovered ``broker/**`` (ADR-17 decision
11 — a module added later is covered the moment it exists):

  1. no dynamic-execution primitives — ``eval`` / ``exec`` / ``compile`` /
     ``__import__``;
  2. no ``subprocess`` import (and therefore no use — it cannot be called
     without being imported);
  3. no dynamic attribute dispatch — ``getattr`` / ``setattr`` / ``delattr``
     with a non-literal name (a caller-supplied string must never become an
     attribute lookup).

Structure follows ``test_adapter_read_only.py``: self-contained helpers, and
self-tests proving the audit BITES on synthetic offending snippets — an audit
that passes by matching nothing is worse than no audit.
"""

from __future__ import annotations

import ast
from pathlib import Path

_BROKER = Path(__file__).resolve().parents[2] / "src" / "hfss_agent" / "broker"

# Callables that introduce arbitrary execution.
_FORBIDDEN_CALLS = frozenset({"eval", "exec", "compile", "__import__"})
# Attribute-dispatch builtins: forbidden only when the attribute NAME is dynamic.
_DYNAMIC_ATTR_BUILTINS = frozenset({"getattr", "setattr", "delattr"})


def _audited_files() -> list[Path]:
    """Every module under ``broker/`` — discovered by glob, never hardcoded,
    so a file added to the package later cannot escape the audit silently."""
    return sorted(_BROKER.rglob("*.py"))


def _is_str_literal(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _violations(source: str) -> list[str]:
    """Every no-execution violation in ``source`` (AST, no exec)."""
    out: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name in _FORBIDDEN_CALLS:
                out.append(f"arbitrary-execution call: {name}()")
            elif (
                name in _DYNAMIC_ATTR_BUILTINS
                and len(node.args) >= 2
                and not _is_str_literal(node.args[1])
            ):
                out.append(f"dynamic attribute dispatch: {name}(..., <non-literal>)")
    return out


def _imports_subprocess(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "subprocess" for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] == "subprocess":
                return True
    return False


# --- the audit, over every discovered file in broker/ -------------------------


def test_audit_discovers_the_broker_package_files() -> None:
    # A broken path must not let the audit pass vacuously: require files, and
    # require the known modules to be among them.
    names = {path.name for path in _audited_files()}
    assert names, f"no files discovered under {_BROKER}"
    assert {"broker.py", "registry.py", "confirmation.py", "writer.py"} <= names


def test_broker_has_no_execution_hatch() -> None:
    for path in _audited_files():
        source = path.read_text(encoding="utf-8")
        assert not _violations(source), (path.name, _violations(source))
        assert not _imports_subprocess(source), f"{path.name} imports subprocess"


# --- the audit must actually bite: self-tests on synthetic snippets ----------


def test_audit_flags_execution_primitives() -> None:
    assert _violations("eval('1 + 1')")
    assert _violations("exec(user_code)")
    assert _violations("compile(src, '<s>', 'exec')")
    assert _violations("__import__(module_name)")


def test_audit_flags_dynamic_attribute_dispatch() -> None:
    assert _violations("getattr(broker, method_name)()")
    assert _violations("setattr(spec, field_name, value)")
    assert _violations("delattr(spec, field_name)")


def test_audit_flags_subprocess_import_in_both_forms() -> None:
    assert _imports_subprocess("import subprocess")
    assert _imports_subprocess("from subprocess import run")


def test_audit_allows_literal_getattr_and_plain_code() -> None:
    # A constant-name getattr is not dynamic dispatch; ordinary broker code
    # (calls, dataclasses, f-strings) is clean.
    assert not _violations("getattr(record, 'timestamp')")
    assert not _violations("spec.handler(**args)")
    assert not _imports_subprocess("import tempfile")
