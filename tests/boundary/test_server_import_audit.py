"""Layer-7 import audit (W-1): the composition root's grant, enforced as an
ALLOW-LIST over every import, with two FILE-SCOPED exceptions.

POLARITY FOLLOWS W-9 AND W-10, NOT THE EIGHT HYBRID SIBLINGS. The module audits
for adapter, broker, session, inspect, validate_native, metrics, snapshot and
preflight all shipped with an ``ast.ImportFrom`` filter on ``node.level == 0``,
which DROPS EVERY RELATIVE IMPORT before the check is consulted -- a planted
``from ..broker import Broker`` left those files green. W-9 replaced that and
W-10 inherited the fix; this audit inherits it too. ``_imported_modules`` below
reports a relative import in its SOURCE SPELLING (``"..adapter"``, ``"."``),
which matches no allow-list root and is therefore refused.

THE ALLOW-LIST IS LONG HERE, AND THAT IS A WEAKER GUARANTEE. W-10 states the
principle: "A longer allow-list is a weaker guarantee, so every entry below
carries its reason AT THE PERMISSION." This is Layer 7 -- the composition root --
so it legitimately imports more than any other module in the repo: the nine
feature grants plus ``mcp``. The compensation is the two FILE-SCOPED exceptions
below. A package-wide permission for ``hfss_agent.adapter`` would let a tool
handler reach the adapter directly, which is the one thing Layer 7 must never
do; scoping it to two files makes every other file in the package
STRUCTURALLY unable to.

THE SCOPING IS BY PATH RELATIVE TO ``server/``, NOT BY BASENAME, and the
difference was measured rather than reasoned about. Keyed on ``path.name``,
a NEW FILE at ``server/handlers/composition.py`` inherited both exceptions --
the walk uses ``rglob`` so it was seen, it just could not be told apart from
the real ``composition.py`` -- and imported ``FakeAdapter`` and the
directory-creating ``locations`` module with every audit green. The permitted
sets below therefore hold posix RELATIVE PATHS; for today's flat package they
read identically to filenames, which is exactly why the defect was invisible.

WHAT THIS AUDIT DOES NOT COVER, so a green run is not over-read: it constrains
what ``server`` imports, not what imports ``server``. "Nothing below Layer 7
imports server" is the other direction and is enforced by the eight module
audits, each of which lists ``hfss_agent.server`` among its forbidden roots.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "hfss_agent"
_SERVER = _SRC / "server"

# --- the Layer-7 grant -------------------------------------------------------
#
# System Design §5, Layer 7: server -> broker, preflight, inspect,
# validate_native, snapshot, gating, metrics, findings, contract. Four of the
# nine are unused today (snapshot, gating, metrics, findings) because the tools
# that need them are deferred; they are permitted rather than added later so the
# grant matches the design document rather than the current build state.
_LAYER_7_GRANT = (
    "hfss_agent.broker",
    "hfss_agent.preflight",
    "hfss_agent.inspect",
    "hfss_agent.validate_native",
    "hfss_agent.snapshot",
    "hfss_agent.gating",
    "hfss_agent.metrics",
    "hfss_agent.findings",
    "hfss_agent.contract",
)

# Everything else this package may name, each with its reason.
#   * ``hfss_agent.server`` -- its own submodules.
#   * ``hfss_agent.session`` -- NOT in §5's Layer-7 list, and permitted because
#     the composition root must construct the ``Session`` the broker wraps.
#     Nothing else here touches it; the file scoping below is what keeps that
#     true.
#   * ``mcp`` -- the SDK. The first third-party runtime import outside adapter.
#   * ``__future__`` -- annotations.
#   * ``argparse`` -- the ``--adapter`` flag.
#   * ``sys`` -- stderr diagnostics ONLY (see the stdout audit, which forbids
#     writing to stdout anywhere in this package).
#   * ``collections.abc`` / ``typing`` / ``dataclasses`` -- annotations and the
#     two frozen dataclasses.
#   * ``functools`` -- ``wraps`` on the serialization decorator, load-bearing
#     because the SDK derives each tool's input schema from the wrapped
#     signature.
#   * ``threading`` -- the process-wide dispatch RLock.
#
# REMOVED IN PART 10, recorded because the removal is the interesting part:
# ``importlib.metadata`` was permitted for "reading this package's own
# version for the handshake". That read was a SECOND implementation of
# ``preflight.probes.real_wrapper_version``, and the two disagreed on every
# failure mode (see app.py). The handshake version now comes from
# ``REAL_PROBES``, so nothing here imports it -- and the live-use check below
# is what noticed, which is the whole reason that check exists.
_ALLOWED_IMPORT_ROOTS = (
    *_LAYER_7_GRANT,
    "hfss_agent.server",
    "hfss_agent.session",
    "mcp",
    "__future__",
    "argparse",
    "collections.abc",
    "dataclasses",
    "functools",
    "sys",
    "threading",
    "typing",
)

# CONSIDERED AND REFUSED, in writing, so each absence is a decision:
#   * ``os`` -- REFUSED. Nothing here may touch the filesystem or the
#     environment. The data directory is resolved by broker's ``locations``,
#     which owns the one permitted ``makedirs`` site in the repo; adapter
#     selection reads a CLI flag, deliberately not an environment variable.
#   * ``pathlib``, ``tempfile``, ``shutil``, ``json`` -- REFUSED. File I/O is
#     broker's alone (the §5 invariant), and serialization is the contract's.
#   * ``logging`` -- REFUSED for now. Nothing in this package logs, and the
#     first logging configuration in the repo is a decision that needs its own
#     review: under stdio transport a handler attached to stdout would corrupt
#     the protocol stream, and a root-logger call from a dependency could too.
#   * ``asyncio`` -- REFUSED. The SDK owns the event loop; handlers are
#     synchronous by measurement (an ``async def`` handler stalls the transport
#     completely, 0.81 s against 0.02 s for the lock).
#   * ``subprocess`` -- REFUSED, and it is the charter's no-arbitrary-execution
#     rule at this layer.
_CONSIDERED_AND_REFUSED = (
    "os",
    "pathlib",
    "tempfile",
    "shutil",
    "json",
    "logging",
    "asyncio",
    "subprocess",
)

# --- the two file-scoped exceptions ------------------------------------------
#
# EXCEPTION 1: ``hfss_agent.adapter``. Something must construct the adapter the
# session wraps, and the composition root is the only layer that knows which one
# this process should get. Confined to the two files that do that work, so a
# tool handler cannot reach an adapter even by accident.
# Posix paths relative to ``server/`` -- see the module docstring on why not
# basenames.
_ADAPTER_PERMITTED_IN = frozenset({"adapter_selection.py", "composition.py"})

# EXCEPTION 2: ``hfss_agent.broker.files.locations``, in composition.py only.
#
# WHY THE DEEP IMPORT RATHER THAN A RE-EXPORT, which is the obvious alternative:
# ``default_intent_path`` and ``default_audit_log_path`` CREATE DIRECTORIES as a
# side effect -- they call ``ensure_data_dir``, which owns the one permitted
# ``makedirs`` site in the repo -- and their names do not say so. Re-exporting
# them from ``hfss_agent.broker`` would promote two directory-creating functions
# into the surface every module in the repo already imports, inviting a call
# from somewhere that must not touch the disk at all. A file-scoped exception
# keeps the blast radius at the one file that legitimately resolves a default
# path, and makes the reach a reviewed entry here rather than an invisible
# convenience.
_LOCATIONS_MODULE = "hfss_agent.broker.files.locations"
_LOCATIONS_PERMITTED_IN = frozenset({"composition.py"})  # relative to server/


def _under(module: str, root: str) -> bool:
    return module == root or module.startswith(root + ".")


def _imported_modules(source: str) -> list[str]:
    """Every module an import NAMES, plus the dotted path each imported name
    would resolve to as a submodule -- both, in their own spelling.

    WHY BOTH, AND IT IS THE HALF THAT WAS MISSING. ``from X import Y`` used to
    be reported as ``X`` alone, so ``from hfss_agent.broker.files import
    locations`` came back as ``hfss_agent.broker.files`` -- which is NOT under
    ``hfss_agent.broker.files.locations`` and IS under the broad
    ``hfss_agent.broker`` grant, so the locations exception was bypassed
    entirely. Measured: planted in ``app.py``, every boundary test stayed
    green. Reporting ``X.Y`` as well is what lets a deep module be scoped no
    matter which spelling reaches it.

    The cost is that a CLASS or function name also appears as a dotted path --
    ``from hfss_agent.broker import Broker`` yields ``hfss_agent.broker`` and
    ``hfss_agent.broker.Broker``. That is deliberate and harmless: this
    function cannot tell a submodule from an attribute without importing, and
    an extra name under an already-permitted root changes no verdict. It only
    ever ADDS a candidate for a scoping rule to catch.

    A RELATIVE IMPORT IS REPORTED IN ITS SOURCE SPELLING AND IS THEREBY REFUSED:
    ``from ..broker import Broker`` comes back as ``"..broker"`` and ``from .
    import x`` as ``"."``, neither of which is under any allowed root. This is
    W-9's fix inherited, not the eight siblings' ``node.level == 0`` defect,
    which dropped relative imports before the list was consulted.

    Blanket rejection rather than resolution, for W-9's stated reason: resolving
    ``..broker`` needs the importing file's package position, which this
    function does not have and must not need -- half its callers are planted
    strings with no file position at all.
    """
    modules: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            modules.append(base)
            # ``from . import x`` gives a base of ``"."``; joining with
            # another dot would spell ``"..x"``, a DIFFERENT relative depth.
            separator = "" if base.endswith(".") else "."
            modules += [base + separator + alias.name for alias in node.names]
    return modules


def _relative(path: Path) -> str:
    """A server source's identity for scoping: posix, relative to ``server/``.

    ``as_posix`` because CI runs on Ubuntu as well as Windows and a raw
    ``str(PurePath)`` yields backslashes on one of them, so a permitted-set
    membership test would pass on Linux and fail on Windows.
    """
    return path.relative_to(_SERVER).as_posix()


def _server_sources() -> list[Path]:
    files = sorted(_SERVER.rglob("*.py"))
    assert files, f"no server sources found under {_SERVER}"
    return files


def _offenders_for(source: str, relative_path: str) -> list[str]:
    """Imports in ``source`` that this file is not permitted to make.

    ``relative_path`` is the file's posix path RELATIVE TO ``server/``, not
    its basename: a subdirectory must not inherit a file-scoped exception by
    reusing a permitted name.
    """
    bad = []
    for module in _imported_modules(source):
        if _under(module, "hfss_agent.adapter"):
            if relative_path not in _ADAPTER_PERMITTED_IN:
                bad.append(module)
            continue
        if _under(module, _LOCATIONS_MODULE):
            if relative_path not in _LOCATIONS_PERMITTED_IN:
                bad.append(module)
            continue
        if not any(_under(module, root) for root in _ALLOWED_IMPORT_ROOTS):
            bad.append(module)
    return bad


def test_server_imports_only_the_allowed_roots() -> None:
    """READ THE PER-FILE ROWS, NOT JUST THE VERDICT."""
    offenders = {}
    for path in _server_sources():
        relative = _relative(path)
        bad = _offenders_for(path.read_text(encoding="utf-8"), relative)
        if bad:
            offenders[relative] = sorted(set(bad))
    assert not offenders, (
        f"server imported modules outside the Layer-7 allow-list: {offenders}. "
        "Add the root above WITH ITS REASON, or route through a module that "
        "already has it."
    )


def test_the_adapter_exception_is_file_scoped_not_package_wide() -> None:
    """THE ASSERTION THAT MAKES THE EXCEPTION AN EXCEPTION.

    ``app.py`` and ``__main__.py`` must be structurally unable to reach an
    adapter. A package-wide permission would let a tool handler take one
    directly, bypassing session, broker, tier gate and audit log in a single
    import -- which is the whole point of there being layers.
    """
    reaching = {}
    for path in _server_sources():
        relative = _relative(path)
        if relative in _ADAPTER_PERMITTED_IN:
            continue
        found = [
            module
            for module in _imported_modules(path.read_text(encoding="utf-8"))
            if _under(module, "hfss_agent.adapter")
        ]
        if found:
            reaching[relative] = sorted(found)
    assert not reaching, f"adapter reached outside its two permitted files: {reaching}"


def test_the_permitted_files_actually_use_their_exceptions() -> None:
    """A permission with no use behind it is a phantom entry that makes the
    list look more permissive than the code is (W-10's live-use rule)."""
    selection = (_SERVER / "adapter_selection.py").read_text(encoding="utf-8")
    composition = (_SERVER / "composition.py").read_text(encoding="utf-8")
    assert any(
        _under(m, "hfss_agent.adapter") for m in _imported_modules(selection)
    ), "adapter_selection.py no longer imports adapter; narrow the exception"
    assert any(
        _under(m, "hfss_agent.adapter") for m in _imported_modules(composition)
    ), "composition.py no longer imports adapter; narrow the exception"
    assert any(
        _under(m, _LOCATIONS_MODULE) for m in _imported_modules(composition)
    ), "composition.py no longer imports locations; drop the exception"


def test_the_locations_exception_is_confined_to_composition() -> None:
    reaching = {}
    for path in _server_sources():
        relative = _relative(path)
        if relative in _LOCATIONS_PERMITTED_IN:
            continue
        found = [
            m
            for m in _imported_modules(path.read_text(encoding="utf-8"))
            if _under(m, _LOCATIONS_MODULE)
        ]
        if found:
            reaching[relative] = sorted(found)
    assert not reaching, (
        f"broker.files.locations reached outside composition: {reaching}"
    )


def test_the_refused_modules_are_actually_refused() -> None:
    """Each refusal is a decision with a reason above; this proves the
    allow-list mechanism actually excludes them rather than the comment being
    aspirational."""
    for module in _CONSIDERED_AND_REFUSED:
        assert not any(
            _under(module, root) for root in _ALLOWED_IMPORT_ROOTS
        ), f"{module!r} is admitted by the allow-list despite being refused"


def test_every_permitted_stdlib_root_has_a_live_use() -> None:
    """The nine Layer-7 grants are permitted by design even when unused (four
    are, today). Everything else must be earned -- an unused stdlib permission
    is a widened surface nobody is paying for."""
    used = set()
    for path in _server_sources():
        used.update(_imported_modules(path.read_text(encoding="utf-8")))
    earned = set(_ALLOWED_IMPORT_ROOTS) - set(_LAYER_7_GRANT) - {"hfss_agent.server"}
    unused = sorted(
        root for root in earned if not any(_under(m, root) for m in used)
    )
    assert not unused, (
        f"permitted but never imported: {unused}. Remove the permission or the "
        "list overstates what this package needs."
    )


def test_the_detector_refuses_a_relative_import() -> None:
    """THE POSITIVE LIMB. The eight sibling audits shipped a ``node.level == 0``
    filter that made planted relative imports invisible; this proves the fix is
    present here rather than assuming it was inherited."""
    planted = "from ..adapter.fake import FakeAdapter\n"
    # Both spellings are reported (see ``_imported_modules``), and neither is
    # under any allowed root, so both are refused.
    assert _imported_modules(planted) == [
        "..adapter.fake",
        "..adapter.fake.FakeAdapter",
    ]
    assert _offenders_for(planted, "app.py") == [
        "..adapter.fake",
        "..adapter.fake.FakeAdapter",
    ]
    # And ``from . import x`` -- the shape with no module name at all. The
    # joined form must stay at ONE dot: ``".composition"``, not ``"..composition"``,
    # which would name a different package level.
    assert _imported_modules("from . import composition\n") == [
        ".",
        ".composition",
    ]
    assert _offenders_for("from . import composition\n", "composition.py") == [
        ".",
        ".composition",
    ]


def test_the_detector_refuses_a_forbidden_absolute_import() -> None:
    for planted in ("import os\n", "import subprocess\n", "from pathlib import Path\n"):
        assert _offenders_for(planted, "app.py"), f"{planted!r} was not refused"


def test_the_detector_admits_what_it_should() -> None:
    """A detector that refused everything would pass every negative test above
    while making the audit useless."""
    assert _offenders_for("from hfss_agent.broker import Broker\n", "app.py") == []
    mcp_line = "from mcp.server.mcpserver import MCPServer\n"
    assert _offenders_for(mcp_line, "app.py") == []
    assert _offenders_for("import sys\n", "__main__.py") == []
    # The exception, admitted in its file and refused outside it.
    adapter_line = "from hfss_agent.adapter import Adapter\n"
    assert _offenders_for(adapter_line, "composition.py") == []
    assert _offenders_for(adapter_line, "app.py") == [
        "hfss_agent.adapter",
        "hfss_agent.adapter.Adapter",
    ]


def test_a_deep_import_spelling_still_reaches_the_locations_scoping() -> None:
    """F5's POSITIVE LIMB. The bypass that existed, now refused.

    ``from hfss_agent.broker.files import locations`` names a module whose own
    spelling (``hfss_agent.broker.files``) sits under the broad
    ``hfss_agent.broker`` grant, so before Part 10 it was admitted anywhere and
    the directory-creating ``locations`` module was reachable from a tool
    handler. Both spellings must now be caught, and BOTH must still be
    admitted in the one file the exception is for.
    """
    deep = "from hfss_agent.broker.files import locations\n"
    direct = "from hfss_agent.broker.files.locations import default_data_dir\n"
    for spelling in (deep, direct):
        assert _offenders_for(spelling, "app.py"), (
            f"{spelling!r} reached locations from app.py without being refused"
        )
        assert _offenders_for(spelling, "composition.py") == []
    # The grant it used to hide behind is still a grant: an ordinary broker
    # import must not become an offender.
    assert _offenders_for("from hfss_agent.broker import Broker\n", "app.py") == []
    sibling = "from hfss_agent.broker.files import errors\n"
    assert _offenders_for(sibling, "app.py") == []


def test_a_subdirectory_does_not_inherit_a_file_scoped_exception() -> None:
    """F4's POSITIVE LIMB. Scoping is by relative path, so a name collision in
    a subdirectory inherits nothing.

    Measured before the fix: a real ``server/handlers/composition.py`` importing
    ``FakeAdapter`` and ``default_data_dir`` left every audit green.
    """
    adapter_line = "from hfss_agent.adapter.fake import FakeAdapter\n"
    locations_line = "from hfss_agent.broker.files import locations\n"
    for line in (adapter_line, locations_line):
        assert _offenders_for(line, "composition.py") == [], (
            "the real composition.py must keep its exceptions"
        )
        assert _offenders_for(line, "handlers/composition.py"), (
            f"{line!r} was admitted in a subdirectory that merely reuses the "
            "permitted basename"
        )


def test_no_relative_import_exists_in_the_package_today() -> None:
    """Enforceable because already true, measured rather than assumed."""
    relative = {}
    for path in _server_sources():
        found = [
            m
            for m in _imported_modules(path.read_text(encoding="utf-8"))
            if m.startswith(".")
        ]
        if found:
            relative[path.name] = found
    assert not relative, f"relative imports found: {relative}"
