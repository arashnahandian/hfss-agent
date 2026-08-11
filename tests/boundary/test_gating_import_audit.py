"""Layer-1 import audit (W-9): gating imports ``contract``, its own submodules,
and NOTHING ELSE — enforced as an ALLOW-LIST over every import, not as a denylist.

READ THE PER-FILE ROWS, NOT JUST THE VERDICT. This file's assertions report
offenders as ``{filename: [modules]}`` for exactly that reason, and it is written
at the top because this audit is where the lesson was learned: the ``gates.py``
import cycle in Part 4 was present in an AST dump that had already been generated
and read only for its summary line. A green audit says nothing was violated; it
does not say the shape is what you think it is. When this file changes, read what
it prints, not whether it passed.

WHY AN ALLOW-LIST, AND WHY THAT DIVERGES FROM FIVE SIBLINGS. W-8's docstring warns
that "the five module audits must stay comparable line for line, because the day
they diverge is the day nobody can tell whether a difference is a decision or a
drift." THIS IS A DECISION, AND HERE IS THE MEASUREMENT BEHIND IT.

W-8's design has two axes: allowed/forbidden ``hfss_agent`` roots, and a
fifteen-entry host-capable denylist. Ported to gating verbatim and measured
against the imports that would actually hurt here, EIGHT PASS SILENTLY:

    import random     PASSES     import datetime    PASSES
    import time       PASSES     import uuid        PASSES
    import secrets    PASSES     import itertools   PASSES
    import hashlib    PASSES     import functools   PASSES

None is an ``hfss_agent`` module, so the root checks never consider it; none
reaches a file, socket, environment or process, so the host check does not either.
They are PURE COMPUTATION, which is precisely ADR-29 dec. 23's recorded gap in
that design — and for W-9 the stakes are higher than for W-8, because two of them
are the specific things this module must never hold.

THE STAKES, STATED PLAINLY. This audit is what retroactively makes ADR-30 dec. 2
TRUE. That decision dropped ``evaluated_at`` from ``FindingProvenance`` on the
grounds that "minting one means calling a clock from the module whose determinism
is what makes it testable" — an argument that, until this file existed, rested on
nothing enforceable. And Part 3 MEASURED that the behavioural determinism test
cannot close the gap: ``time.time()`` returns a float near 1.75e9, where float64
carries about sixteen significant digits, so two calls microseconds apart can
serialize identically and the test stays green. ``random.random()`` and
``time.perf_counter_ns()`` are caught; a plain clock is not. SO THIS AUDIT IS THE
PRIMARY GUARD, NOT THE BACKSTOP.

A DENYLIST CANNOT DO THIS JOB. It must enumerate every non-deterministic or
capability-bearing module in the standard library and will still miss the next
one, because the failure mode is an import nobody anticipated. An allow-list fails
CLOSED on exactly that case: a module not named below does not reach this package
without an edit to this line, in a diff someone reviews. The measured union across
all seven gating files is three roots, so the allow-list costs nothing today —
which is what makes it affordable to adopt before it is needed rather than after.

TWO OF W-8's TEN TESTS DO NOT SURVIVE THE POLARITY CHANGE, and are deliberately
NOT ported hollow:

  * ``test_the_two_axes_are_blind_to_each_other`` — MEANINGLESS HERE. It proves
    two axes cannot be merged without losing coverage. There is one axis. Porting
    it would leave a test asserting a property of a design this file rejected.
  * ``test_stdlib_names_are_not_caught_by_the_hfss_agent_bans`` — INVERTED. Under
    a denylist, the stdlib ``inspect`` must not trip the ban on
    ``hfss_agent.inspect``. Under an allow-list the stdlib ``inspect`` IS refused,
    correctly, so the property it protected no longer exists. What replaces it is
    the opposite hazard, which an allow-list genuinely has:
    ``test_the_allowed_prefix_does_not_over_admit``.

FOUR THINGS AN IMPORT LIST CANNOT SEE, each with its own test below: builtins
that need no import (``eval``, ``open``); gate-to-gate imports, which are legal
under any flat root rule; branching on a key inside
``FreshnessEvidence.available_signals``, which Part 3b measured to be uncatchable
behaviourally because the key space is unbounded by design; and STATE THAT
SURVIVES BETWEEN CALLS — a module-level counter or memo, or a mutable default
argument — which makes a gate non-deterministic with zero imports at all. That
last one is the same determinism axis as the allow-list, arriving through a
different syntactic door.

ONE HAZARD IS FLAGGED RATHER THAN GUARDED, so its absence is not read as an
oversight: a CLASS ATTRIBUTE mutated inside a method also survives between calls,
and the scan does not catch it. This package contains no classes, so guarding it
would be a check derived from imagination rather than from a producer — ADR-28
dec. 4's rule. The mutable-default form IS guarded, because
``target_coverage.evaluate(snapshot, target_frequency_hz=None)`` means the
construct already exists here and the hazard is one keystroke away.
"""

from __future__ import annotations

import ast
from pathlib import Path

_GATING = Path(__file__).resolve().parents[2] / "src" / "hfss_agent" / "gating"

# THE COMPLETE SET OF IMPORT ROOTS THIS PACKAGE MAY NAME. Matched by dotted
# prefix, so ``hfss_agent.contract.tool_io`` is admitted and
# ``hfss_agent.contracts`` is not — see the two prefix tests below, which pin both
# directions.
#
# ``hfss_agent.gating`` IS ITSELF ALLOWED: a package importing its own submodules
# is not a boundary break, and every sibling audit says so in the same words. The
# per-file rules further down are what constrain WHICH submodule may import which.
#
# NOTHING FROM THE STANDARD LIBRARY IS ON THIS LIST, and that is the whole point
# rather than an oversight. The four gates and their two support modules need none
# — the measured union is exactly the three roots below. A future gate that
# genuinely needs one (``math`` is the plausible candidate) adds it HERE, which is
# a reviewed diff rather than a silent import.
_ALLOWED_IMPORT_ROOTS = (
    "__future__",
    "hfss_agent.contract",
    "hfss_agent.gating",
)

# CONSIDERED AND REFUSED, written down positively for the reason W-8 states when
# it PERMITS the same two: "an unlisted import is indistinguishable from an
# unconsidered one." W-8 admits both; W-9 refuses both, and a reader who meets
# ``_CONSIDERED_AND_PERMITTED`` one audit over needs to see that the difference
# was decided rather than drifted into.
#
#   * ``datetime`` — REFUSED. ADR-30 dec. 2 dropped ``evaluated_at`` from
#     ``FindingProvenance`` because "a judgment is a PURE FUNCTION of the snapshot:
#     the same snapshot yields the same findings forever, so an evaluation instant
#     carries nothing ``DesignSnapshot.created_at`` does not already situate. The
#     cost would be real rather than notional — ``gating`` may import only
#     ``contract``, so minting one means calling a clock from the module whose
#     determinism is what makes it testable." W-8 legitimately stamps
#     ``created_at``; W-9 stamps no instant at all, so it needs no clock.
#   * ``uuid`` — REFUSED. W-8 mints ``snapshot_id`` because a snapshot identifies a
#     CAPTURE EVENT — something that happened at a time. A gate finding is a pure
#     function of a snapshot and identifies no event, so ``finding_id`` is derived
#     from content (``gate-<name>-<outcome>``). That choice was made specifically
#     so this import stays out, and this line is the other half of it.
_CONSIDERED_AND_REFUSED = ("datetime", "uuid")

# Builtins need no import, so the allow-list above cannot see them. These are the
# capability and arbitrary-execution ones: the charter's "no eval, no exec, no
# subprocess-driven scripting, anywhere" and "only broker performs file I/O".
_FORBIDDEN_BUILTINS = ("open", "eval", "exec", "compile", "__import__")

# THE THREE FILES THAT ARE NOT GATES. Named rather than globbed, so that adding a
# fourth support module is a deliberate act; their existence is asserted below, so
# renaming one fails loudly instead of silently reclassifying it as a gate.
_PACKAGE_INIT = "__init__.py"
_SHARED = "common.py"
_AGGREGATOR = "gates.py"
_NON_GATE_FILES = frozenset({_PACKAGE_INIT, _SHARED, _AGGREGATOR})

# The attribute whose keys must never be read, and the operations that read one.
_SIGNALS_ATTR = "available_signals"
_KEY_READING_METHODS = ("get", "keys", "values", "items", "setdefault", "pop")

# THE CALLS THAT MAY RECEIVE THE MAPPING AS AN ARGUMENT -- AN ALLOW-LIST, FOR THE
# REASON THIS WHOLE FILE IS ONE. It began as a six-method denylist plus the note
# that "``dict(...)`` and ``len(...)`` are deliberately absent", which is the same
# note inverted -- and it was measurably wrong the way a denylist is always
# measurably wrong: ``sorted(signals)``, ``list(signals)``, ``next(iter(signals))``
# and every comprehension enumerate the key space and none of them was a method
# call, so none was named and none was caught.
#
# WHAT SEPARATES THE TWO PERMITTED CALLS FROM EVERY OTHER ONE. ``dict(m)`` copies
# the mapping WHOLESALE -- no key is singled out, nothing about its structure
# changes, and the result is the same evidence in a new object. ``len(m)`` reports
# a size. NEITHER SURFACES A KEY NAME INTO THE PROGRAM. ``list(m)``, ``sorted(m)``,
# ``iter(m)`` and a comprehension all do exactly that: they project the key space
# into a sequence the code can then read, which is the thing the contract forbids.
#
# A CALL ON ANYTHING BUT A BARE NAME IS REFUSED OUTRIGHT (``json.dumps(m)``,
# ``self.read(m)``), because the callee is then not something this scan can judge
# and the failure mode of guessing is silence.
_KEY_BLIND_CALLS = ("dict", "len")


def _under(module: str, root: str) -> bool:
    return module == root or module.startswith(root + ".")


def _imported_modules(source: str) -> list[str]:
    """Every module named by an import in ``source``, in its own spelling.

    A RELATIVE IMPORT IS REPORTED IN ITS SOURCE SPELLING AND IS THEREBY REFUSED --
    ``from ..broker import Broker`` comes back as ``"..broker"``, which matches no
    allow-list root, and ``from . import x`` comes back as ``"."``. THIS REPLACES A
    FILTER ON ``node.level == 0`` THAT DROPPED EVERY RELATIVE IMPORT BEFORE THE
    ALLOW-LIST WAS CONSULTED: a planted ``from ..broker import Broker`` in a gate
    left this entire file green, which is the exact failure an allow-list exists to
    make impossible.

    BLANKET REJECTION RATHER THAN RESOLUTION, and the choice is not merely the
    simpler one. Resolving ``..broker`` to ``hfss_agent.broker`` needs the
    IMPORTING FILE'S PACKAGE POSITION, which this function does not have and must
    not need: it takes source TEXT, and half its callers -- every planted string in
    the meta-test below -- have no file position at all. Threading one through would
    make the audit's positive limb test a different code path from the audit itself,
    which is the shape that lets a detector rot. Rejection needs no position and
    treats planted and real sources identically.

    IT IS ENFORCEABLE BECAUSE IT IS ALREADY TRUE. Measured across ``src/hfss_agent``
    rather than assumed: there is not one relative import anywhere in the package,
    in gating or outside it. So this costs nothing today, and the day someone wants
    one it is a refusal in a diff someone reads -- the same discipline the root
    allow-list applies to ``math``.

    THE CONSEQUENCE FOR THE PER-FILE RULES, stated rather than left to be found:
    ``_intra_package_imports`` still cannot see ``from .solution_exists import
    evaluate`` as an intra-package import, because ``".solution_exists"`` is not
    under ``hfss_agent.gating``. That blindness is now UNREACHABLE rather than
    merely unlikely -- the allow-list refuses the import outright, so no relative
    spelling can reach a state where gate-independence would have to interpret it.
    A relative gate-to-gate import fails at
    ``test_gating_imports_only_the_allowed_roots``, not at
    ``test_no_gate_module_imports_another_gate_module``, and both planted spellings
    in the meta-test below pin exactly that.
    """
    modules: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules.append("." * node.level + (node.module or ""))
    return modules


def _gating_sources() -> list[Path]:
    files = sorted(_GATING.rglob("*.py"))
    assert files, f"no gating source files found under {_GATING}"
    return files


def _gate_files() -> list[Path]:
    """The gate modules, DISCOVERED BY GLOB so a new one is covered unedited.

    W-11's inversion is the precedent: constrain by discovery, name only the
    exceptions. A fifth gate added tomorrow is subject to every per-file rule below
    without anyone remembering to add it to a list.
    """
    return [p for p in _gating_sources() if p.name not in _NON_GATE_FILES]


def _intra_package_imports(path: Path) -> set[str]:
    """The gating submodules this file imports, by bare name."""
    names: set[str] = set()
    for module in _imported_modules(path.read_text(encoding="utf-8")):
        if _under(module, "hfss_agent.gating"):
            tail = module[len("hfss_agent.gating") :].lstrip(".")
            if tail:
                names.add(tail.split(".")[0])
    return names


# --- the single axis ---------------------------------------------------------


def test_gating_imports_only_the_allowed_roots() -> None:
    """EVERY import, not merely every ``hfss_agent`` import.

    This is the assertion that makes the polarity real. A denylist would have to
    anticipate ``random``; this refuses it for not being anticipated.
    """
    offenders: dict[str, list[str]] = {}
    for path in _gating_sources():
        bad = [
            module
            for module in _imported_modules(path.read_text(encoding="utf-8"))
            if not any(_under(module, root) for root in _ALLOWED_IMPORT_ROOTS)
        ]
        if bad:
            offenders[path.name] = bad
    assert not offenders, (
        f"gating imported modules outside the allow-list: {offenders}. Add the "
        "root to _ALLOWED_IMPORT_ROOTS only if the module is deterministic and "
        "capability-free; see this file's docstring for why the list is closed"
    )


def test_the_allowed_prefix_admits_contract_submodules() -> None:
    """``hfss_agent.contract`` is a PREFIX grant, as in every sibling audit.

    ``contract`` carries no behaviour beyond validation (W-12), so naming a type
    from any of its submodules grants no capability. The gates import
    ``hfss_agent.contract`` directly today, but a gate needing a ``tool_io`` type
    must not be blocked by an accident of how ``_under`` happens to work.
    """
    assert _under("hfss_agent.contract.tool_io", "hfss_agent.contract")
    assert _under("hfss_agent.contract.common", "hfss_agent.contract")
    assert any(
        _under("hfss_agent.contract.tool_io", root)
        for root in _ALLOWED_IMPORT_ROOTS
    )


def test_the_allowed_prefix_does_not_over_admit() -> None:
    """THE HAZARD AN ALLOW-LIST HAS THAT A DENYLIST DOES NOT.

    Replaces W-8's ``test_stdlib_names_are_not_caught_by_the_hfss_agent_bans``,
    which does not survive the polarity change: under a denylist the risk is a
    stdlib name colliding with a banned one, and under an allow-list the risk runs
    the other way — a sibling whose name merely STARTS WITH an allowed root
    sliding in on a substring match.

    ``_under`` requires equality or a dotted boundary, so none of these is
    admitted. If it were ever loosened to ``startswith(root)``, every name below
    would pass and this is what would notice.
    """
    for impostor in (
        "hfss_agent.contracts",
        "hfss_agent.contract_evil",
        "hfss_agent.gating_helpers",
        "hfss_agent.gatingx",
        "__future_plans__",
    ):
        assert not any(
            _under(impostor, root) for root in _ALLOWED_IMPORT_ROOTS
        ), f"{impostor!r} must not be admitted by a prefix rule"
    # And the genuine members still are, so this is not passing by rejecting
    # everything.
    for genuine in (
        "__future__",
        "hfss_agent.contract",
        "hfss_agent.gating.common",
    ):
        assert any(_under(genuine, root) for root in _ALLOWED_IMPORT_ROOTS)


# --- determinism, which is this audit's whole reason to exist ----------------


def test_no_gating_file_reaches_a_clock_or_a_random_source() -> None:
    """NAMED for the invariant it protects, so losing it is a visible deletion.

    The blanket allow-list above already refuses these. This test exists anyway,
    for the reason W-8 keeps a named broker test beside its blanket ones: a
    maintainer reading a failing assertion needs to know whether it protects
    something or merely restates a list. ADR-30 dec. 2's argument for dropping
    ``evaluated_at`` is the something.
    """
    forbidden = ("time", "datetime", "random", "secrets", "uuid", "calendar")
    offenders: dict[str, list[str]] = {}
    for path in _gating_sources():
        bad = [
            module
            for module in _imported_modules(path.read_text(encoding="utf-8"))
            if any(_under(module, root) for root in forbidden)
        ]
        if bad:
            offenders[path.name] = bad
    assert not offenders, (
        f"gating reached a clock or a randomness source: {offenders}. A gate is a "
        "pure function of the snapshot; ADR-30 dec. 2 rests on it"
    )


def test_datetime_and_uuid_are_considered_and_refused() -> None:
    """The record that W-8 PERMITS these two and W-9 REFUSES them, by decision.

    Narrowing or widening the refusal means editing an assertion that states its
    own justification, rather than quietly adding a name to a list. The mirror of
    W-8's ``test_the_clock_and_the_id_source_are_considered_and_permitted``, which
    exists for the identical reason in the opposite direction.
    """
    for module in _CONSIDERED_AND_REFUSED:
        assert not any(
            _under(module, root) for root in _ALLOWED_IMPORT_ROOTS
        ), f"{module!r} is refused for W-9; see _CONSIDERED_AND_REFUSED"
    # And they are refused as a CONSEQUENCE of the allow-list rather than by a
    # second mechanism that could drift away from it.
    assert set(_CONSIDERED_AND_REFUSED) == {"datetime", "uuid"}


def test_no_gating_file_calls_a_capability_builtin() -> None:
    """Builtins need no import, so the allow-list cannot see them.

    ``open`` is the broker's alone; ``eval``/``exec``/``compile``/``__import__``
    are the arbitrary-execution path the charter refuses outright ("If you think a
    task needs one, the answer is a typed ``cannot_evaluate`` outcome, not a script
    hatch"). ``__import__`` is on the list because it is the one that would
    reintroduce every module the allow-list just refused.
    """
    offenders: dict[str, list[str]] = {}
    for path in _gating_sources():
        called = {
            node.func.id
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        bad = sorted(called & set(_FORBIDDEN_BUILTINS))
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"gating called a capability builtin: {offenders}"


# --- the per-file rules: gate independence -----------------------------------


def test_the_named_non_gate_files_exist() -> None:
    """Renaming a support file must fail loudly, not reclassify it silently.

    Every per-file rule below partitions the package into "gates" (globbed) and
    three named exceptions. If ``gates.py`` were renamed, it would fall into the
    globbed set and be judged as a gate — importing four other gates, so the
    independence rule would fire with a confusing message about the wrong thing.
    This makes the rename fail here instead, where the name is stated.
    """
    present = {path.name for path in _gating_sources()}
    assert _NON_GATE_FILES <= present, (
        f"a named non-gate file is missing: {sorted(_NON_GATE_FILES - present)}"
    )
    assert _gate_files(), "no gate modules discovered; the glob found nothing"


def test_no_gate_module_imports_another_gate_module() -> None:
    """GATE INDEPENDENCE. Each gate judges the snapshot, never another verdict.

    Legal under any flat root rule — ``hfss_agent.gating`` is allowed, so
    ``freshness`` importing ``solution_exists`` passes every check above. It is
    forbidden here because it would make one gate's outcome depend on another's,
    which breaks two things at once: ``evaluate_gates`` returns four INDEPENDENT
    judgments over one artifact, and a gate that consumed a sibling's finding
    would acquire an evaluation ORDER that nothing in the contract pins.

    The constrained side is globbed, so a fifth gate is covered without editing
    this test; only the three non-gate exceptions are named.
    """
    gate_names = {path.stem for path in _gate_files()}
    offenders: dict[str, list[str]] = {}
    for path in _gate_files():
        siblings = sorted(_intra_package_imports(path) & gate_names)
        if siblings:
            offenders[path.name] = siblings
    assert not offenders, (
        f"a gate imported another gate: {offenders}. Gates judge the snapshot "
        "independently; a shared helper belongs in common.py"
    )


def test_only_the_aggregator_imports_gate_modules() -> None:
    """The same invariant from the other side, and it catches a different edit.

    The test above forbids gate-to-gate. This one pins that composing the gate set
    is ONE module's job: if ``common.py`` grew an import of a gate, the rule above
    would not fire (``common`` is not a gate) but the package would have a second
    place where the gate set is assembled — which is how a partial gate list
    becomes constructible, the thing W-7 cannot detect.
    """
    gate_names = {path.stem for path in _gate_files()}
    importers = {
        path.name
        for path in _gating_sources()
        if _intra_package_imports(path) & gate_names
    }
    assert importers == {_AGGREGATOR}, (
        f"gate modules are imported by {sorted(importers)}; composing the gate "
        f"set is {_AGGREGATOR}'s job alone"
    )


# --- the key-branching guard --------------------------------------------------


def _signals_aliases(tree: ast.AST) -> set[str]:
    """Local names bound directly to an ``available_signals`` reference."""
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_signals(node.value, set()):
            aliases |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return aliases


def _is_signals(node: ast.AST, aliases: set[str]) -> bool:
    if isinstance(node, ast.Attribute) and node.attr == _SIGNALS_ATTR:
        return True
    return isinstance(node, ast.Name) and node.id in aliases


def _key_reads(source: str) -> list[str]:
    """Every operation in ``source`` that reads a key of ``available_signals``.

    ONE LEVEL OF ALIASING IS FOLLOWED — ``sigs = e.available_signals`` then
    ``sigs["k"]`` is caught — because that is the shape a reader would reach for
    first. Deeper indirection is not tracked, and saying so is more useful than
    implying a completeness this cannot have: an AST audit sees syntax, not
    dataflow.

    ITERATION IS THE FORM THAT WAS MISSING, and it is the most natural spelling
    there is: ``for key in signals:`` enumerates a mapping without calling any of
    the six methods above, so a detector built from methods alone never saw it. A
    for-loop branching on an invented key was planted and left the entire suite
    green. Four node shapes carry the same read and all four are handled here —
    the ``for`` statement, a comprehension's ``for`` clause (list, set, dict and
    generator all reduce to ``ast.comprehension``), a call that projects the keys
    into a sequence, and the subscript/method/membership forms that were already
    covered.

    ``ast.AsyncFor`` is included beside ``ast.For``. This package contains no async
    code, so that half is symmetry rather than a live hazard — the same symmetry
    ``_cross_call_state`` already keeps by walking ``ast.AsyncFunctionDef``.
    """
    tree = ast.parse(source)
    aliases = _signals_aliases(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _is_signals(node.value, aliases):
            found.append(f"line {node.lineno}: subscript")
        elif isinstance(node, ast.For | ast.AsyncFor) and _is_signals(
            node.iter, aliases
        ):
            found.append(f"line {node.lineno}: iteration")
        elif isinstance(node, ast.comprehension) and _is_signals(
            node.iter, aliases
        ):
            # ``ast.comprehension`` has no ``lineno``; report its iterable's.
            found.append(f"line {node.iter.lineno}: comprehension")
        elif isinstance(node, ast.Call) and any(
            _is_signals(argument, aliases) for argument in node.args
        ):
            callee = node.func.id if isinstance(node.func, ast.Name) else None
            if callee not in _KEY_BLIND_CALLS:
                found.append(f"line {node.lineno}: {callee or 'call'}(...)")
        elif (
            isinstance(node, ast.Attribute)
            and node.attr in _KEY_READING_METHODS
            and _is_signals(node.value, aliases)
        ):
            found.append(f"line {node.lineno}: .{node.attr}()")
        elif isinstance(node, ast.Compare):
            # ``strict=True``: ``ops`` and ``comparators`` are the same length by
            # the grammar, so a mismatch would mean the AST shape changed under us
            # -- which should raise rather than silently truncate the scan.
            for operator, comparator in zip(
                node.ops, node.comparators, strict=True
            ):
                if isinstance(operator, ast.In | ast.NotIn) and _is_signals(
                    comparator, aliases
                ):
                    found.append(f"line {node.lineno}: membership test")
    return found


def test_no_gating_file_branches_on_an_available_signals_key() -> None:
    """THE CONTRACT RULE, MADE ENFORCEABLE. ``FreshnessEvidence`` says consumers
    "must never branch on a key name — ``determinable`` is the field to branch on".

    UNCATCHABLE BEHAVIOURALLY, AND THAT WAS MEASURED RATHER THAN ASSUMED. Part 3b
    planted two key branches: one on ``design_modified_since_solve``, which the
    freshness tests DO set and therefore caught; one on an invented key no test
    sets, which passed the entire suite. ``available_signals`` is
    ``dict[str, Any]`` with no vocabulary by design, so the key space is unbounded
    and no finite set of test rows can cover it. A syntactic check can.
    """
    offenders: dict[str, list[str]] = {}
    for path in _gating_sources():
        reads = _key_reads(path.read_text(encoding="utf-8"))
        if reads:
            offenders[path.name] = reads
    assert not offenders, (
        f"gating read a key of {_SIGNALS_ATTR}: {offenders}. The contract permits "
        "branching on `determinable` only; carry the mapping as evidence"
    )


def test_the_key_read_detector_finds_every_shape_it_claims_to() -> None:
    """THE POSITIVE LIMB, without which the check above is unfalsifiable.

    An assertion that a pattern appears NOWHERE needs a companion showing the same
    code FINDING it somewhere, or the detector can silently stop looking — a
    typo'd attribute name, a walk that no longer visits, a node type that changed
    shape — and stay green forever. A test that can only pass is one of the
    recurring shapes a vacuous test takes, and it is the one an "appears nowhere"
    assertion falls into by default.

    Each planted source below is a real spelling someone would write.

    THE ITERATION BLOCK IS WHY THIS LIMB IS LONGER THAN IT WAS. Every spelling in
    it was MISSED by the method-based detector this replaced, and the plainest of
    them -- ``for key in signals:`` -- is the first thing anyone writes to walk a
    mapping. A positive limb that probes only the shapes the detector was built
    around measures the author's imagination rather than the detector.
    """
    planted = {
        "subscript": "x = evidence.available_signals['design_modified']",
        "get": "x = evidence.available_signals.get('design_modified')",
        "membership": "if 'design_modified' in evidence.available_signals: pass",
        "not-in": "if 'k' not in evidence.available_signals: pass",
        "keys": "for k in evidence.available_signals.keys(): pass",
        "items": "for k, v in evidence.available_signals.items(): pass",
        "pop": "x = evidence.available_signals.pop('k', None)",
        "one-level alias": (
            "sigs = evidence.available_signals\nx = sigs['design_modified']"
        ),
        "alias + get": (
            "sigs = evidence.available_signals\nx = sigs.get('design_modified')"
        ),
        # --- the enumeration forms, none of which is a method call -------------
        "bare for-loop": "for key in evidence.available_signals: pass",
        "for-loop with a branch": (
            "for key in evidence.available_signals:\n"
            "    if key == 'design_modified': pass\n"
        ),
        "alias + for-loop": (
            "sigs = evidence.available_signals\nfor key in sigs: pass"
        ),
        "sorted": "for key in sorted(evidence.available_signals): pass",
        "list": "x = list(evidence.available_signals)",
        "tuple": "x = tuple(evidence.available_signals)",
        "set": "x = set(evidence.available_signals)",
        "iter": "x = iter(evidence.available_signals)",
        "next(iter(...))": "x = next(iter(evidence.available_signals))",
        "min": "x = min(evidence.available_signals)",
        "list comprehension": "x = [k for k in evidence.available_signals]",
        "set comprehension": "x = {k for k in evidence.available_signals}",
        "dict comprehension": "x = {k: 1 for k in evidence.available_signals}",
        "generator expression": (
            "x = any(k == 'design_modified' for k in evidence.available_signals)"
        ),
        "alias + comprehension": (
            "sigs = evidence.available_signals\nx = [k for k in sigs]"
        ),
        # A call this scan cannot judge the callee of. Refused rather than guessed.
        "call on a non-name callee": "x = json.dumps(evidence.available_signals)",
    }
    for label, source in planted.items():
        assert _key_reads(source), f"the detector missed a {label} key read"

    # AND THE LEGITIMATE SPELLINGS ARE NOT FLAGGED, so the check is discriminating
    # rather than merely alarmed. These are how a gate carries the mapping as
    # evidence without reading it: copy it wholesale, or report its size. The first
    # is the shape ``freshness._from_solve_state`` actually contains, so a rule
    # flagging it would fail the package on the day it shipped.
    for label, source in {
        "wholesale copy": "x = dict(evidence.available_signals)",
        "size only": "x = len(evidence.available_signals)",
        # Wholesale copy by unpacking. Structurally the same as ``dict(...)``: it
        # surfaces no key name into the program, it just rebuilds the mapping.
        "wholesale copy by unpacking": "x = {**evidence.available_signals}",
        "the flag beside it": "if evidence.determinable: pass",
        "an unrelated dict": "x = other_mapping['k']",
        "iterating something else": "for k in other_mapping: pass",
    }.items():
        assert not _key_reads(source), f"the detector wrongly flagged {label}"


# --- the meta-test ------------------------------------------------------------


def test_audit_would_catch_a_forbidden_import() -> None:
    """The audit is only meaningful if it detects the violations it is aimed at.

    The eight modules below are the measured set that W-8's two-axis design lets
    through — the reason this file's polarity differs from its five siblings. Each
    must be refused by the allow-list, and ``hfss_agent.contract`` must still be
    admitted so this is not passing by rejecting everything.

    THE RELATIVE SPELLINGS AT THE END ARE WHY THIS LIMB WAS INCOMPLETE, and their
    absence is what let the ``node.level == 0`` filter survive. Every source here
    was an ABSOLUTE import, so a scanner that silently dropped relative ones passed
    this test and every other in the file while a planted ``from ..broker import
    Broker`` sat in a gate. A positive limb that probes only the spellings the
    scanner already handles proves nothing about the ones it does not.
    """
    for source in (
        "import random",
        "import time",
        "import secrets",
        "import hashlib",
        "import datetime",
        "import uuid",
        "import itertools",
        "import functools",
        "import os",
        "import subprocess",
        "from hfss_agent.broker import Broker",
        "from hfss_agent.adapter import base",
        "import pyaedt",
        "from ansys.aedt.core import Hfss",
        # RELATIVE SPELLINGS OF THE SAME VIOLATIONS. ``from ..broker import
        # Broker`` is the escape the level filter opened; the two gate-to-gate
        # forms are the ones the per-file rules would otherwise have to interpret,
        # and are refused here instead so those rules never see one.
        "from ..broker import Broker",
        "from ...hfss_agent.adapter import base",
        "from .solution_exists import evaluate",
        "from . import solution_exists",
        "from .common import applicability",
    ):
        modules = _imported_modules(source)
        assert modules, f"{source!r} parsed to no module at all"
        assert not all(
            any(_under(module, root) for root in _ALLOWED_IMPORT_ROOTS)
            for module in modules
        ), f"{source!r} must be refused by the allow-list"

    for source in (
        "from __future__ import annotations",
        "from hfss_agent.contract import Finding",
        "from hfss_agent.contract.tool_io import CannotEvaluate",
        "from hfss_agent.gating.common import applicability",
    ):
        modules = _imported_modules(source)
        assert all(
            any(_under(module, root) for root in _ALLOWED_IMPORT_ROOTS)
            for module in modules
        ), f"{source!r} must be permitted"


# --- module-level state: the same axis, a different syntactic door -----------

# THE RULE IS ABOUT MUTATION, NOT SHAPE, AND THAT WAS DERIVED FROM THE PACKAGE
# RATHER THAN FROM A PRINCIPLE. Dumping every module-level assignment across the
# seven gating files first: 38 assignments, of which 7 are MUTABLE CONTAINERS --
# ``__all__`` (list), ``CLASSIFICATION_BY_OUTCOME``, ``_STATUS_OUTCOMES`` and four
# copies of ``_ABSENCE_OUTCOMES`` (dicts). A "no module-level dict" rule would
# fail six of the seven files on the day it shipped.
#
# SO WHAT SEPARATES A CONSTANT DICT FROM A MEMO CACHE? Not the shape: ``_CACHE =
# {}`` and ``_ABSENCE_OUTCOMES = {...}`` are the same node type, and no annotation
# distinguishes them either -- ``Final`` would only be a promise. What separates
# them is USE. A constant is read; a cache is WRITTEN, and written from inside a
# function, because that is the only place a value can differ between two calls.
#
# WRITING IS A DISTINCT SYNTACTIC EVENT, so that IS checkable where shape is not.
# Three forms, and the same dump measured all three at zero across the package:
#
#   * ``global`` -- rebinding a module-level name from a function. The counter.
#   * ``nonlocal`` -- a closure holding state across calls. Exotic, one line to
#     cover, and a genuine hazard with no module-level assignment at all.
#   * mutation of a module-level name from inside a function -- subscript
#     assignment, augmented assignment, ``del``, or a mutating method call. The
#     memo dict.
#
# ONE SUB-RULE WAS PROPOSED AND IS DELIBERATELY NOT IMPLEMENTED: "no augmented
# assignment at MODULE level". ``_X += 1`` in the module body runs exactly once,
# at import, so it cannot make two calls differ. It is an odd way to write a
# constant, not a determinism hazard, and a rule that catches nothing real earns
# its place in no audit.
#
# THE SHADOWING LIMIT, stated rather than implied: a local name shadows a
# module-level one, so ``_local_bindings`` is subtracted before the mutation check
# runs. It walks into nested functions, which OVER-collects shadows -- a nested
# function that rebound an outer name could mask a violation. The package contains
# no nested functions, and ``global``/``nonlocal`` are caught unconditionally
# regardless of shadowing, so the two strongest signals are unaffected.
# A FOURTH FORM, FOUND BY PROBING THE CHECK ABOVE RATHER THAN BY REASONING ABOUT
# IT, and it is the one most likely to arrive by ACCIDENT rather than by design:
#
#     def evaluate(snapshot, _memo={}):
#         _memo[snapshot.snapshot_id] = ...
#
# A mutable default argument is evaluated ONCE, at function definition, so it
# survives between calls exactly as a module-level dict would -- with no
# module-level assignment and no import. The mutation check above cannot see it:
# ``_memo`` is a parameter, so it lands in ``_local_bindings`` and is subtracted as
# a shadow before the scan runs. Measured, not assumed: both spellings came back
# NOT CAUGHT before this was added.
#
# IT EARNS ITS PLACE BECAUSE THE CONSTRUCT ALREADY EXISTS HERE.
# ``target_coverage.evaluate(snapshot, target_frequency_hz=None)`` has a default
# argument today, so this hazard is one keystroke from shipped code.
#
# AND A FIFTH FORM, WHICH IS THE FOURTH'S SIBLING AND WAS MISSED FOR THE SAME
# REASON THE KEY-BRANCH DETECTOR MISSED ITERATION -- the check enumerated SHAPES
# instead of stating a property:
#
#     def evaluate(snapshot, _memo=dict()):
#
# ``dict()`` and ``list()`` are ``ast.Call``, not ``ast.Dict`` and ``ast.List``, so
# a six-entry list of literal node types never saw them while doing exactly what
# the literal spellings do. THAT IS NOW AN ALLOW-LIST OVER DEFAULT SHAPES rather
# than a denylist over mutable ones: a default may be a constant, a tuple of
# constants, or a signed numeric constant, and ANYTHING ELSE IS REPORTED. The next
# factory nobody named -- ``bytearray()``, ``defaultdict(list)``, ``[]``, a
# comprehension -- lands in the reported set by default instead of by anticipation.
# Both defaults in this package are ``None``, so the allow-list costs nothing today.
#
# A ``Name`` DEFAULT IS DELIBERATELY NOT ADMITTED, and refusing it closes a hole
# rather than inventing a rule. ``def evaluate(s, memo=_MEMO)`` binds a
# module-level mutable to a PARAMETER, and the mutation check above then cannot see
# writes through it: ``memo`` is a parameter, so it lands in ``_local_bindings`` and
# is subtracted as a shadow. Permitting the shape would leave the fourth form
# reachable by one more step of indirection.
#
# A MUTATED CLASS ATTRIBUTE ALSO ESCAPES THE SCAN AND IS STILL FLAGGED RATHER THAN
# GUARDED, on ADR-28 dec. 4's rule -- it needs a class to exist first and this
# package has none. THE FUNCTION-ATTRIBUTE SIBLING IS THE OPPOSITE CASE AND IS NOW
# GUARDED: ``evaluate.calls = 0`` needs only a ``def``, and this package is nothing
# but ``def``s. It was invisible until now for a mechanical reason --
# ``_module_level_names`` collected ``Assign`` and ``AnnAssign`` only, so a function
# name never entered ``watched`` and a write to an attribute of one had nothing to
# match against.


def _is_constant_default(node: ast.expr) -> bool:
    """Whether a default argument is a value that cannot carry state between calls.

    Three admitted shapes, and each is admitted because it is IMMUTABLE rather than
    because it is common: a constant (``None``, a number, a string, a bool), a
    tuple whose every element is one, and a signed numeric constant -- ``-1.0``
    parses as ``UnaryOp(USub, Constant)`` and is not an ``ast.Constant`` itself.
    """
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Tuple):
        return all(_is_constant_default(element) for element in node.elts)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        return _is_constant_default(node.operand)
    return False

_MUTATING_METHODS = frozenset(
    {
        "append", "extend", "insert", "remove", "pop", "clear", "update",
        "setdefault", "add", "discard", "sort", "reverse", "popitem",
    }
)


def _bound_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, ast.Tuple | ast.List):
        names: set[str] = set()
        for element in target.elts:
            names |= _bound_names(element)
        return names
    return set()


def _module_level_names(tree: ast.Module) -> set[str]:
    """Names bound in the module body -- the candidates for shared state.

    A ``def`` BINDS A MODULE-LEVEL NAME TOO, and omitting it was the mechanical
    reason ``evaluate.calls = 0`` was invisible: a function object carries
    attributes exactly as any other object does, they survive between calls exactly
    as a module-level dict would, and until a function's name entered ``watched``
    there was nothing for ``_writes_into`` to match a write against.

    THE INVERSION WORTH NAMING, because the file's own prose sets up its opposite.
    A mutated CLASS attribute is flagged-not-guarded on the grounds that this
    package contains no classes. The function-attribute form is that hazard's
    sibling and the grounds run the other way: this package contains nothing BUT
    functions, so the construct it needs is on every one of these seven files.
    """
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                names |= _bound_names(target)
        elif isinstance(node, ast.AnnAssign):
            names |= _bound_names(node.target)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(node.name)
    return names


def _local_bindings(function: ast.AST) -> set[str]:
    """Names bound locally, which SHADOW a module-level name of the same spelling."""
    bound: set[str] = set()
    arguments = function.args  # type: ignore[attr-defined]
    for group in (arguments.posonlyargs, arguments.args, arguments.kwonlyargs):
        bound |= {argument.arg for argument in group}
    for extra in (arguments.vararg, arguments.kwarg):
        if extra is not None:
            bound.add(extra.arg)
    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                bound |= _bound_names(target)
        elif isinstance(node, ast.AnnAssign | ast.AugAssign | ast.For):
            bound |= _bound_names(node.target)
        elif isinstance(node, ast.comprehension):
            bound |= _bound_names(node.target)
        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars is not None:
                    bound |= _bound_names(item.optional_vars)
    return bound


def _writes_into(target: ast.AST, watched: set[str]) -> bool:
    if isinstance(target, ast.Subscript | ast.Attribute) and isinstance(
        target.value, ast.Name
    ):
        return target.value.id in watched
    return isinstance(target, ast.Name) and target.id in watched


def _cross_call_state(source: str) -> list[str]:
    """Every construct that lets a value survive between two calls, with its line.

    Two forms, both of which make ``evaluate`` return different findings for the
    same snapshot: a write to module-level state from inside a function -- INCLUDING
    an attribute of a module-level function, which a ``def`` binds a name for -- and
    a default argument that is not a constant (evaluated once, at definition).
    """
    tree = ast.parse(source)
    module_names = _module_level_names(tree)
    found: list[str] = []
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    for function in functions:
        arguments = function.args
        for default in (*arguments.defaults, *arguments.kw_defaults):
            # ``kw_defaults`` carries a real Python ``None`` -- not an
            # ``ast.Constant`` -- for every keyword-only argument that has NO
            # default. Skipping those is what keeps the allow-list from reporting
            # the absence of a default as a non-constant one.
            if default is None:
                continue
            if not _is_constant_default(default):
                found.append(
                    f"line {default.lineno}: non-constant default argument in "
                    f"{function.name}()"
                )
        watched = module_names - _local_bindings(function)
        for node in ast.walk(function):
            if isinstance(node, ast.Global):
                found.append(f"line {node.lineno}: global {', '.join(node.names)}")
            elif isinstance(node, ast.Nonlocal):
                found.append(f"line {node.lineno}: nonlocal {', '.join(node.names)}")
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if _writes_into(target, watched):
                        found.append(f"line {node.lineno}: assignment into state")
            elif isinstance(node, ast.AugAssign) and _writes_into(
                node.target, watched
            ):
                found.append(f"line {node.lineno}: augmented assignment")
            elif isinstance(node, ast.Delete):
                for target in node.targets:
                    if _writes_into(target, watched):
                        found.append(f"line {node.lineno}: del on state")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in watched
                and node.func.attr in _MUTATING_METHODS
            ):
                found.append(
                    f"line {node.lineno}: "
                    f"{node.func.value.id}.{node.func.attr}()"
                )
    return sorted(set(found))


def test_no_gating_file_holds_state_between_calls() -> None:
    """A gate is a PURE FUNCTION of the snapshot, and this is the other half of it.

    The allow-list stops a gate importing a clock. Nothing stopped it keeping a
    counter: ``_CALLS += 1`` under a ``global``, ``_MEMO[key] = finding``, or a
    mutable default argument, makes two calls on the same snapshot differ with
    ZERO imports. Part 3 measured that the behavioural determinism test cannot be
    relied on as the backstop -- ``time.time()`` slips past it on float64
    resolution -- so this closes the door structurally rather than hoping to
    observe the effect.

    MUTATION, NOT SHAPE. Seven module-level mutable containers already exist in
    this package and every one is a constant; see the comment above for why the
    distinction is checkable only through use.
    """
    offenders: dict[str, list[str]] = {}
    for path in _gating_sources():
        writes = _cross_call_state(path.read_text(encoding="utf-8"))
        if writes:
            offenders[path.name] = writes
    assert not offenders, (
        f"gating holds state between calls: {offenders}. A gate returns the same "
        "findings for the same snapshot forever; ADR-30 dec. 2 rests on it"
    )


def test_the_cross_call_state_detector_finds_every_shape_it_claims_to() -> None:
    """THE POSITIVE LIMB, and the NARROWING one beside it.

    An "appears nowhere" assertion needs a companion showing the same code finding
    the pattern where it should be. And a detector proven only to FIND things can
    pass by flagging everything -- so the second half is the one that keeps this
    rule shippable: seven module-level mutable containers already exist here, and
    every one must stay legal.
    """
    caught = {
        "global counter": (
            "_CALLS = 0\n"
            "def evaluate(s):\n"
            "    global _CALLS\n"
            "    _CALLS += 1\n"
        ),
        "memo write": (
            "_MEMO = {}\n"
            "def evaluate(s):\n"
            "    _MEMO[s.snapshot_id] = 1\n"
        ),
        "memo update": (
            "_MEMO = {}\n"
            "def evaluate(s):\n"
            "    _MEMO.update({'k': 1})\n"
        ),
        "memo setdefault": (
            "_MEMO = {}\n"
            "def evaluate(s):\n"
            "    return _MEMO.setdefault(s, 1)\n"
        ),
        "list append": (
            "_SEEN = []\n"
            "def evaluate(s):\n"
            "    _SEEN.append(s)\n"
        ),
        "del from state": (
            "_MEMO = {}\n"
            "def evaluate(s):\n"
            "    del _MEMO['k']\n"
        ),
        "closure state": (
            "def _make():\n"
            "    count = 0\n"
            "    def inner():\n"
            "        nonlocal count\n"
            "        count += 1\n"
            "    return inner\n"
        ),
        # --- attributes hung on a function, which a ``def`` makes reachable -----
        "function attribute write": (
            "def evaluate(s):\n"
            "    evaluate.calls = 1\n"
        ),
        "function attribute increment": (
            "def evaluate(s):\n"
            "    evaluate.calls += 1\n"
        ),
        "attribute on a sibling function": (
            "def _helper():\n"
            "    return 1\n"
            "def evaluate(s):\n"
            "    _helper.seen = s\n"
        ),
        "del of a function attribute": (
            "def evaluate(s):\n"
            "    del evaluate.calls\n"
        ),
        # --- defaults that are not constants ------------------------------------
        # The first two are the ``ast.Call`` spellings a node-type denylist could
        # not see; the rest are what an allow-list gets for free.
        "dict() default": (
            "def evaluate(s, _memo=dict()):\n"
            "    return _memo\n"
        ),
        "list() default": (
            "def evaluate(s, _seen=list()):\n"
            "    return _seen\n"
        ),
        "set() default": (
            "def evaluate(s, _seen=set()):\n"
            "    return _seen\n"
        ),
        "dict literal default": (
            "def evaluate(s, _memo={}):\n"
            "    return _memo\n"
        ),
        "list literal default": (
            "def evaluate(s, _seen=[]):\n"
            "    return _seen\n"
        ),
        "comprehension default": (
            "def evaluate(s, _seen=[x for x in ()]):\n"
            "    return _seen\n"
        ),
        "keyword-only mutable default": (
            "def evaluate(s, *, _memo={}):\n"
            "    return _memo\n"
        ),
        "module-level mutable bound through a default": (
            "_MEMO = {}\n"
            "def evaluate(s, memo=_MEMO):\n"
            "    memo[s] = 1\n"
        ),
    }
    for label, source in caught.items():
        assert _cross_call_state(source), f"the detector missed a {label}"

    # THE NARROWING HALF. Every one of these is a shape the package already
    # contains, or a legitimate local operation, and none may be flagged.
    permitted = {
        "constant dict, never written": (
            "_ABSENCE_OUTCOMES = {'no_solution': 'fail'}\n"
            "def evaluate(s):\n"
            "    return _ABSENCE_OUTCOMES[s]\n"
        ),
        "unused empty dict": (
            "_CACHE = {}\n"
            "def evaluate(s):\n"
            "    return 1\n"
        ),
        "constant list": (
            "__all__ = ['evaluate']\n"
            "def evaluate(s):\n"
            "    return 1\n"
        ),
        "local dict mutated": (
            "def evaluate(s):\n"
            "    observed = {}\n"
            "    observed['k'] = 1\n"
            "    return observed\n"
        ),
        "local list appended": (
            "def evaluate(s):\n"
            "    found = []\n"
            "    found.append(1)\n"
            "    return found\n"
        ),
        "local shadowing a module name": (
            "_MEMO = {}\n"
            "def evaluate(s):\n"
            "    _MEMO = {}\n"
            "    _MEMO['k'] = 1\n"
            "    return _MEMO\n"
        ),
        "reading module state": (
            "_STATUS = {'a': 1}\n"
            "def evaluate(s):\n"
            "    return _STATUS.get('a')\n"
        ),
        # --- the shapes the two widenings above must NOT have swept up ----------
        # A ``def`` now binds a watched name, so these three pin that naming a
        # function, calling one, and returning one are all still legal. The second
        # is ``gates.evaluate_gates``' entire body.
        "reading a function's own name": (
            "def evaluate(s):\n"
            "    return evaluate\n"
        ),
        "calling a sibling function": (
            "def _helper(x):\n"
            "    return x\n"
            "def evaluate(s):\n"
            "    return _helper(s)\n"
        ),
        "a local attribute write": (
            "def evaluate(s):\n"
            "    holder = s\n"
            "    holder.seen = 1\n"
            "    return holder\n"
        ),
        # And the default-argument allow-list admits every shape this package
        # actually uses. ``target=None`` is ``target_coverage.evaluate``'s and
        # ``gates.evaluate_gates``' own signature.
        "a None default": (
            "def evaluate(s, target=None):\n"
            "    return target\n"
        ),
        "a keyword-only argument with no default at all": (
            "def evaluate(s, *, outcome):\n"
            "    return outcome\n"
        ),
        "a string default": (
            "def evaluate(s, label='gate'):\n"
            "    return label\n"
        ),
        "a signed numeric default": (
            "def evaluate(s, floor=-1.0):\n"
            "    return floor\n"
        ),
        "a tuple-of-constants default": (
            "def evaluate(s, names=('a', 'b')):\n"
            "    return names\n"
        ),
    }
    for label, source in permitted.items():
        assert not _cross_call_state(source), (
            f"the detector wrongly flagged {label}; it would block a shape this "
            "package already contains"
        )
