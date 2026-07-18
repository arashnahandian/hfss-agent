"""AEDT-API import audit (W-3): only the real adapter's session module may import
the AEDT API, under EITHER name shape.

The AEDT API ships on PyPI as ``pyaedt`` but imports as ``ansys.aedt.core`` (the
1.0 restructure). Auditing only the literal string "pyaedt" would leave the whole
real API reachable via ``from ansys.aedt.core import Hfss``, so this audit denies
BOTH ``pyaedt`` / ``from pyaedt`` AND ``ansys.aedt`` / ``from ansys.aedt``
everywhere except the single permitted file.

Scope is deliberately narrow: this checks WHICH FILES may import the AEDT API,
nothing else. A general allowlist-based I/O-import audit is separate, later work
in the sibling repo — building it here would be scope creep.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "hfss_agent"

# The ONE file permitted to import the AEDT API, relative to _SRC.
_PERMITTED = Path("adapter/real/session.py")

# Forbidden import roots, matched against the dotted module path of every
# ``import X`` / ``from X import ...``. Both name shapes of the same package.
_FORBIDDEN_ROOTS = ("pyaedt", "ansys.aedt")


def _is_forbidden(module: str) -> bool:
    """True if ``module`` is, or is a submodule of, a forbidden AEDT-API root."""
    return any(
        module == root or module.startswith(root + ".") for root in _FORBIDDEN_ROOTS
    )


def _aedt_imports(source: str) -> list[str]:
    """Every forbidden AEDT-API module imported by ``source`` (via AST, no exec).

    Catches both ``import ansys.aedt.core`` (``ast.Import``) and
    ``from ansys.aedt.core import Hfss`` / ``from pyaedt import Hfss``
    (``ast.ImportFrom``). Relative imports (``node.level > 0``) are
    project-internal and can never name the AEDT API, so they are skipped.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names if _is_forbidden(alias.name)]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and _is_forbidden(node.module):
                found.append(node.module)
    return found


def test_only_session_module_imports_the_aedt_api() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _SRC.rglob("*.py"):
        relative = path.relative_to(_SRC)
        imports = _aedt_imports(path.read_text(encoding="utf-8"))
        if imports and relative != _PERMITTED:
            offenders[str(relative)] = imports
    assert not offenders, f"AEDT API imported outside {_PERMITTED}: {offenders}"


def test_permitted_session_module_actually_imports_the_aedt_api() -> None:
    # The permitted file is only meaningful as an exception if it really is the
    # AEDT-API boundary; guard against it silently drifting to import nothing.
    source = (_SRC / _PERMITTED).read_text(encoding="utf-8")
    assert _aedt_imports(source), f"{_PERMITTED} is expected to import the AEDT API"


def test_audit_detects_pyaedt_import_in_a_non_permitted_file() -> None:
    assert _aedt_imports("import pyaedt") == ["pyaedt"]
    assert _aedt_imports("from pyaedt import Hfss") == ["pyaedt"]


def test_audit_detects_ansys_aedt_core_import_in_a_non_permitted_file() -> None:
    # The hole a "pyaedt"-only check would leave: the real API under its import
    # name. Both statement forms must be caught.
    assert _aedt_imports("import ansys.aedt.core") == ["ansys.aedt.core"]
    assert _aedt_imports("from ansys.aedt.core import Hfss") == ["ansys.aedt.core"]


def test_audit_ignores_unrelated_and_relative_imports() -> None:
    # Neither an ansys package that is not the AEDT API, nor project-internal
    # imports, should trip the audit.
    assert _aedt_imports("import ansys.something_else") == []
    internal = "from hfss_agent.adapter.real.session import LiveSession"
    assert _aedt_imports(internal) == []


def test_importing_pyaedt_free_adapter_packages_loads_no_aedt_api() -> None:
    # Fresh interpreter so no other test's imports mask a leak. Importing the
    # adapter, the fake, AND the real package (its PyAEDT-free surface) must not
    # pull the AEDT API into sys.modules — only make_live_adapter() does.
    code = (
        "import sys\n"
        "import hfss_agent.adapter\n"
        "import hfss_agent.adapter.fake\n"
        "import hfss_agent.adapter.real\n"
        "leaked = sorted(m for m in sys.modules if m == 'pyaedt' "
        "or m.startswith('pyaedt.') or m == 'ansys' or m.startswith('ansys.'))\n"
        "assert not leaked, ('AEDT API leaked into adapter import', leaked)\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
