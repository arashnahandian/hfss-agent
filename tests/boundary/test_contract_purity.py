"""Canonical contract import-purity test (ADR-3; runbook Step 1.1 Done criteria).

Importing the public contract subpackage — ``hfss_agent.contract`` and its
``tool_io`` tool-I/O schemas — must not pull in ``pyaedt`` or any I/O-capable
module. This is the load-bearing guarantee (ADR-3) that lets the closed engine
and ``gating`` depend on the contract without tripping the import audit, and
keeps the wrapper the sole capability-holder. System Design §4 homes "contract
purity" in this ``tests/boundary/`` suite.

The check runs in a *fresh* interpreter (subprocess) — reusing the pattern from
the tool_io purity check — so no other test's imports can mask a leak. A
violation is caught two ways: an errant ``import pyaedt`` fails the subprocess
outright (pyaedt is not installed), and any denylisted module that *were*
installed and leaked would show up in the subprocess's sys.modules scan.
"""

import importlib.util
import subprocess
import sys

# I/O-capable modules whose presence would mean the contract reached past pure
# data. Some obvious candidates are DELIBERATELY EXCLUDED because they are
# transitively imported by pydantic — the contract's one sanctioned dependency —
# not by the contract reaching for I/O, so listing them would make the test
# flaky, not stricter:
#   * os, io, pathlib — pulled in at pydantic import;
#   * socket — pulled in the moment pydantic *builds a model* (verified: a
#     single-field BaseModel is enough), so every schema module trips it. It is
#     pydantic machinery, the same category as os/io/pathlib, not a contract
#     egress path.
_STDLIB_IO_DENYLIST = [
    "subprocess",
    "urllib.request",
    "http.client",
]
# Third-party HTTP clients: only meaningful to assert-absent when actually
# installed, so they join the denylist only if importable in this environment.
_OPTIONAL_IO_DENYLIST = ["requests", "httpx"]


def _active_io_denylist() -> list[str]:
    denylist = list(_STDLIB_IO_DENYLIST)
    for name in _OPTIONAL_IO_DENYLIST:
        if importlib.util.find_spec(name) is not None:
            denylist.append(name)
    return denylist


def test_contract_import_pulls_in_no_pyaedt_or_io() -> None:
    denylist = _active_io_denylist()
    # Fresh interpreter so no other test's imports can mask a leak. Import BOTH
    # the top-level contract and the tool_io subpackage, so a leak anywhere under
    # either is caught, then scan this clean process's sys.modules.
    code = (
        "import sys\n"
        "import hfss_agent.contract  # noqa: F401\n"
        "import hfss_agent.contract.tool_io  # noqa: F401\n"
        f"denylist = {denylist!r}\n"
        "pyaedt = sorted(m for m in sys.modules "
        "if m == 'pyaedt' or m.startswith('pyaedt.'))\n"
        "io_leaks = sorted(m for m in denylist if m in sys.modules)\n"
        "assert not pyaedt, ('pyaedt leaked into contract', pyaedt)\n"
        "assert not io_leaks, ('I/O modules leaked into contract', io_leaks)\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
