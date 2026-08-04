"""Layer-5 import audit (W-8): the snapshot module imports ``contract`` and
nothing else — no broker, no session, no adapter, no pyaedt, no Layer-4 sibling,
and nothing that reaches the filesystem, the network, or the OS.

System Design §5 places snapshot at Layer 5 with a CONTRACT-ONLY grant (corrected
ADR-28; the layer number reflects ASSEMBLY order, not imports), and §4 homes
import audits in this ``tests/boundary/`` suite. Parse each glob-discovered
source file's imports statically (AST, no exec) — the approach that can assert
imports are *only* the allowed roots, not merely that a denylisted module is
absent. No new mechanism is introduced; the five module audits must stay
comparable line for line, because the day they diverge is the day nobody can tell
whether a difference is a decision or a drift.

FOLLOWS W-7's POLARITY, WITHOUT W-7's NAMED FILE LIST, AND BOTH HALVES ARE
DELIBERATE. The polarity is W-7's: constrained by default, with the constrained
files discovered by glob, and NO file exempt from anything. The named list is
absent because there is no gap for one to close. W-7 needs
``_PURE_FORMULA_FILES`` precisely because its module-wide audit ALLOWS
``hfss_agent.broker`` (§5 grants ``metrics -> broker``), so a formula could
quietly reach the broker and the coarse test could never object; W-11 needs
``_HOST_READING_FILES`` because exactly one of its files may read machine state.
Under a contract-only grant W-8 has neither hole: the module-wide check already
IS the strictest per-file check that could be written, so a per-file clone of it
would be a literal duplicate. Adding one would also create a list that a future
file could be added to, which is the mechanism by which an exemption appears.

THE SUBSTANTIVE DIFFERENCE FROM EVERY OTHER MODULE AUDIT IS THE BROKER. W-5, W-6,
W-7 and W-11 all ALLOW ``hfss_agent.broker``; this file FORBIDS it, and that
inversion is the entire content of the contract-only grant. It gets its own named
test below rather than living only inside the blanket denylist, so that losing it
in a refactor requires a test named for the thing it protects to die visibly.

WHY THIS AUDIT IS TWO INDEPENDENT ASSERTIONS AND NOT ONE. The ``hfss_agent``-root
axis and the host-capability axis do not collapse into each other, in either
direction. ``import os`` is INVISIBLE to the root checks — it is not an
``hfss_agent`` module, so the allowed-roots test never considers it and the
denylist never matches it — and ``open`` is a builtin that needs no import at
all, so it is invisible to both. Conversely a planted ``from hfss_agent.broker
import Broker`` is invisible to the host check, because ``hfss_agent.broker`` is
under none of the host-capable roots. Each axis is the only thing that can see
its own violation, and the meta-tests at the bottom of this file assert that
mutual blindness directly so the two can never be silently merged.

WHERE THIS OVERLAPS AN EXISTING AUDIT, named so a reader finding both does not
think one is redundant. ``test_file_io_audit.py`` is repo-wide and
glob-discovered, so it already covers every file added under ``src/`` — including
this package — and it independently catches a planted ``open()`` here (verified
by running it, not by reading it). The overlap is on that one axis only: that
audit targets file CONTENT and NAMESPACE mutation, and says nothing about
``socket``, ``urllib``, ``http``, ``sys``, ``platform`` or ``importlib``, all of
which this file forbids. The narrower copy stays for the reason W-11 keeps its
own duplicate: it fails closest to the edit, and it is named for the module whose
invariant it protects rather than for the repo's.

THE PEER SYMMETRY, already complete in the other direction. Six existing audits
forbid ``hfss_agent.snapshot`` (broker, session, inspect, validate_native,
metrics, preflight), so the reverse bans that make ``SnapshotAssemblyError``'s
fourth duplication structurally unavoidable rather than lazy are already in place
and need no edit here. One asymmetry is NOT closed and is flagged rather than
fixed: ``test_adapter_import_audit.py`` audits only the AEDT API and constrains
no ``hfss_agent`` root at all, so ``adapter -> hfss_agent.snapshot`` would pass
CI today. Widening it is out of scope for this step.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SNAPSHOT = Path(__file__).resolve().parents[2] / "src" / "hfss_agent" / "snapshot"

# The hfss_agent roots the snapshot module may depend on (§5 Layer 5).
# ``hfss_agent.snapshot`` is itself allowed (a package importing its own
# submodules is not a boundary break). ``hfss_agent.contract`` is matched by
# PREFIX, which admits ``hfss_agent.contract.tool_io`` — see
# ``test_snapshot_may_name_contract_tool_io_types`` for why that is the decision
# rather than an accident of how ``_under`` happens to work.
_ALLOWED_HFSS_ROOTS = (
    "hfss_agent.contract",
    "hfss_agent.snapshot",
)

# Roots that must never appear: the AEDT API (both name shapes, ADR-17
# decision 8), the BROKER (the inversion this whole file exists for), the two
# lower layers below it, the four Layer-4 modules whose outputs W-8 receives as
# DATA rather than fetches, and every layer it sits below or beside.
#
# ``hfss_agent.inspect`` and ``hfss_agent.validate_native`` are forbidden even
# though W-8 consumes their results, and that is the point rather than a tension:
# it consumes the RESULTS, which are ``contract.tool_io`` types, and never the
# producers. A W-8 that could call ``inspect_design`` would be fetching its own
# inputs, which is exactly the composition §1.1 assigns to the server layer.
_FORBIDDEN_ROOTS = (
    "pyaedt",
    "ansys.aedt",
    "hfss_agent.broker",
    "hfss_agent.adapter",
    "hfss_agent.session",
    "hfss_agent.server",
    "hfss_agent.inspect",
    "hfss_agent.validate_native",
    "hfss_agent.metrics",
    "hfss_agent.preflight",
    "hfss_agent.gating",
    "hfss_agent.findings",
)

# Modules that would let a file reach the machine on its own: the filesystem, the
# environment, the interpreter's own identity, installed metadata, the network, a
# subprocess. None is an hfss_agent module, so the root lists above cannot
# express this; it is checked separately against the same parsed import list.
#
# CONTENT FOLLOWS W-11's LIST, WHICH IS THE BROADEST EXISTING ONE, and the choice
# is deliberate rather than copied: W-11 legitimately needs ONE host-reading file
# and W-7 legitimately generates the strings that become files, whereas W-8 has
# no host business whatsoever. The module with the least reason to touch the
# machine gets the strictest list, and it costs nothing because nothing here
# wants any of these.
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

# CONSIDERED AND PERMITTED, written down rather than left as an absence. Both of
# these are non-deterministic — they return something different on each call —
# which is the property that makes a reader wonder whether they belong in a
# module whose output crosses the engine seam. They do, and the permission is
# recorded positively because an unlisted import is indistinguishable from an
# unconsidered one.
#
#   * ``datetime`` — W-8 stamps ``created_at`` with an inline
#     ``datetime.now(timezone.utc)``, exactly as W-5 and W-6 stamp ``read_at``
#     and ``validated_at``. Reading a clock is already the established shape for
#     an assembler in this package.
#   * ``uuid`` — W-8 mints ``snapshot_id`` as ``"snap-" + uuid4().hex``. It draws
#     from ``os.urandom``, reads no user data, opens no file, and returns no host
#     fact. And decisively: a module that already calls a clock is ALREADY
#     non-deterministic and ALREADY reaching a host primitive, so a random
#     identifier is the same category rather than a new one. ``uuid1`` would be a
#     different matter — it embeds the MAC address — but nothing here may use it,
#     and a leaked MAC would surface in the no-handles property test rather than
#     here.
#
# Asserted below as absent from ``_HOST_CAPABLE_MODULES``, so narrowing this
# permission means editing a test that states its own reasoning.
_CONSIDERED_AND_PERMITTED = ("datetime", "uuid")


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


def _snapshot_sources() -> list[Path]:
    files = sorted(_SNAPSHOT.rglob("*.py"))
    assert files, f"no snapshot source files found under {_SNAPSHOT}"
    return files


def test_snapshot_imports_only_contract() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _snapshot_sources():
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
        f"snapshot imported hfss_agent modules outside contract: {offenders}"
    )


def test_snapshot_imports_nothing_forbidden() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _snapshot_sources():
        modules = _imported_modules(path.read_text(encoding="utf-8"))
        bad = [
            module
            for module in modules
            if any(_under(module, root) for root in _FORBIDDEN_ROOTS)
        ]
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"snapshot imported forbidden modules: {offenders}"


def test_snapshot_does_not_import_the_broker() -> None:
    """THE INVERSION, named so it cannot be lost in a refactor.

    Every other module audit in this suite ALLOWS ``hfss_agent.broker``: §5
    grants it to inspect, validate_native, metrics and preflight, and the broker
    is how each of those reaches HFSS at all. W-8 is the one module for which the
    broker is forbidden, and that single difference IS the contract-only grant —
    a W-8 holding a broker could dispatch, which means it could fetch its own
    inputs, which means the artifact crossing the engine seam would no longer be
    provably a function of what a caller handed in.

    A regression here would still be caught by the two blanket tests above. It
    would not be NAMED, and the name is what a maintainer reads when deciding
    whether a failing assertion is protecting something or merely restating a
    list. Compare ``test_metrics_does_not_reach_session_or_adapter_directly``,
    which makes the same move for the claim ADR-20 decision 1 makes.
    """
    assert "hfss_agent.broker" in _FORBIDDEN_ROOTS
    assert not any(_under("hfss_agent.broker", root) for root in _ALLOWED_HFSS_ROOTS)
    for path in _snapshot_sources():
        modules = _imported_modules(path.read_text(encoding="utf-8"))
        assert not [
            module for module in modules if _under(module, "hfss_agent.broker")
        ], (
            f"{path.name} imports the broker; W-8 receives its inputs as data and "
            "dispatches nothing — a broker here would let the snapshot fetch what "
            "it is supposed to be handed"
        )


def test_snapshot_may_name_contract_tool_io_types() -> None:
    """WHAT "contract ONLY" ADMITS — the PREFIX reading, decided at Step 2.5b.

    §5's Layer-5 line reads "snapshot (W-8) -> contract ONLY", and there are two
    readings of it. The narrow one admits only the §2 data-model schemas; the
    prefix one admits the whole ``hfss_agent.contract`` package, ``tool_io``
    included. The prefix reading is the decision, for three reasons:

      1. The constraint is about CAPABILITIES, not about which data shapes W-8
         may name. Everything under ``contract`` is an inert pydantic model
         carrying validation and nothing else (W-12), so importing one grants no
         ability to reach HFSS, a file, the network or the OS — which is the
         entire thing the Layer-5 grant is protecting.
      2. The narrow reading would make ADR-28 decision 8 UNIMPLEMENTABLE.
         "``SelectionRefused`` gets no representation on any field. W-8 raises."
         — and ``SelectionRefused`` is a ``tool_io`` type, as are
         ``CannotEvaluate``, ``InspectionResult``, ``NativeValidationBlock``,
         ``SessionStatus`` and ``SelectionChain``. A W-8 that may not name them
         cannot check for them, so it could not raise on them, so the decision
         could not be carried out. Being unable to express a decision the same
         ADR makes is the tell that the reading is wrong.
      3. It is also what the existing audits already do. Every sibling in this
         suite matches allowed roots by dotted prefix, so ``hfss_agent.contract``
         has always admitted its own submodules everywhere else; a special
         narrower rule here would be the novelty, not the prefix.

    Asserted directly rather than left to ``_under``'s behaviour, so a future
    reader cannot narrow the grant silently and break the entry point.
    """
    assert _under("hfss_agent.contract.tool_io", "hfss_agent.contract")
    assert _under(
        "hfss_agent.contract.tool_io.preflight_session", "hfss_agent.contract"
    )
    assert any(
        _under("hfss_agent.contract.tool_io", root) for root in _ALLOWED_HFSS_ROOTS
    )
    # And the grant stays a grant over ``contract`` specifically: a same-shaped
    # name under any other root is still refused, so the prefix rule cannot be
    # read as "anything with a dot in it is fine".
    assert not any(
        _under("hfss_agent.broker.registry", root) for root in _ALLOWED_HFSS_ROOTS
    )
    assert any(
        _under("hfss_agent.broker.registry", root) for root in _FORBIDDEN_ROOTS
    )


def test_no_snapshot_file_reaches_the_host() -> None:
    """No file, environment, network, or process handle is reachable from W-8.

    Discovered by glob with NO exemption, which is the difference from W-11: that
    module has one file that legitimately reads machine state, and W-8 has none.
    See the module docstring for why this assertion does not collapse into the
    root checks above — ``import os`` is invisible to both of them.
    """
    offenders: dict[str, list[str]] = {}
    for path in _snapshot_sources():
        bad = [
            module
            for module in _imported_modules(path.read_text(encoding="utf-8"))
            if any(_under(module, root) for root in _HOST_CAPABLE_MODULES)
        ]
        if bad:
            offenders[path.name] = bad
    assert not offenders, (
        f"snapshot files import host-capable modules: {offenders}. W-8 composes "
        "data it was handed and reaches nothing"
    )


def test_no_snapshot_file_calls_open() -> None:
    """``open`` is a builtin and needs no import, so the module lists above cannot
    see it. Only the broker writes files, and W-8 does not even produce a payload
    for one — it returns a ``DesignSnapshot`` object and lets its caller decide
    what to do with it."""
    for path in _snapshot_sources():
        called = {
            node.func.id
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "open" not in called, (
            f"{path.name} calls open(); every write is the broker's"
        )


def test_the_clock_and_the_id_source_are_considered_and_permitted() -> None:
    """``datetime`` and ``uuid`` are permitted ON PURPOSE, and this is the record.

    Both are non-deterministic, which is the property that makes a reader wonder
    whether they belong in the module whose output crosses the engine seam. The
    reasoning lives in the comment on ``_CONSIDERED_AND_PERMITTED`` above; what
    this test adds is that narrowing the permission requires deleting an
    assertion that states its own justification, rather than quietly adding a
    name to a list.

    ``uuid1`` is the member of that module nothing here may use — it embeds the
    MAC address — and it is deliberately NOT guarded here: an import audit sees
    module names, not attribute access, so a check for it would be a check this
    file cannot actually make. The property test over the assembled tree is where
    a leaked host fact would surface.
    """
    for module in _CONSIDERED_AND_PERMITTED:
        assert not any(
            _under(module, root) for root in _HOST_CAPABLE_MODULES
        ), f"{module!r} is permitted for W-8 and must not be host-capable-banned"
        assert not _under(module, "hfss_agent")
        assert not any(_under(module, root) for root in _FORBIDDEN_ROOTS)


def test_audit_would_catch_a_forbidden_import() -> None:
    # The audit is only meaningful if it actually detects a violation — in both
    # AEDT name shapes, for the broker inversion this file exists for, for the
    # two lower layers, and for the Layer-4 modules whose outputs W-8 receives as
    # data rather than fetches.
    assert _imported_modules("import pyaedt") == ["pyaedt"]
    assert _imported_modules("from ansys.aedt.core import Hfss") == ["ansys.aedt.core"]
    assert _imported_modules("from hfss_agent.broker import Broker") == [
        "hfss_agent.broker"
    ]
    assert _imported_modules("from hfss_agent.session import Session") == [
        "hfss_agent.session"
    ]
    assert _imported_modules("from hfss_agent.server import app") == [
        "hfss_agent.server"
    ]
    for forbidden in ("broker", "adapter", "session", "inspect", "validate_native"):
        assert any(
            _under(f"hfss_agent.{forbidden}", root) for root in _FORBIDDEN_ROOTS
        ), f"hfss_agent.{forbidden} must be forbidden to W-8"
    assert any(_under("ansys.aedt.core", root) for root in _FORBIDDEN_ROOTS)


def test_the_two_axes_are_blind_to_each_other() -> None:
    """The proof that the root check and the host check are not duplicates.

    Asserted in BOTH directions, because a one-directional check would leave the
    other collapse available. A host-capable import is invisible to the root
    lists (it is not an ``hfss_agent`` module at all), and an ``hfss_agent``
    violation is invisible to the host list (it is under none of those roots). So
    each assertion is the only thing that can see its own violation, and merging
    them would silently drop whichever half the survivor cannot see.
    """
    for bypass in ("import os", "import platform", "from pathlib import Path"):
        modules = _imported_modules(bypass)
        assert any(
            any(_under(module, root) for root in _HOST_CAPABLE_MODULES)
            for module in modules
        ), f"{bypass!r} must be caught by the host-state check"
        assert not any(_under(module, "hfss_agent") for module in modules), (
            f"{bypass!r} is invisible to the root checks, which is why the "
            "host check exists separately"
        )
    for bypass in ("from hfss_agent.broker import Broker", "import hfss_agent.session"):
        modules = _imported_modules(bypass)
        assert not any(
            any(_under(module, root) for root in _HOST_CAPABLE_MODULES)
            for module in modules
        ), (
            f"{bypass!r} is invisible to the host check, which is why the root "
            "checks exist separately"
        )
        assert any(
            any(_under(module, root) for root in _FORBIDDEN_ROOTS)
            for module in modules
        ), f"{bypass!r} must be caught by the root checks"
    # And the imports W-8 legitimately uses trip neither axis.
    for allowed in ("datetime", "uuid", "typing", "collections.abc", "__future__"):
        assert not any(_under(allowed, root) for root in _HOST_CAPABLE_MODULES)
        assert not any(_under(allowed, root) for root in _FORBIDDEN_ROOTS)


def test_stdlib_names_are_not_caught_by_the_hfss_agent_bans() -> None:
    """``hfss_agent.inspect`` is banned; the stdlib ``inspect`` is not.

    Every hfss_agent entry in the two root tuples is fully qualified, and
    ``_under`` matches on equality or a dotted-prefix boundary — so a bare stdlib
    name that happens to collide with one of our module names cannot trigger it.
    ``inspect`` is the live collision (W-5's package is named after it);
    ``contextlib`` stands in for the general case.
    """
    for stdlib_name in ("inspect", "inspect.signature", "contextlib", "types"):
        assert not any(_under(stdlib_name, root) for root in _FORBIDDEN_ROOTS), (
            f"the stdlib module {stdlib_name!r} must not trip the hfss_agent bans"
        )
    # And the ban it could have been confused with does still fire.
    assert any(_under("hfss_agent.inspect", root) for root in _FORBIDDEN_ROOTS)
    # The audits only ever consider hfss_agent-rooted modules for the
    # allowed-roots check, so a stdlib import is not an "outside contract"
    # offender either.
    assert not _under("inspect", "hfss_agent")
