"""Layer-6 import audit (W-10): findings imports ``contract``, its own submodules,
four stdlib names and ``pydantic``, and NOTHING ELSE — enforced as an ALLOW-LIST,
plus the STRUCTURAL half of §6.6 clause (d).

READ THE PER-FILE ROWS, NOT JUST THE VERDICT. Every assertion here reports
offenders as ``{filename: [...]}`` for the reason W-9's audit states at its own
top: a green audit says nothing was violated; it does not say the shape is what
you think it is.

POLARITY FOLLOWS W-9's, NOT THE FIVE DENYLIST SIBLINGS', and the reason is
inherited rather than re-derived. W-9 measured that eight modules — ``random``,
``time``, ``secrets``, ``hashlib``, ``datetime``, ``uuid``, ``itertools``,
``functools`` — pass the two-axis denylist design silently, "none of them an
hfss_agent module and none reaching a file, socket, environment or process". That
measurement holds here unchanged, so this audit does not reopen the question.

BUT THE ALLOW-LIST IS NOT FREE HERE, WHICH IS THE ONE PLACE THIS DIFFERS FROM
W-9. Gating's measured union was three roots, so its list "costs nothing today".
This package's measured union is SEVEN, and four of them are stdlib. A longer
allow-list is a weaker guarantee, so every entry below carries its reason AT THE
PERMISSION — W-9 refuses ``datetime`` and ``uuid`` in writing because "an
unlisted import is indistinguishable from an unconsidered one", and that argument
runs in both directions: a permission needs its reason as much as a refusal does.

WHAT THIS AUDIT OWNS THAT NO SIBLING DOES: §6.6 CLAUSE (d), STRUCTURALLY. Part 4
established the narrowed claim BEHAVIOURALLY — differential tests showing that
hostile and benign strings produce identical wrapper decisions — and deliberately
left the structural proof here. THE TWO ARE DIFFERENT CLAIMS AND MUST NOT BECOME
TWO SOURCES FOR ONE FACT:

  * ``tests/findings/test_hostile_strings.py`` owns "on these inputs, no decision
    changed". It runs the pipeline and compares receipts. It cannot prove absence
    — the input space is unbounded.
  * THIS FILE owns "no such decision EXISTS to change". It reads syntax and
    proves absence over the whole package. It cannot prove behaviour — a check
    can be structurally clean and still wrong.

Neither implies the other. Deleting either leaves a real hole.

THE CLAIM, AS PART 4 NARROWED IT: no untrusted string selects a capability, a
code path reaching one, a tier, or a file path. The broad version ("no untrusted
string reaches a branch") is FALSE and Part 4 measured why — three branches
legitimately take one as an operand, and they are admitted by name below.

TWO SHIPPED DEFECTS FROM W-9's AUDIT ARE INHERITED AS FIXES, NOT AS SHAPES. Its
AST walk once filtered ``ast.ImportFrom`` on ``node.level == 0``, dropping every
relative import before the allow-list saw it; and its positive limb planted
fourteen violations that were all ABSOLUTE, so it never probed that hole.
``_imported_modules`` below reports a relative import in its source spelling and
thereby refuses it, and the meta-test plants relative spellings explicitly.

WHERE THIS PACKAGE DIFFERS FROM GATING, so each absence reads as a decision:

  * GATE INDEPENDENCE, the FOUR-GATE COMPOSITION RULE and the
    ``available_signals`` KEY-BRANCH DETECTOR have NO ANALOGUE here. The first two
    partition gating into "gates" and three named support files and constrain
    which may import which; this package has no such partition — its four modules
    form a layered chain (``results`` <- ``receipt``/``render`` <- ``merge`` <-
    ``__init__``) and the chain is asserted below in its own right. The third
    guards a contract sentence about ``FreshnessEvidence``, a type this package
    never touches.
  * THE CROSS-CALL STATE DETECTOR DOES PORT, and one part of it is STRENGTHENED
    rather than copied — see ``_cross_call_state``.
"""

from __future__ import annotations

import ast
from pathlib import Path

_FINDINGS = Path(__file__).resolve().parents[2] / "src" / "hfss_agent" / "findings"

# THE COMPLETE SET OF IMPORT ROOTS THIS PACKAGE MAY NAME, each with the reason it
# is here. Matched by dotted prefix — see the two prefix tests below.
#
#   * ``__future__`` — ``annotations`` only, as in every module in this repo. No
#     runtime behaviour at all.
#   * ``hfss_agent.contract`` — Layer 6's entire grant. ``contract`` carries no
#     behaviour beyond validation (W-12), so naming a type from it grants nothing.
#     THIS IS THE PERMISSION THE WHOLE PACKAGE RESTS ON: Part 4's decision that
#     W-10 performs no length-capping is justified by ``sanitize_str`` and
#     ``MAX_UNTRUSTED_STR_LEN`` living in ``hfss_agent.adapter``, which this list
#     refuses. If ``hfss_agent.adapter`` were ever added here, that decision would
#     silently lose its reason — which is why the refusal is also asserted by name.
#   * ``hfss_agent.findings`` — a package importing its own submodules is not a
#     boundary break; every sibling audit says so in the same words. The chain
#     rule below constrains WHICH submodule may import which.
#   * ``collections.abc`` — ``Callable``, ``Iterable``, ``Mapping``, ``Sequence``
#     for annotations. Abstract base classes: no I/O, no clock, no randomness, and
#     nothing that can hold state. Admitted as ``collections.abc`` rather than as
#     ``collections`` deliberately, so ``collections.Counter`` and
#     ``collections.defaultdict`` — both mutable containers a memo cache would
#     reach for — stay refused.
#   * ``dataclasses`` — ``dataclass``, ``field``. W-10's result types are frozen
#     dataclasses rather than pydantic models because nothing here crosses a wire
#     (``results.py`` states the reasoning). Pure construction, no capability.
#   * ``typing`` — ``Any``, ``Literal``. Annotations only.
#   * ``pydantic`` — see ``test_only_validation_error_is_named_from_pydantic`` for
#     what naming the ROOT admits that this package does not use, and why that is
#     accepted rather than narrowed.
#
# NOTHING ELSE. A future module that genuinely needs a stdlib name adds it HERE,
# in a diff someone reviews, with its reason beside it.
_ALLOWED_IMPORT_ROOTS = (
    "__future__",
    "collections.abc",
    "dataclasses",
    "hfss_agent.contract",
    "hfss_agent.findings",
    "pydantic",
    "typing",
)

# CONSIDERED AND REFUSED, in writing, for W-9's stated reason. Each is a module
# someone could plausibly reach for HERE, so its absence from the list above is a
# decision rather than an oversight.
#
#   * ``datetime`` — REFUSED. W-10 stamps no instant. A receipt is a pure function
#     of the two streams it was handed, and ``render.findings_template_text`` is
#     asserted byte-deterministic and timestamp-free (following W-5 and W-6). A
#     clock here would break a guarantee two tests already pin.
#   * ``uuid`` — REFUSED. W-10 mints no identifier. ``finding_id`` is the
#     producer's, and ``merge._id_anomalies`` records at length that the identity
#     reported must be the identity the producer emitted — minting one would
#     break the correspondence ``RejectedFinding.position`` exists to provide.
#   * ``os``, ``pathlib``, ``shutil``, ``tempfile`` — REFUSED, and this is the
#     clause-(d) half of the list. "No untrusted string selects a file path" is
#     enforced most simply by this package having no way to name one.
#   * ``re`` — REFUSED, and it is the least obvious entry. A regex over
#     producer-controlled text is exactly the content-reading branch clause (d)
#     forbids: ``if re.match(r"^gate\\.", finding.rule_id)`` selects a code path
#     from what an untrusted string SAYS. Refusing the import is stronger than
#     any rule about how it is used.
#   * ``hfss_agent.adapter`` — REFUSED, and Part 4's no-capping decision rests on
#     it; see the ``hfss_agent.contract`` permission above.
_CONSIDERED_AND_REFUSED = (
    "datetime",
    "uuid",
    "os",
    "pathlib",
    "shutil",
    "tempfile",
    "re",
    "hfss_agent.adapter",
)

# Builtins need no import, so the allow-list cannot see them. ``open`` is the
# broker's alone; ``eval``/``exec``/``compile``/``__import__`` are the
# arbitrary-execution path the charter refuses outright, and ``__import__`` would
# reintroduce every module the allow-list just refused.
_FORBIDDEN_BUILTINS = ("open", "eval", "exec", "compile", "__import__")

# --- clause (d): the method allow-list ---------------------------------------
#
# THE MEASURED UNION OF EVERY METHOD NAME CALLED ANYWHERE IN THIS PACKAGE, which
# is what makes this checkable at all: an AST cannot know a receiver's type, so a
# rule phrased as "no string method that reads content" is unenforceable. A rule
# phrased as "only these names may be called" is enforceable, and it fails closed
# on exactly the spellings that would read content -- ``startswith``, ``endswith``,
# ``lower``, ``casefold``, ``find``, ``index``, ``count``, ``split``,
# ``partition``, ``format``, ``replace``, ``match``, ``search``. None of them is
# below, and adding one is a reviewed diff.
#
# GROUPED BY WHAT EACH IS, because a flat list of thirteen names teaches nothing:
#
#   * TEXT CONSTRUCTION -- ``join`` builds a string from wrapper-owned parts; it
#     writes text, it never reads it. Every receiver in this package is a literal
#     separator (``", "``, ``"; "``, ``"."``, ``"\\n"``).
#   * THE BLANKNESS TESTS -- ``strip``. Three calls, and they are two of the three
#     branches Part 4 admitted: ``merge`` on ``finding_id``, and the evidence rules
#     on their fields. ``strip`` reads WHITESPACE, never meaning, which is why it
#     is the one content-touching operation on this list.
#   * CONTAINERS -- ``append``, ``extend``, ``add``, ``pop``, ``get``, ``items``,
#     ``values``, ``setdefault``. All on wrapper-built locals.
#   * PYDANTIC -- ``model_dump``, ``model_validate``, ``errors``. The forcing pass
#     and the schema-detail reader.
_ALLOWED_METHOD_NAMES = frozenset(
    {
        "join",
        "strip",
        "append", "extend", "add", "pop", "get", "items", "values", "setdefault",
        "model_dump", "model_validate", "errors",
    }
)


def _under(module: str, root: str) -> bool:
    return module == root or module.startswith(root + ".")


def _imported_modules(source: str) -> list[str]:
    """Every module named by an import in ``source``, in its own spelling.

    A RELATIVE IMPORT IS REPORTED IN ITS SOURCE SPELLING AND IS THEREBY REFUSED --
    ``from ..adapter import sanitize`` comes back as ``"..adapter"``, matching no
    allow-list root. THIS IS W-9's FIX INHERITED, NOT ITS DEFECT: that audit
    shipped with a ``node.level == 0`` filter which dropped every relative import
    before the allow-list was consulted, so a planted ``from ..broker import
    Broker`` left the whole file green.

    BLANKET REJECTION RATHER THAN RESOLUTION, for W-9's stated reason: resolving
    ``..adapter`` needs the importing file's package position, which this function
    does not have and must not need -- half its callers are planted strings with
    no file position at all. Threading one through would make the positive limb a
    different code path from the audit itself, which is the shape that lets a
    detector rot.

    ENFORCEABLE BECAUSE ALREADY TRUE: measured across ``src/hfss_agent``, there is
    not one relative import anywhere in the package.
    """
    modules: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules.append("." * node.level + (node.module or ""))
    return modules


def _findings_sources() -> list[Path]:
    files = sorted(_FINDINGS.rglob("*.py"))
    assert files, f"no findings source files found under {_FINDINGS}"
    return files


def _submodule_stems() -> set[str]:
    """The package's own module names, by glob rather than by list."""
    return {path.stem for path in _findings_sources() if path.stem != "__init__"}


def _intra_package_imports(path: Path) -> set[str]:
    """The findings submodules this file imports, by bare name.

    TWO SPELLINGS, AND THE SECOND WAS MISSING. ``from hfss_agent.findings.merge
    import merge_findings`` puts the submodule in the MODULE part, which the first
    branch reads. ``from hfss_agent.findings import merge`` puts it in the NAMES
    part, and the module part is then just ``hfss_agent.findings`` with an empty
    tail -- so the first branch found nothing and the layering rule saw no import
    at all.

    FOUND BY A NEGATIVE CONTROL THAT FAILED TO FIRE, not by reading: a planted
    ``from hfss_agent.findings import merge`` in ``results.py`` left the whole
    suite green. W-9's audit has the identical hole; it has never shown there
    because ``gating`` happens to use the dotted spelling everywhere.

    THE SECOND BRANCH IS FILTERED AGAINST THE REAL MODULE SET, because
    ``from hfss_agent.findings import merge_findings`` imports a FUNCTION and must
    not be read as importing a module. The stems come from the glob, so a new
    submodule is covered without editing anything.
    """
    stems = _submodule_stems()
    names: set[str] = set()
    source = path.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            if _under(node.module, "hfss_agent.findings"):
                tail = node.module[len("hfss_agent.findings") :].lstrip(".")
                if tail:
                    names.add(tail.split(".")[0])
                else:
                    names |= {
                        alias.name for alias in node.names if alias.name in stems
                    }
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if _under(alias.name, "hfss_agent.findings"):
                    tail = alias.name[len("hfss_agent.findings") :].lstrip(".")
                    if tail:
                        names.add(tail.split(".")[0])
    return names


# --- the single axis ---------------------------------------------------------


def test_findings_imports_only_the_allowed_roots() -> None:
    """EVERY import, not merely every ``hfss_agent`` import.

    This is the assertion that makes the polarity real. A denylist would have to
    anticipate ``re``; this refuses it for not being anticipated.

    FAILS IF: any module in ``findings/`` imports something outside the seven
    roots -- including a stdlib name that looks harmless. The one to watch is
    ``hfss_agent.adapter``: Part 4's decision that W-10 does no capping is
    justified by that package being out of reach, and adding it here would strip
    the reason out from under a shipped decision.
    """
    offenders: dict[str, list[str]] = {}
    for path in _findings_sources():
        bad = [
            module
            for module in _imported_modules(path.read_text(encoding="utf-8"))
            if not any(_under(module, root) for root in _ALLOWED_IMPORT_ROOTS)
        ]
        if bad:
            offenders[path.name] = bad
    assert not offenders, (
        f"findings imported modules outside the allow-list: {offenders}. Add the "
        "root to _ALLOWED_IMPORT_ROOTS only with its reason beside it; see this "
        "file's docstring for why the list is closed and why it is not free"
    )


def test_the_allowed_prefix_admits_contract_submodules() -> None:
    """``hfss_agent.contract`` is a PREFIX grant, as in every sibling audit.

    ``receipt`` and ``results`` name ``hfss_agent.contract`` directly today, but a
    module needing a ``tool_io`` type -- ``ValidationReport`` is the one Step 3.3
    will bring -- must not be blocked by an accident of how ``_under`` works.

    FAILS IF: ``_under`` is narrowed to exact equality, which would refuse
    ``hfss_agent.contract.tool_io`` and block the composition step this package
    is built to feed.
    """
    assert _under("hfss_agent.contract.tool_io", "hfss_agent.contract")
    assert _under("hfss_agent.contract.common", "hfss_agent.contract")
    assert _under("collections.abc", "collections.abc")
    assert any(
        _under("hfss_agent.contract.tool_io", root)
        for root in _ALLOWED_IMPORT_ROOTS
    )


def test_the_allowed_prefix_does_not_over_admit() -> None:
    """THE HAZARD AN ALLOW-LIST HAS THAT A DENYLIST DOES NOT.

    A sibling whose name merely STARTS WITH an allowed root sliding in on a
    substring match. ``_under`` requires equality or a dotted boundary, so none of
    these is admitted; if it were loosened to ``startswith(root)`` every name
    below would pass and this is what would notice.

    ``collections`` IS THE LOAD-BEARING ONE HERE and it is not in W-9's version:
    this package admits ``collections.abc`` and must NOT thereby admit
    ``collections``, whose ``Counter`` and ``defaultdict`` are exactly the mutable
    containers a memo cache reaches for.

    FAILS IF: ``_under`` is loosened, or ``collections.abc`` is widened to
    ``collections`` -- which would look like a harmless tidy-up and would open the
    cross-call-state door the detector below exists to close.
    """
    for impostor in (
        "hfss_agent.contracts",
        "hfss_agent.contract_evil",
        "hfss_agent.findings_helpers",
        "hfss_agent.findingsx",
        "collections",
        "typingx",
        "pydantic_settings",
        "dataclasses_json",
        "__future_plans__",
    ):
        assert not any(
            _under(impostor, root) for root in _ALLOWED_IMPORT_ROOTS
        ), f"{impostor!r} must not be admitted by a prefix rule"
    for genuine in (
        "__future__",
        "collections.abc",
        "dataclasses",
        "hfss_agent.contract",
        "hfss_agent.findings.receipt",
        "pydantic",
        "typing",
    ):
        assert any(_under(genuine, root) for root in _ALLOWED_IMPORT_ROOTS)


def test_the_refused_modules_are_refused_and_each_has_a_reason() -> None:
    """The record that these eight were considered, mirroring W-9's own.

    Narrowing or widening the refusal means editing an assertion that states its
    justification, rather than quietly adding a name to a list.

    ``hfss_agent.adapter`` IS THE ONE WITH A SHIPPED DECISION BEHIND IT. Part 4
    concluded that W-10 performs no length-capping because ``sanitize_str`` and
    ``MAX_UNTRUSTED_STR_LEN`` are out of reach; this assertion is what keeps that
    true rather than merely stated.

    FAILS IF: any of the eight is admitted -- as a consequence of the allow-list
    rather than through a second mechanism that could drift away from it.
    """
    for module in _CONSIDERED_AND_REFUSED:
        assert not any(
            _under(module, root) for root in _ALLOWED_IMPORT_ROOTS
        ), f"{module!r} is refused for W-10; see _CONSIDERED_AND_REFUSED"
    assert "hfss_agent.adapter" in _CONSIDERED_AND_REFUSED
    assert "re" in _CONSIDERED_AND_REFUSED


def test_every_permitted_root_has_a_live_use_behind_it() -> None:
    """AN ALLOW-LIST ENTRY NOTHING USES IS A PERMISSION NOBODY EXAMINED.

    This build has a recorded failure of exactly that shape -- a planned list with
    entries no producer filled -- so the list is held to the package rather than
    to a plan. Each of the seven roots must be named by at least one file.

    FAILS IF: a root is added speculatively, or an import is removed from ``src/``
    and its permission left behind. Either direction is a real edit: the second
    means the list now grants more than the package needs.
    """
    named: set[str] = set()
    for path in _findings_sources():
        for module in _imported_modules(path.read_text(encoding="utf-8")):
            for root in _ALLOWED_IMPORT_ROOTS:
                if _under(module, root):
                    named.add(root)
    assert named == set(_ALLOWED_IMPORT_ROOTS), (
        f"permissions with no live use: {sorted(set(_ALLOWED_IMPORT_ROOTS) - named)}"
    )


def test_only_validation_error_is_named_from_pydantic() -> None:
    """THE WIDEST PERMISSION ON THE LIST, PINNED TO WHAT IT ACTUALLY BUYS.

    ``findings/`` names exactly one pydantic symbol -- ``ValidationError``, in
    ``receipt.py``. Naming the ROOT admits far more, and the notable ones are
    measured rather than guessed: ``BaseModel``, ``TypeAdapter``, ``Field``,
    ``create_model``, ``validate_call``, and the path-validating types
    ``FilePath``, ``DirectoryPath``, ``NewPath``, plus ``AnyUrl``/``FileUrl``.

    WHY THE ROOT IS ADMITTED ANYWAY, rather than narrowing to
    ``pydantic.ValidationError``. The forcing pass calls ``Finding.model_validate``
    and ``model_dump`` already, so this package is coupled to pydantic's behaviour
    whatever its import line says; narrowing the import would constrain the
    spelling while leaving the coupling. And ``BaseModel`` is a legitimate future
    need -- Step 3.3 composes a ``ValidationReport``.

    THE ONE THING WORTH KNOWING, stated rather than left implicit: ``FilePath``
    and ``DirectoryPath`` VALIDATE BY TOUCHING THE FILESYSTEM (an existence
    check). That is a metadata-only read, which ``tests/boundary/
    test_file_io_audit.py`` places explicitly outside the file-I/O invariant
    ("the invariant targets file CONTENT and NAMESPACE mutation, not existence
    checks") -- so admitting the root does not breach that boundary. It is
    recorded here because a reader meeting ``pydantic`` on an allow-list in a
    package that may not name ``pathlib`` deserves to know the two facts sit
    together on purpose.

    FAILS IF: a second pydantic symbol is imported without this permission being
    re-examined -- which is the moment to decide whether the root grant is still
    the right shape.
    """
    named: dict[str, list[str]] = {}
    for path in _findings_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "pydantic"
            ):
                named.setdefault(path.name, []).extend(
                    alias.name for alias in node.names
                )
    assert named == {"receipt.py": ["ValidationError"]}, (
        f"the pydantic surface changed: {named}. Re-read this test's docstring "
        "before widening it"
    )


def test_no_findings_file_calls_a_capability_builtin() -> None:
    """Builtins need no import, so the allow-list cannot see them.

    FAILS IF: any module calls ``open``, ``eval``, ``exec``, ``compile`` or
    ``__import__``. ``__import__`` is the one that would reintroduce every module
    the allow-list just refused, so its absence is what makes the list mean
    anything.
    """
    offenders: dict[str, list[str]] = {}
    for path in _findings_sources():
        called = {
            node.func.id
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        bad = sorted(called & set(_FORBIDDEN_BUILTINS))
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"findings called a capability builtin: {offenders}"


# --- the module chain: this package's analogue of gate independence ----------


def test_the_module_chain_has_no_cycle_and_flows_one_way() -> None:
    """THE LAYERING, ASSERTED. ``results`` <- ``receipt``/``render`` <- ``merge``
    <- ``__init__``.

    NOT gate independence, which has no analogue here -- gating partitions itself
    into four peers plus three support files and forbids peer-to-peer imports.
    This package is a chain, and what matters is that it stays acyclic and
    one-directional: ``results`` holds the types and must import no sibling, and
    ``receipt`` must not import ``merge`` (the gate does not know about the
    stream that drives it).

    THE PRECEDENT FOR ASSERTING IT AT ALL is W-9's own lesson, written at the top
    of its audit: the ``gates.py`` import cycle was present in an AST dump read
    only for its summary line. A cycle here would be equally invisible.

    FAILS IF: ``results`` grows an import of any sibling; ``receipt`` imports
    ``merge`` or ``render``; or ``render`` imports ``receipt`` or ``merge``.
    Verified against a broken tree in BOTH spellings -- a planted
    ``from hfss_agent.findings import merge`` in ``results.py`` is what exposed
    that ``_intra_package_imports`` saw only the dotted one.
    """
    permitted: dict[str, set[str]] = {
        "results.py": set(),
        "receipt.py": {"results"},
        "render.py": {"results"},
        "merge.py": {"receipt", "results"},
        "__init__.py": {"merge", "receipt", "render", "results"},
    }
    actual = {
        path.name: _intra_package_imports(path) for path in _findings_sources()
    }
    assert set(actual) == set(permitted), (
        f"the module set changed: {sorted(set(actual) ^ set(permitted))}. A new "
        "module needs a row here stating what it may import"
    )
    offenders = {
        name: sorted(imports - permitted[name])
        for name, imports in actual.items()
        if imports - permitted[name]
    }
    assert not offenders, f"a module imported outside its layer: {offenders}"


# --- CLAUSE (d), STRUCTURALLY: the half Part 4's tests cannot prove ----------


_LOOKUP_METHODS = ("get", "setdefault", "pop")


def _is_computed_key(node: ast.AST) -> bool:
    """A lookup key derived from an object or a call, rather than written down.

    ``ROUTES[finding.rule_id]`` and ``ROUTES.get(str(x))`` are computed;
    ``problem["loc"]`` is a constant, and ``list[Finding]`` is an annotation whose
    slice is a bare ``Name``. Every non-annotation subscript in this package has a
    CONSTANT slice -- measured -- so admitting ``Name`` costs nothing and keeps
    every annotation in the package legal without special-casing annotations.
    """
    return isinstance(node, ast.Attribute | ast.Call)


def _root_name(node: ast.AST) -> str | None:
    """The base ``Name`` of an attribute or subscript chain, if there is one.

    ``FindingReceipt.seen.append`` bottoms out at ``FindingReceipt``. Written
    because both detectors below were measured missing a TWO-LEVEL chain: a check
    requiring ``isinstance(node.value, ast.Name)`` sees ``a.b`` and not ``a.b.c``,
    and the second is the spelling a class-level container actually takes.
    """
    while isinstance(node, ast.Attribute | ast.Subscript):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _content_reading_operations(source: str) -> list[str]:
    """Every construct that could let an untrusted string steer a decision.

    FOUR RULES, EACH AN ALLOW-LIST, AND EACH CLOSING A DIFFERENT DOOR:

      * A METHOD NAME OUTSIDE ``_ALLOWED_METHOD_NAMES``. An AST cannot know a
        receiver's type, so "no string method that reads content" is
        unenforceable; "only these names may be called" is. It fails closed on
        ``startswith``, ``lower``, ``find``, ``split``, ``format``, ``replace``
        and every other spelling that reads meaning.
      * A COMPARISON WITH A STRING-LITERAL OPERAND. ``x == "gate"``,
        ``"admin" in x`` (a substring search) and ``x in "abc"`` all decide
        something from what a string SAYS. Measured across this package: ZERO
        exist today, so the rule costs nothing and refuses the next one.
      * ``getattr`` WITH A COMPUTED NAME. Selecting an attribute by an untrusted
        string is the sharpest form of "a code path chosen by content". All three
        call sites here pass a bare ``Name`` bound to a wrapper-owned constant
        (``EVIDENCE_RULES``' field names, ``ANY_TYPED_FIELDS``' components,
        ``_CLAIMED_ID_ATTR``), so requiring ``Name`` or ``Constant`` holds today
        and refuses ``getattr(obj, finding.rule_id)``.

      * A TABLE LOOKUP KEYED ON A COMPUTED VALUE. ``ROUTES[finding.rule_id]`` and
        ``ROUTES.get(finding.rule_id)`` select a value -- and therefore a
        behaviour -- from what an untrusted string SAYS, without calling any
        content-reading method at all. FOUND BY THE POSITIVE LIMB RATHER THAN BY
        REASONING: ``.get`` is on the method allow-list because
        ``_claimed_finding_id`` needs it for a dict candidate, so a planted
        routing table passed the first three rules cleanly.

        THE CONTAINER'S SCOPE IS WHAT SEPARATES ROUTING FROM GROUPING, and the
        distinction is Part 3's, not invented here. ``merge._id_anomalies`` does
        ``positions_by_id.setdefault(finding.finding_id, [])`` -- a lookup keyed on
        an untrusted id -- and argues at length that "GROUPING BY AN UNTRUSTED
        VALUE IS NOT BRANCHING ON ONE ... no code path is selected, no capability
        is chosen, and the same statements execute whatever the ids hold." What
        makes that true is that the container is a LOCAL ACCUMULATOR built inside
        the call, whose contents become data. A MODULE-LEVEL table is the opposite:
        it exists before the call, its entries were chosen by whoever wrote the
        module, and selecting one is selecting a behaviour. So this rule reports a
        computed-key lookup only on a module-level name, which admits the one real
        site and refuses the routing table.

    A ``match`` STATEMENT WITH A STRING PATTERN is caught by the second rule's
    sibling clause below: ``ast.MatchValue`` carrying a string constant is the
    same decision written with different syntax, and this package has no ``match``
    statement to be broken by refusing it.

    WHAT THIS DOES NOT PROVE, stated so the claim stays the size of the mechanism:
    it reads SYNTAX, not dataflow. A wrapper-owned string that a producer had
    influenced upstream would pass every rule here. That is why Part 4's
    behavioural differential is not redundant with this file.
    """
    tree = ast.parse(source)
    module_names = _module_level_names(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _is_computed_key(node.slice):
            if _root_name(node.value) in module_names:
                found.append(f"line {node.lineno}: table lookup by computed key")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr not in _ALLOWED_METHOD_NAMES:
                found.append(f"line {node.lineno}: .{node.func.attr}()")
            elif (
                node.func.attr in _LOOKUP_METHODS
                and node.args
                and _is_computed_key(node.args[0])
                and _root_name(node.func.value) in module_names
            ):
                found.append(
                    f"line {node.lineno}: table .{node.func.attr}() by computed key"
                )
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "getattr" and len(node.args) >= 2:
                name_argument = node.args[1]
                if not isinstance(name_argument, ast.Name | ast.Constant):
                    found.append(
                        f"line {node.lineno}: getattr with a computed name"
                    )
        elif isinstance(node, ast.Compare):
            for operand in (node.left, *node.comparators):
                if isinstance(operand, ast.Constant) and isinstance(
                    operand.value, str
                ):
                    found.append(f"line {node.lineno}: comparison to a string")
        elif isinstance(node, ast.MatchValue):
            if isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, str
            ):
                found.append(f"line {node.lineno}: match on a string pattern")
    return sorted(set(found))


def test_no_findings_file_reads_the_content_of_a_string_to_decide_anything() -> None:
    """§6.6 CLAUSE (d), STRUCTURALLY -- the claim this file owns.

    "No untrusted string selects a capability, a code path reaching one, a tier,
    or a file path." Part 4 proved the behavioural half; this proves that no such
    decision EXISTS to be steered.

    THE THREE BRANCHES PART 4 ADMITTED SURVIVE THIS CHECK, and that is the
    calibration: ``merge``'s ``finding_id.strip()``, the evidence rules'
    ``value.strip()``, and ``str(problem["loc"][0]) in declared``. The first two
    call an allowed method; the third compares against a NAME (the wrapper's own
    ``declared`` set), not a literal. A rule that refused them would fail the
    package on the day it shipped.

    FAILS IF: a content-reading method appears (``startswith`` and ``lower`` are
    the plausible ones -- "route findings whose rule_id starts with gate."), a
    comparison against a string literal appears, a ``match`` on a string pattern
    appears, or ``getattr`` is called with a computed attribute name.
    """
    offenders: dict[str, list[str]] = {}
    for path in _findings_sources():
        reads = _content_reading_operations(path.read_text(encoding="utf-8"))
        if reads:
            offenders[path.name] = reads
    assert not offenders, (
        f"findings read string content to decide something: {offenders}. §6.6(d) "
        "permits blankness tests and wrapper-owned allow-list membership; see "
        "this file's docstring for the narrowed claim"
    )


def test_the_content_reading_detector_finds_every_shape_it_claims_to() -> None:
    """THE POSITIVE LIMB, and it is the hard part.

    An "appears nowhere" assertion needs a companion showing the same code finding
    the pattern somewhere, or the detector can silently stop looking and stay
    green forever. W-9's audit states the standard this must meet: "a positive
    limb that probes only the spellings the scanner already handles proves nothing
    about the ones it does not." So every branch shape is planted, not only the
    ones the rules were written around.

    FAILS IF: any rule stops firing -- a typo'd attribute name, a walk that no
    longer visits, an ``ast`` node that changed shape.
    """
    caught = {
        # --- content-reading methods, the whole family -------------------------
        "startswith": "if finding.rule_id.startswith('gate.'): pass",
        "endswith": "if finding.finding_id.endswith('-pass'): pass",
        "lower": "x = finding.rule_id.lower()",
        "casefold": "x = finding.rule_id.casefold()",
        "split": "x = finding.rule_id.split('.')",
        "replace": "x = finding.reason_flagged.replace('a', 'b')",
        "find": "x = finding.template_text.find('approve')",
        "index": "x = finding.template_text.index('approve')",
        "count": "x = finding.template_text.count('x')",
        "format": "x = 'route {}'.format(finding.rule_id)",
        "partition": "x = finding.rule_id.partition('.')",
        "encode": "x = finding.rule_id.encode()",
        "removeprefix": "x = finding.rule_id.removeprefix('gate.')",
        # --- comparisons against a literal, every operator ---------------------
        "equality to a literal": "if finding.rule_id == 'gate.freshness': pass",
        "inequality to a literal": "if finding.rule_id != 'gate': pass",
        "substring search": "if 'approve' in finding.template_text: pass",
        "negative substring": "if 'x' not in finding.rule_id: pass",
        "membership in a literal": "if finding.severity in 'abc': pass",
        "ordering against a literal": "if finding.rule_id < 'm': pass",
        "chained comparison": "if 'a' < finding.rule_id < 'z': pass",
        # --- table lookup keyed on content -------------------------------------
        # THE FIRST OF THESE IS WHY THIS RULE EXISTS. ``.get`` is on the method
        # allow-list (``_claimed_finding_id`` needs it), so a routing table passed
        # every other rule cleanly until the positive limb planted one.
        "table .get() by content": (
            "ROUTES = {'gate.freshness': 1}\n"
            "x = ROUTES.get(finding.rule_id)\n"
        ),
        "table subscript by content": (
            "ROUTES = {'gate.freshness': 1}\n"
            "x = ROUTES[finding.rule_id]\n"
        ),
        "table setdefault by content": (
            "ROUTES = {}\n"
            "x = ROUTES.setdefault(finding.rule_id, 1)\n"
        ),
        "table pop by content": (
            "ROUTES = {'a': 1}\n"
            "x = ROUTES.pop(finding.rule_id, None)\n"
        ),
        "table lookup by a computed key": (
            "ROUTES = {'a': 1}\n"
            "x = ROUTES[str(finding.rule_id)]\n"
        ),
        "table lookup through a class attribute": (
            "class Router:\n"
            "    table = {}\n"
            "def route(finding):\n"
            "    return Router.table[finding.rule_id]\n"
        ),
        # --- a match statement, which no rule was written around ---------------
        "match on a string": (
            "match finding.rule_id:\n"
            "    case 'gate.freshness':\n"
            "        pass\n"
        ),
        # --- reflection selected by content ------------------------------------
        "getattr with an attribute name": "x = getattr(obj, finding.rule_id)",
        "getattr with a subscript name": "x = getattr(obj, parts[0])",
        "getattr with a call": "x = getattr(obj, str(finding.rule_id))",
        # --- an f-string reaching a path ---------------------------------------
        # NOTE: this is caught by the METHOD rule (``.open``), not by a path rule.
        # The import allow-list and the builtin rule are what actually stop a path
        # being constructed at all; this shows the third door is closed too.
        "f-string path via a method": (
            "p = Path(f'/tmp/{finding.rule_id}')\n"
            "p.open('w')\n"
        ),
    }
    for label, source in caught.items():
        assert _content_reading_operations(source), (
            f"the detector missed a {label}"
        )

    # THE NARROWING HALF: every one of these is a shape this package already
    # contains, and none may be flagged -- or the rule fails the package on the
    # day it ships. The first three are the exact branches Part 4 admitted.
    permitted = {
        "the finding_id blankness test": (
            "if not finding.finding_id.strip(): pass"
        ),
        "the evidence blankness test": "return bool(value.strip())",
        "the wrapper-owned allow-list membership": (
            "declared = set(Finding.model_fields)\n"
            "x = str(problem['loc'][0]) in declared\n"
        ),
        "joining wrapper-owned parts": "x = ', '.join(names)",
        "getattr with a loop variable": (
            "for name, rule in EVIDENCE_RULES:\n"
            "    x = getattr(finding, name)\n"
        ),
        "getattr with a module constant": (
            "x = getattr(candidate, _CLAIMED_ID_ATTR, None)"
        ),
        "an identity comparison": "if node_type is dict: pass",
        "a None presence test": "if finding.suggested_action is not None: pass",
        "an isinstance test": "if isinstance(candidate, Finding): pass",
        "an integer membership test": "if id(node) in seen: pass",
        "a length comparison": "if len(positions) > 1: pass",
        "a truthiness test on a wrapper list": "if non_inert: pass",
        "comparing two closed Literals": "if finding.source == arrived_on: pass",
        "list and dict operations": (
            "found.append(1)\n"
            "found.extend([2])\n"
            "seen.add(3)\n"
            "positions_by_id.setdefault('k', []).append(0)\n"
        ),
        "pydantic operations": (
            "payload = candidate.model_dump(warnings=False)\n"
            "validated = Finding.model_validate(payload)\n"
            "problems = error.errors(include_url=False)\n"
        ),
        # --- the lookup rule's narrowing half, and the real site it must admit --
        # THIS IS ``merge._id_anomalies``' ACTUAL LINE. Part 3 argued at length
        # that grouping by an untrusted value is not branching on one; the
        # container is a local accumulator built inside the call, so no code path
        # is selected and the result is data.
        "grouping into a local accumulator by an untrusted id": (
            "def anomalies(accepted):\n"
            "    positions_by_id = {}\n"
            "    for index, finding in enumerate(accepted):\n"
            "        positions_by_id.setdefault(finding.finding_id, []).append(index)\n"
            "    return positions_by_id\n"
        ),
        "a local dict subscripted by an untrusted id": (
            "def collect(finding):\n"
            "    seen = {}\n"
            "    seen[finding.finding_id] = 1\n"
            "    return seen\n"
        ),
        "a constant-key lookup on pydantic's error dict": (
            "x = problem['loc']\ny = problem['loc'][0]\nz = problem['type']\n"
        ),
        "annotation subscripts": (
            "accepted: list[Finding] = []\n"
            "positions_by_id: dict[str, list[int]] = {}\n"
            "ANY_TYPED_FIELDS: tuple[tuple[str, ...], ...] = ()\n"
        ),
    }
    for label, source in permitted.items():
        assert not _content_reading_operations(source), (
            f"the detector wrongly flagged {label}; it would block a shape this "
            "package already contains"
        )


def test_the_three_admitted_branches_are_still_exactly_three() -> None:
    """THE CALIBRATION AGAINST PART 4's ENUMERATION, and where it has moved.

    Part 4 enumerated three branches legitimately taking an untrusted string as an
    operand. Re-derived here over the package as it now stands, the ``strip``
    sites are exactly those three -- two blankness tests and the allow-list
    membership.

    PART 7's OWN ENUMERATION FOUND TWO MORE BRANCH SITES THAN PART 4's, and they
    are reported rather than quietly admitted: ``render`` tests
    ``suggested_action is not None`` and ``claimed is None``. Both arrived with
    ``render.py``, which did not exist when Part 4 enumerated. NEITHER READS
    CONTENT: they compare by IDENTITY against ``None``, and a ``str`` is never
    ``None`` whatever it says, so no string value can change either outcome. They
    are PRESENCE tests -- "is this optional field set" -- which is the same
    question W-6 asks of its message list. So the count of CONTENT-reading
    branches is unchanged at three.

    FAILS IF: a fourth ``strip`` appears (a new blankness test is a real decision
    -- Part 5 measured that blankness is narrower than "invisible", so each site
    inherits that limitation), or one of the three disappears.
    """
    strip_sites: dict[str, int] = {}
    for path in _findings_sources():
        count = sum(
            1
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "strip"
        )
        if count:
            strip_sites[path.name] = count
    assert strip_sites == {"merge.py": 1, "receipt.py": 2}, (
        f"the blankness-test sites moved: {strip_sites}"
    )


# --- cross-call state: ported, and one part strengthened ---------------------
#
# W-9's DETECTOR PORTS, AND THE REASON IT APPLIES HERE IS ITS OWN, not an analogy.
# Gating needs it because ADR-30 dec. 2 dropped ``evaluated_at`` on the grounds
# that a gate is a pure function of the snapshot. W-10 needs it because two
# guarantees rest on the same property and are already pinned:
# ``test_two_merges_of_the_same_inputs_produce_equal_receipts`` and the renderer's
# byte-determinism. A module-level counter or a memo would break both with zero
# imports, which is why the allow-list above cannot close this door alone.
#
# ONE PART IS STRENGTHENED RATHER THAN COPIED, AND IT IS GATING'S OWN RULE THAT
# REQUIRES IT. That file flags the mutated-CLASS-ATTRIBUTE form and deliberately
# does NOT guard it: "This package contains no classes, so guarding it would be a
# check derived from imagination rather than from a producer -- ADR-28 dec. 4's
# rule." THAT GROUND DOES NOT HOLD HERE. ``results.py`` declares two classes,
# ``RejectedFinding`` and ``FindingReceipt``, so the construct exists and the same
# rule now points the other way. Note that ``frozen=True`` does NOT close it:
# frozen forbids INSTANCE attribute assignment and says nothing about writing an
# attribute on the class object itself.
#
# ONE PART IS ANTICIPATORY AND SAID TO BE. Gating guards the mutable-default form
# because ``target_coverage.evaluate(snapshot, target_frequency_hz=None)`` means
# "the construct already exists here". THIS PACKAGE HAS NO DEFAULT ARGUMENT AT
# ALL -- measured, zero across four files, and ``merge_findings`` is deliberately
# undefaulted on both parameters (Part 1 asserts it). The guard is kept anyway,
# and the honest reason is not "a producer exists" but "the detector is one
# expression and the hazard needs no import to arrive". Recorded as the weaker
# justification it is, rather than borrowed from gating's stronger one.


def _is_constant_default(node: ast.expr) -> bool:
    """Whether a default argument is a value that cannot carry state between calls."""
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

    FOUR BINDING FORMS, and the last two are widenings over W-9's version that
    were each forced by a probe rather than reasoned into existence:

      * ``Assign`` / ``AnnAssign`` -- the module-level constant or memo.
      * ``def`` -- a function object carries attributes like any other, so
        ``evaluate.calls = 0`` survives between calls. W-9 already collects this.
      * ``class`` -- ADDED HERE. W-9 flags the mutated-class-attribute form and
        deliberately does NOT guard it, on the stated ground that "this package
        contains no classes, so guarding it would be a check derived from
        imagination rather than from a producer". ``results.py`` declares two, so
        the same rule now points the other way. ``frozen=True`` does not close it:
        frozen forbids INSTANCE attribute assignment and says nothing about
        writing an attribute on the class object itself.
      * ``import`` -- ADDED HERE, and it is the one that was invisible. An
        imported name is bound at module level exactly as an assigned one is, so
        ``FindingReceipt.seen = x`` in ``merge.py`` -- writing a class attribute on
        a class defined one module over -- survives between calls and escaped the
        scan entirely, because the name never entered ``watched``. Measured NOT
        CAUGHT before this was added, and it is the spelling a real violation would
        most likely take here, since every class in this package is imported by the
        module that would write to it. W-9 has the same hole; it is narrower there
        because ``gating`` imports only contract types.
    """
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                names |= _bound_names(target)
        elif isinstance(node, ast.AnnAssign):
            names |= _bound_names(node.target)
        elif isinstance(
            node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
        ):
            names.add(node.name)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
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
    """Whether writing ``target`` writes into a watched module-level name.

    CHAIN-WALKING RATHER THAN ONE LEVEL, and the widening was forced by the
    positive limb rather than chosen. W-9's version requires
    ``isinstance(target.value, ast.Name)``, which sees ``A.b`` and misses
    ``A.b.c`` -- and ``FindingReceipt.seen.append(x)``, a write into a class-level
    container, is exactly the two-level spelling. Measured: it came back NOT
    CAUGHT before ``_root_name`` was introduced.
    """
    if isinstance(target, ast.Subscript | ast.Attribute):
        return _root_name(target) in watched
    return isinstance(target, ast.Name) and target.id in watched


def _cross_call_state(source: str) -> list[str]:
    """Every construct that lets a value survive between two calls, with its line."""
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
            # ``kw_defaults`` carries a real ``None`` for a keyword-only argument
            # with NO default; skipping those keeps the allow-list from reporting
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
                and node.func.attr in _MUTATING_METHODS
                and _root_name(node.func.value) in watched
            ):
                # ``_root_name`` rather than a bare ``Name`` check -- see
                # ``_writes_into`` for the two-level chain that forced it.
                found.append(
                    f"line {node.lineno}: "
                    f"{_root_name(node.func.value)}.{node.func.attr}()"
                )
    return sorted(set(found))


def test_no_findings_file_holds_state_between_calls() -> None:
    """W-10's OUTPUT IS A PURE FUNCTION OF ITS TWO STREAMS, and this is the half
    the import allow-list cannot enforce.

    A module-level counter, a memo dict, a mutable default, or an attribute hung
    on a function or a CLASS makes two merges of equal inputs differ with zero
    imports. Two shipped guarantees rest on that not happening --
    ``test_two_merges_of_the_same_inputs_produce_equal_receipts`` and the
    renderer's byte-determinism.

    FAILS IF: any of those constructs appears. The class-attribute form is the one
    gating cannot check and this package can, because ``results.py`` has two
    classes.
    """
    offenders: dict[str, list[str]] = {}
    for path in _findings_sources():
        writes = _cross_call_state(path.read_text(encoding="utf-8"))
        if writes:
            offenders[path.name] = writes
    assert not offenders, (
        f"findings holds state between calls: {offenders}. A receipt is a pure "
        "function of the two streams it was handed"
    )


def test_the_cross_call_state_detector_finds_every_shape_it_claims_to() -> None:
    """THE POSITIVE LIMB, and the NARROWING one beside it.

    THE CLASS BLOCK IS WHAT THIS FILE ADDS TO W-9's. Gating flags that form and
    does not guard it, on the stated ground that it has no classes; this package
    has two, so the same rule requires the guard rather than the flag.

    FAILS IF: a detector rule stops firing, or starts flagging a shape the package
    already contains -- the module-level constants in ``receipt.py`` and
    ``render.py`` are the ones that would break first.
    """
    caught = {
        "global counter": (
            "_CALLS = 0\ndef merge(a):\n    global _CALLS\n    _CALLS += 1\n"
        ),
        "memo write": "_MEMO = {}\ndef merge(a):\n    _MEMO[a] = 1\n",
        "memo update": "_MEMO = {}\ndef merge(a):\n    _MEMO.update({'k': 1})\n",
        "list append": "_SEEN = []\ndef merge(a):\n    _SEEN.append(a)\n",
        "del from state": "_MEMO = {}\ndef merge(a):\n    del _MEMO['k']\n",
        "closure state": (
            "def _make():\n"
            "    n = 0\n"
            "    def inner():\n"
            "        nonlocal n\n"
            "        n += 1\n"
            "    return inner\n"
        ),
        "function attribute write": "def merge(a):\n    merge.calls = 1\n",
        "function attribute increment": "def merge(a):\n    merge.calls += 1\n",
        # --- THE CLASS FORMS, which gating flags and does not guard ------------
        "class attribute write": (
            "class FindingReceipt:\n"
            "    pass\n"
            "def merge(a):\n"
            "    FindingReceipt.seen = a\n"
        ),
        "class attribute increment": (
            "class FindingReceipt:\n"
            "    count = 0\n"
            "def merge(a):\n"
            "    FindingReceipt.count += 1\n"
        ),
        "class attribute del": (
            "class FindingReceipt:\n"
            "    pass\n"
            "def merge(a):\n"
            "    del FindingReceipt.seen\n"
        ),
        "mutating a class-level container": (
            "class FindingReceipt:\n"
            "    seen = []\n"
            "def merge(a):\n"
            "    FindingReceipt.seen.append(a)\n"
        ),
        "a frozen dataclass is not exempt": (
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class RejectedFinding:\n"
            "    reason: str\n"
            "def merge(a):\n"
            "    RejectedFinding.seen = a\n"
        ),
        # --- the IMPORTED-NAME forms, which were invisible until Part 7 --------
        # This is the spelling a real violation here would take: every class in
        # this package is imported by the module that would write to it.
        "attribute write on an imported class": (
            "from hfss_agent.findings.results import FindingReceipt\n"
            "def merge(a):\n"
            "    FindingReceipt.seen = a\n"
        ),
        "attribute write on an imported module": (
            "import hfss_agent.findings.results as r\n"
            "def merge(a):\n"
            "    r.CACHE = a\n"
        ),
        "mutating a container on an imported class": (
            "from hfss_agent.findings.results import FindingReceipt\n"
            "def merge(a):\n"
            "    FindingReceipt.seen.append(a)\n"
        ),
        # --- non-constant defaults ---------------------------------------------
        "dict() default": "def merge(a, _m=dict()):\n    return _m\n",
        "list() default": "def merge(a, _s=list()):\n    return _s\n",
        "dict literal default": "def merge(a, _m={}):\n    return _m\n",
        "list literal default": "def merge(a, _s=[]):\n    return _s\n",
        "comprehension default": "def merge(a, _s=[x for x in ()]):\n    return _s\n",
        "keyword-only mutable default": "def merge(a, *, _m={}):\n    return _m\n",
        "module mutable bound through a default": (
            "_MEMO = {}\ndef merge(a, memo=_MEMO):\n    memo[a] = 1\n"
        ),
    }
    for label, source in caught.items():
        assert _cross_call_state(source), f"the detector missed a {label}"

    permitted = {
        "constant tuple, never written": (
            "EVIDENCE_FIELDS = ('inspected',)\n"
            "def check(f):\n"
            "    return EVIDENCE_FIELDS\n"
        ),
        "constant frozenset": (
            "_ALLOWED = frozenset({'join'})\n"
            "def check(f):\n"
            "    return 'join' in _ALLOWED\n"
        ),
        "local dict mutated": (
            "def merge(a):\n"
            "    seen = {}\n"
            "    seen['k'] = 1\n"
            "    return seen\n"
        ),
        "local list appended": (
            "def merge(a):\n"
            "    out = []\n"
            "    out.append(1)\n"
            "    return out\n"
        ),
        "reading a class, not writing it": (
            "class FindingReceipt:\n"
            "    pass\n"
            "def merge(a):\n"
            "    return FindingReceipt(accepted=(), rejected=())\n"
        ),
        "constructing a dataclass": (
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class RejectedFinding:\n"
            "    reason: str\n"
            "def merge(a):\n"
            "    return RejectedFinding(reason='x')\n"
        ),
        "calling a sibling function": (
            "def _helper(x):\n    return x\ndef merge(a):\n    return _helper(a)\n"
        ),
        "a None default": "def merge(a, target=None):\n    return target\n",
        "a keyword-only argument with no default": (
            "def merge(a, *, gate_findings):\n    return gate_findings\n"
        ),
    }
    for label, source in permitted.items():
        assert not _cross_call_state(source), (
            f"the detector wrongly flagged {label}; it would block a shape this "
            "package already contains"
        )


# --- the meta-test ------------------------------------------------------------


def test_audit_would_catch_a_forbidden_import() -> None:
    """The audit is only meaningful if it detects the violations it is aimed at.

    THE RELATIVE SPELLINGS ARE NOT DECORATION. W-9's audit shipped with a
    ``node.level == 0`` filter that dropped every relative import, and its
    positive limb never noticed because all fourteen planted sources were
    absolute. Both halves are planted here.

    FAILS IF: ``_imported_modules`` stops reporting a spelling the allow-list
    would refuse -- which is exactly how that defect survived a green suite.
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
        "import re",
        "import pathlib",
        "import subprocess",
        "import collections",
        "from collections import Counter",
        "from hfss_agent.adapter.sanitize import sanitize_str",
        "from hfss_agent.broker import Broker",
        "from hfss_agent.gating import evaluate_gates",
        "from hfss_agent.snapshot import assemble_snapshot",
        "import pyaedt",
        "from ansys.aedt.core import Hfss",
        # RELATIVE SPELLINGS OF THE SAME VIOLATIONS.
        "from ..adapter.sanitize import sanitize_str",
        "from ..broker import Broker",
        "from ...hfss_agent.adapter import base",
        "from . import receipt",
        "from .receipt import validate_finding",
        "from .results import FindingReceipt",
    ):
        modules = _imported_modules(source)
        assert modules, f"{source!r} parsed to no module at all"
        assert not all(
            any(_under(module, root) for root in _ALLOWED_IMPORT_ROOTS)
            for module in modules
        ), f"{source!r} must be refused by the allow-list"

    for source in (
        "from __future__ import annotations",
        "from collections.abc import Callable, Iterable",
        "from dataclasses import dataclass",
        "from typing import Any, Literal",
        "from pydantic import ValidationError",
        "from hfss_agent.contract import Finding",
        "from hfss_agent.contract.tool_io import ValidationReport",
        "from hfss_agent.findings.results import FindingReceipt",
    ):
        modules = _imported_modules(source)
        assert all(
            any(_under(module, root) for root in _ALLOWED_IMPORT_ROOTS)
            for module in modules
        ), f"{source!r} must be permitted"
