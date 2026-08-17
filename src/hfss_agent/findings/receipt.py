"""The receipt gate: one candidate in, an exact ``Finding`` or a refusal out.

WHAT THIS GATE ACTUALLY IS, stated first because the obvious reading is wrong. A
"reject findings missing a required field" check, applied to an object that is
already a constructed ``Finding``, CANNOT EVER FIRE -- pydantic refused the
missing field at construction, so by the time such an object exists the check has
nothing to catch. A check that cannot fail is worse than no check, because it
reads as coverage. This module therefore does not perform that check.

WHAT IT DOES INSTEAD IS A RE-VALIDATION FORCING PASS: dump the candidate to plain
data and validate that data back into a ``Finding``. That single operation is
what turns four otherwise-invisible shapes into ordinary refusals, and it was
probed before it was written rather than assumed:

  * ``Finding.model_construct(...)`` builds an object that passes
    ``isinstance(x, Finding)`` with required fields simply ABSENT -- reading one
    raises ``AttributeError``. ``model_dump()`` does not raise on such an object;
    it returns whatever was set. Validating that partial dict raises.
  * A ``Finding`` SUBCLASS declaring an extra field is refused by
    ``extra="forbid"`` on the way back in.
  * A ``Finding`` SUBCLASS adding only a METHOD is NORMALIZED rather than
    refused, and that is the correct outcome rather than a gap -- see
    ``validate_finding``.
  * Wrong-typed fields, and a nested ghost provenance, both surface as ordinary
    validation errors.

THEN A SECOND, INDEPENDENT GATE: EVIDENCE COMPLETENESS. The two are the pair the
runbook names -- "malformed OR evidence-incomplete" -- and they have OPPOSITE
FEASIBILITY, which is why they are two gates and not one. The forcing pass above
catches objects whose SHAPE cannot be established. This one catches an object
whose shape is perfect and whose CONTENT is absent: a ``Finding`` with
``inspected=[]``, ``observed_values={}`` and ``reason_flagged=""`` validates
cleanly against the schema -- measured -- because nothing in ``Finding`` carries
a ``min_length`` or any other constraint. No schema check can ever reach it, so
without this gate a judgment presented with no evidence at all would be handed on
as an accepted finding.

THEN A THIRD GATE: INERT VALUES. Until Part 6 this docstring recorded the hole
below as belonging to a later part, and it now belongs here, so the measurement
is kept and the disclaimer replaced. A ``Finding`` whose ``observed_values``
carries a callable, a ``pathlib.Path`` or a live handle validates CLEANLY through
the forcing pass and the object survives intact: ``observed_values`` and
``applicability.conditions`` are ``dict[str, Any]``, and pydantic does not
validate ``Any``. These are the ONLY two such fields on a ``Finding`` -- derived
by walking ``Finding.model_fields`` and every nested model, not by listing them
from memory, and pinned that way by a test.

The leak was measured end to end rather than reasoned about: a ``Path`` planted
in ``FreshnessEvidence.available_signals``, carried through the REAL
``assemble_snapshot`` and copied verbatim into ``observed_values`` by the REAL
freshness gate, produced a finding whose JSON contained
``"C:\\Users\\Owner\\Documents\\Ansoft\\patch_antenna.aedt"`` -- a filesystem
path including the operator's Windows account name -- and it FLATTENED SILENTLY,
because pydantic serializes a ``Path`` to a plain string without complaint. W-8
drops that path deliberately so no filesystem string crosses into the engine
(``snapshot/assembler._selection``, pinned by
``tests/snapshot/test_path_is_dropped.py``); a finding carrying it back would
defeat that decision from the return path. A callable and a live handle behave
differently and worse in one respect: they survive ``model_dump()``, raise only
on ``model_dump_json()``, and the live handle was measured still carrying a bound
method after the receipt gate had accepted it.

WHAT STILL IS NOT CAUGHT, so the claim stays the size of the mechanism: a
``str`` is inert and may still be hostile text. Control characters and
instruction-shaped prose pass all three gates unchanged. That is Part 4's
envelope and is deliberately untouched here -- an untrusted string and a
non-inert object are different problems.

THE ANNOTATION IS NOT THE ENFORCEMENT. The engine seam is declared
``evaluate(DesignSnapshot) -> list[Finding]``, but the engine is a separately
distributed wheel and that signature is its CLAIM about what it returns. So every
candidate is treated as an object of unknown provenance: nothing is read off one
by bare attribute access, and no method of one is called outside a guard.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from pydantic import ValidationError

from hfss_agent.contract import Finding, FindingSource
from hfss_agent.findings.results import RejectedFinding

# The one attribute this module ever tries to read off an unvalidated candidate,
# and only to label a refusal with. Never to decide anything.
_CLAIMED_ID_ATTR = "finding_id"

_NOT_A_FINDING_DETAIL = (
    "the object supplied is not a Finding instance, so no schema check was "
    "reachable and nothing about its content was examined. Its type is "
    "deliberately not named here: a type name is chosen by whoever wrote the "
    "object, so echoing one would put engine-authored text into a "
    "wrapper-authored field."
)

# TWO STAGES, TWO SENTENCES, BECAUSE ONE SENTENCE COULD BE FALSE. These read as
# near-duplicates and are not: the receipt gate reduces a candidate to plain data
# and then validates that data, and a non-validation failure in EITHER stage ends
# up here. A single detail covering both was measured to lie -- an object whose
# ``model_dump`` returned a hostile ``Mapping`` reduced FINE and then raised
# ``RuntimeError`` during validation, while the detail said it "could not be
# reduced to plain data" and blamed engine-supplied code for what may equally
# have been one of this package's own validators. Stating which stage failed is
# the only version of this that is true in both cases.
_UNDUMPABLE_DETAIL = (
    "the object is a Finding instance but raised while being REDUCED to plain "
    "data, so its contents were never checked. ``model_dump`` is an ordinary "
    "method and a subclass may override it, so the failure arose on the supplied "
    "object's own code path. The underlying error is deliberately not echoed "
    "here: its text is not wrapper-authored."
)

# --- the inert-value gate ----------------------------------------------------
#
# THE TWO FIELDS PYDANTIC DOES NOT VALIDATE, as component paths from the
# ``Finding`` root. DERIVED BY MEASUREMENT, NOT RECALLED: walking
# ``Finding.model_fields`` and every nested model type reports exactly two
# annotations admitting an arbitrary object -- ``observed_values`` and
# ``applicability.conditions``. Everything else bottoms out in ``str``,
# ``str | None``, ``bool``, a closed ``Literal``, or ``dict[str, str]``.
#
# PATHS RATHER THAN NAMES, because one of the two is not a field of ``Finding``
# at all; it is a field of ``Applicability``, one model down. A flat name list
# could not express it and would have quietly walked the wrong thing.
#
# A TEST DERIVES THIS SET FROM THE MODEL AND ASSERTS EQUALITY, so a third
# ``Any`` hole added to the contract fails AT THE DECISION rather than leaking
# past a hand-maintained tuple -- the shape ADR-31 dec. 16 used for the outcome
# partition. This constant is what the walk enforces and what that test compares
# against; there is no second copy.
ANY_TYPED_FIELDS: tuple[tuple[str, ...], ...] = (
    ("observed_values",),
    ("applicability", "conditions"),
)

# WHAT MAY TRAVEL: an ALLOW-LIST OF EXACT TYPES, never a denylist of forbidden
# ones. A denylist is a list of the objects someone thought of; the space of
# objects an engine can construct is not enumerable, and this package inverted an
# audit to allow-list polarity for that reason already.
#
# DERIVED FROM REAL OUTPUT. Swept every snapshot shape the gate suite can build
# through the real ``assemble_snapshot`` -> ``evaluate_gates`` path: 1,134
# evaluations, 4,536 findings, and the union of leaf types across both fields is
# exactly ``{bool, float, int, str}``. Container types encountered: ``dict`` and
# ``list``, nothing else. Maximum nesting depth: 2. Every key at every depth: a
# ``str``. So four of the five entries below are what the wrapper's own output
# actually contains, and the walk cannot refuse it.
#
# ``type(None)`` IS THE FIFTH AND THE SWEEP NEVER PRODUCED ONE, so it is admitted
# deliberately and for a stated reason rather than by analogy. Part 2 already
# fixed ``{"determinable": None}`` as a COMPLETE finding -- see
# ``_empty_evidence_fields``' bound, and ``test_a_null_observed_value_under_a
# _real_key_is_complete``, which pins it as accepted. Refusing ``None`` here
# would silently reverse a bound this module stated two parts ago, from a part
# whose subject is something else entirely. It is also the one entry that cannot
# be faked: ``NoneType`` is NOT SUBCLASSABLE (measured -- ``type 'NoneType' is
# not an acceptable base type``) and admits exactly one instance, so unlike the
# other four it cannot carry state or behaviour under any input.
#
# ``datetime`` IS DELIBERATELY EXCLUDED, AND THIS IS THE ONE PLACE W-8'S
# ALLOW-LIST IS NOT COPIED. ``tests/snapshot/test_inert_leaves.py`` admits it
# because the contract DECLARES two datetime fields, so a JSON round trip
# restores them through the field's own validator. Inside an ``Any`` hole there
# is no declared type to restore anything: measured, a ``datetime`` here
# round-trips to the ``str`` ``'2026-08-03T08:00:00Z'`` and the finding no longer
# equals itself -- which is IDENTICALLY the silent-flattening behaviour of the
# ``pathlib.Path`` this gate exists to catch. Admitting it would admit the very
# failure class. ``Finding`` declares no datetime field anywhere, and the sweep
# produced none.
#
# WHAT A RULE AUTHOR SHOULD DO INSTEAD, stated here and echoed in the refusal
# text, because a refusal that does not say what to do instead gets worked
# around: put the ISO-8601 STRING in ``observed_values``, not the ``datetime``.
# That is not a concession -- it is what crossing this seam does to the value in
# any case, since a ``Finding`` reaches a consumer as JSON. The same answer
# covers a ``pathlib.Path`` (its string form), a ``Decimal`` (``float`` or its
# string form) and an identifier object (its string form). Nothing is lost that
# the wire was ever going to carry.
#
# EXACT TYPE, NOT ``isinstance``, for the two reasons W-8 records and one it does
# not face. A ``str`` subclass carrying state passes ``isinstance`` -- measured
# here, not borrowed: planted as a VALUE it survives the forcing pass with its
# attribute and its method intact, and its JSON is byte-identical to a plain
# string's. ``bool`` subclasses ``int``, so it must be named rather than
# inherited. And the third: a ``dict`` SUBCLASS passes ``isinstance(x, dict)``,
# after which ``x.items()`` dispatches to whatever the engine wrote -- measured
# against an isinstance-based walk, where a subclass whose ``items()`` raises
# took the whole walk down. Exact-type matching is what makes descending safe,
# not merely strict. (Container subclasses do not in fact reach this walk today,
# because stage 2 normalizes them; see ``_carries_a_non_inert_object``, which
# records what that does and does not leave for this check to do.)
INERT_LEAF_TYPES: tuple[type, ...] = (str, int, float, bool, type(None))


def _is_inert(node_type: type) -> bool:
    """Is this exact type one the allow-list admits?

    WRITTEN AS AN IDENTITY CHAIN OVER THE TUPLE, AND ``node_type in
    INERT_LEAF_TYPES`` WOULD BE A SECURITY BUG. This is the least obvious line in
    the module, so it is measured rather than argued:

      * ``type(node) in INERT_LEAF_TYPES`` compares with ``==`` for every entry
        that is not identical. An engine can give its class a METACLASS defining
        ``__eq__``, and Python tries the reflected operation first because the
        metaclass is a subclass of ``type`` -- so the comparison RUNS
        ENGINE-SUPPLIED CODE. Measured: it raised ``RuntimeError`` out of the
        membership test.
      * ``type(node) in frozenset(INERT_LEAF_TYPES)`` is worse, not better: set
        membership hashes first, so a metaclass ``__hash__`` runs instead.
        Measured: it raised too.
      * ``any(node_type is inert for inert in ...)`` compares by IDENTITY only.
        ``is`` dispatches to nothing at all. Measured: returns ``False``, runs
        nothing.

    This is the same rule ADR-9 §6.6 states and Part 2 applied to ``bool()`` and
    ``len()``: untrusted data must never influence control flow. A membership
    test looks nothing like a call, which is exactly why it is worth the
    paragraph -- and note that the hazard only bites the objects this gate exists
    to catch, because an inert type matches the first identity check and never
    reaches a comparison at all.
    """
    return any(node_type is inert for inert in INERT_LEAF_TYPES)


def _carries_a_non_inert_object(root: object) -> bool:
    """Does anything anywhere under ``root`` fail the allow-list?

    THIS FUNCTION CANNOT RAISE, FOR ANY INPUT, AND THAT IS LOAD-BEARING RATHER
    THAN TIDY. It is called from ``validate_finding``'s stage 3, which sits
    OUTSIDE both ``try`` blocks -- the exact position from which Part 2's
    dispatch fall-through sent an ``AttributeError`` escaping a function
    documented never to raise. Widening a guard to cover this call would hide
    that class of bug again, so the property is established instead of caught.
    What makes it true, item by item, each one measured against a real hostile
    object rather than assumed:

      * NOTHING OF THE NODE'S IS EXECUTED. ``type(x)`` and ``id(x)`` dispatch to
        nothing; ``is`` dispatches to nothing; ``_is_inert`` compares by identity
        only. So no ``__iter__``, ``__bool__``, ``__len__``, ``__eq__``,
        ``__hash__``, ``__repr__``, ``keys()`` or ``items()`` of an engine object
        ever runs. Probed against all seven of those raising deliberately.
      * ONLY EXACT ``dict`` AND ``list`` ARE DESCENDED, so ``node.items()`` and
        the ``list`` iteration below are the builtins and cannot be overridden.
        A subclass is not descended into -- it is REPORTED.
        THAT BRANCH IS A SECOND LINE AND NOT THE FIRST, and the distinction is
        measured rather than assumed, because the obvious reading over-credits
        this walk. ``model_dump`` REBUILDS a ``dict`` or ``list`` subclass as an
        exact container at every depth, discarding its attributes and methods and
        without calling its ``items()``, ``keys()`` or ``__iter__`` -- so stage 2
        has already normalized one away before this walk runs, exactly as it
        normalizes a method-only ``Finding`` subclass, and such an object is
        ACCEPTED rather than refused. A ``str`` subclass is NOT rebuilt and does
        reach here. What this branch guarantees is therefore narrower and still
        worth having: that the walk cannot be made to execute a container
        subclass's code even if one ever reaches it.
      * IT TERMINATES ON EVERY INPUT. ``seen`` makes each container be walked
        once, so a cycle -- a dict containing itself, a self-appending list, two
        dicts referring to each other -- is finite. Measured: all three
        terminate, and a cycle DOES reach here, because the forcing pass
        preserves it intact.
      * IT IS ITERATIVE, NOT RECURSIVE, and that is not style. Nests 1,500 deep
        survive construction and the forcing pass, while the default recursion
        limit is 1,000 -- so the natural recursive spelling raises
        ``RecursionError`` on an input the engine controls. Worse, that error
        subclasses ``RuntimeError`` and would be swallowed by the broad guard
        two stages up and misreported as a schema failure. Probed to 5,000 deep
        and 50,000 wide.

    THE ``id()`` PRECONDITION, WRITTEN DOWN BECAUSE COPYING THIS WALK SOMEWHERE
    ELSE COULD BREAK IT SILENTLY. An identity-keyed visited set is only sound
    while every container it has recorded is still ALIVE -- CPython reuses an
    address after collection, so a freed container's id could be matched against
    a different one and a whole subtree skipped. It is sound HERE because every
    node reachable from ``root`` is held by the live ``Finding`` the caller is
    still holding, and additionally by ``pending`` while queued, for the entire
    duration of the walk. Nothing is constructed inside this function and nothing
    can be collected during it. A caller that walked a structure built lazily --
    a generator's output, say -- would not have that guarantee and must not reuse
    this shape.

    SHORT-CIRCUITS AT THE FIRST OFFENDER, deliberately. Counting them all would
    be one more wrapper-owned number for the refusal, and it is declined: it is
    not more actionable (the fix is the same either way), and stopping early
    means the walk touches strictly less of a structure of unknown provenance.

    Returns:
        ``True`` if any leaf, at any depth, in a KEY position or a VALUE
        position, has an exact type the allow-list does not admit.
    """
    seen: set[int] = set()
    # An explicit stack, not the call stack -- see the docstring. Order of
    # traversal is not specified and nothing depends on it: the answer is a
    # single boolean over the whole structure.
    pending: list[object] = [root]
    while pending:
        node = pending.pop()
        node_type = type(node)
        if node_type is dict:
            if id(node) in seen:
                continue
            seen.add(id(node))
            # BOTH HALVES OF EVERY ITEM. Keys are validated to ``str`` by the
            # schema at the TOP level of each site only -- measured: one level
            # deeper an ``int``, a ``tuple``, a ``Path``, a ``datetime`` and
            # ``bytes`` all survive as keys, and a ``Path`` used as a nested key
            # reaches the JSON carrying the account name exactly as a value
            # would. A values-only walk would miss that entirely.
            for key, value in node.items():
                pending.append(key)
                pending.append(value)
            continue
        if node_type is list:
            if id(node) in seen:
                continue
            seen.add(id(node))
            pending.extend(node)
            continue
        if _is_inert(node_type):
            continue
        return True
    return False


# NO ``ALLOWED_CONTAINER_TYPES`` CONSTANT, unlike W-8's walk, and the absence is
# deliberate. There the two containers are handled by one generic branch, so a
# tuple states the rule; here ``dict`` and ``list`` need different bodies (a dict
# yields keys AND values, a list yields items), so a constant beside them would
# be decorative -- a second statement of a fact the two branches already make,
# and one that could drift out of agreement with them. ``tuple`` and ``set`` are
# not containers for this walk's purposes: the sweep produced neither, and both
# flatten to a JSON list, so an in-process consumer and a JSON consumer would see
# different shapes of the same finding.


def _non_inert_detail(sites: list[str]) -> str:
    """The refusal text: which FIELDS carried an object, and nothing more.

    WHAT MAY APPEAR HERE IS NARROWER THAN AT ANY OTHER REFUSAL SITE, and the two
    exclusions are the interesting part.

    THE OFFENDING TYPE IS NOT NAMED. ``_NOT_A_FINDING_DETAIL`` already refuses to
    name a foreign object's type on the grounds that a type name is chosen by
    whoever wrote the object; here that is not merely a convention about naming
    but a measured fact about mutability. ``type(x).__name__``,
    ``__qualname__`` and ``__module__`` are all ASSIGNABLE, to any string
    whatever -- measured, including one carrying ``\\x1b[31m`` and
    ``IGNORE ALL PREVIOUS INSTRUCTIONS``. So echoing a type name is not
    "reporting a type", it is echoing an engine-authored string into a
    wrapper-authored field, and it would do so at the one moment a reader is
    most inclined to trust the text.

    THE LOCATION INSIDE THE FIELD IS NOT NAMED EITHER, for the same reason one
    step further in. A path like ``observed_values['handle']`` reads as
    structural and is not: every component after the first is a KEY, and keys
    below the top level are engine-authored (they are not even validated to
    ``str`` -- see the walk). Naming the root field is safe precisely because it
    is the one component ``Finding`` and ``Applicability`` declare.

    THE DIAGNOSTIC LOSS, STATED RATHER THAN LEFT TO BE DISCOVERED, the way
    ``_schema_detail`` states its named-vs-counted trade: a reader learns THAT a
    field carried an object and WHICH field, and cannot learn WHAT the object was
    or WHERE in the structure it sat. For a rule author that is usually enough,
    because they hold the producing code; for anyone else it is deliberately a
    dead end, and the finding itself is not carried on this record to make up the
    difference. The count is of FIELDS, not of objects -- the walk stops at the
    first offender in each field, so no object count exists to report.
    """
    return (
        f"{len(sites)} field(s) carry an object where only a value may travel: "
        f"{', '.join(sites)}. The finding satisfies the schema in every respect: "
        "these fields are typed dict[str, Any], and pydantic does not validate "
        "Any, so no schema check can reach this. Only str, int, float, bool and "
        "None may travel, at any depth, in a key or a value; a datetime, a "
        "filesystem path, a callable, a live handle, a str subclass, a tuple or "
        "a set may not. A rule reporting a timestamp, a path or an identifier "
        "should place its STRING form here -- a finding reaches a consumer as "
        "JSON, so that is what crossing this seam does to the value in any case. "
        "Which object it was, and where inside the field it sat, are deliberately "
        "not named: a type name is assignable to any string by whoever wrote the "
        "object, and a nested key is engine-authored, so echoing either would put "
        "engine-authored text into a wrapper-authored field."
    )


def _non_inert_fields(finding: Finding) -> list[str]:
    """The ``Any``-typed fields carrying an object, in ``ANY_TYPED_FIELDS`` order.

    A LIST RATHER THAN A BOOL, so the refusal can name which field rather than
    only that one exists -- ``_empty_evidence_fields``' shape, for its reason.

    RUN ON A VALIDATED ``Finding``, WHICH IS WHAT MAKES THE ATTRIBUTE WALK SAFE.
    After stage 2 both components resolve on exact types -- ``Finding`` and
    ``Applicability``, each a fresh ``model_validate`` result -- so ``getattr``
    here reaches wrapper-constructed objects and cannot run a property an engine
    wrote. Before stage 2 it could not be written at all: a ``model_construct``
    ghost's ``observed_values`` can be a bare ``str`` (measured), and reading
    attributes off an object of unknown provenance to make a decision is what
    ADR-9 forbids.

    THE BOUND, STATED RATHER THAN IMPLIED, because a caller must not assume more
    than this makes true:

      * IT IS A CLAIM ABOUT LEAF TYPES, NOT ABOUT SHAPE. A structure of nothing
        but dicts and ints that contains ITSELF passes here -- every leaf is
        inert -- and still raises ``PydanticSerializationError`` on
        ``model_dump_json``. Measured. Accepting a finding therefore does NOT
        promise a consumer that it serializes. Refusing a cycle was considered
        and declined: a cycle carries no behaviour, which is what this gate is
        about, and pydantic already refuses it loudly at the point of use rather
        than silently -- which is exactly what a ``Path`` does NOT do, and the
        reason this gate exists at all.
      * IT IS A CLAIM ABOUT TYPES, NOT ABOUT MEANING. A wrong-but-inert value is
        out of scope, as it is for W-8's equivalent.
      * IT SAYS NOTHING ABOUT STRINGS. A ``str`` is inert and may carry control
        characters and instruction-shaped prose; Part 4 owns that envelope.
      * IT COVERS THESE TWO FIELDS AND NEEDS TO COVER NO OTHERS. Every other
        field on a ``Finding`` is declared with a type pydantic enforces, so
        stage 2 has already established it.
    """
    offending: list[str] = []
    for path in ANY_TYPED_FIELDS:
        node: object = finding
        for component in path:
            node = getattr(node, component)
        if _carries_a_non_inert_object(node):
            offending.append(".".join(path))
    return offending


# --- the evidence gate's field set ------------------------------------------
#
# THE SEVEN NUMBERED EVIDENCE FIELDS ARE SIX HERE, AND THE MISSING ONE IS NOT AN
# OVERSIGHT. ``classification`` (field 6) is a closed ``Literal`` --
# ``error``/``warning``/``judgment_call`` -- so an empty value is REFUSED BY THE
# SCHEMA before this gate is ever reached. Measured rather than reasoned:
# constructing a ``Finding`` with ``classification=""`` raises ``literal_error``.
# A non-emptiness check on it could therefore never fire, and a check that cannot
# fail is the shape this build has shipped three times and each time it read as
# coverage. The Done bar's number is still satisfied: all seven are COVERED, six
# by this gate and the seventh by the schema, which is a stronger guarantee than
# a check of ours because it refuses at construction.
#
# THE OTHER FOUR FREE STRINGS -- ``finding_id``, ``rule_id``, ``rule_purpose``,
# ``severity`` -- ARE CONSIDERED AND DELIBERATELY EXCLUDED. All four can hold ""
# (measured), so the exclusion is a decision rather than an impossibility, and an
# unlisted omission is indistinguishable from an unconsidered one (ADR-29 dec. 4):
#
#   * THEY ARE IDENTITY, NOT EVIDENCE, and this gate's whole claim is about
#     evidence. A finding with an empty ``rule_id`` but full ``inspected``,
#     ``observed_values``, ``reason_flagged`` and ``limitations_and_assumptions``
#     still shows what was looked at, what was found, why it was flagged, and what
#     the judgment assumes. It is not evidence-incomplete; it is
#     identity-incomplete, which is a different defect.
#   * TRACEABILITY IS ALREADY COVERED FROM INSIDE THE SEVEN. ``calculation_ref``
#     (field 3) is the reference into the code that produced the finding and IS
#     checked here, so "which code stands behind this" cannot be blank even when
#     ``rule_id`` is.
#   * IDENTITY BELONGS TO THE MERGE'S OWN PART, not this one. Part 3 owns
#     ``finding_id`` collision across the two streams, and an empty ``finding_id``
#     is the degenerate collision -- every one of them collides with every other.
#     Checking emptiness here and collision there would split one field's rules
#     across two parts, which is the drift this package refuses everywhere else.
#   * ``severity`` IS A REMOVAL CANDIDATE. ``gating/common.py`` records it as a
#     required field no producer ever varies and names it for removal at the next
#     contract amendment on ADR-30 dec. 3's argument. Adding a gate over a field
#     already proposed for deletion would create a second thing to unpick.
#
# SO THIS GATE DOES NOT WIDEN PAST THE SEVEN. Stated plainly because the opposite
# choice was available and arguable, and because a reader who expects ``rule_id``
# here should find the reason rather than a gap.
def _text_is_present(value: str) -> bool:
    """A free-text field carries something: it is not blank after stripping."""
    return bool(value.strip())


def _some_entry_is_present(value: Iterable[str]) -> bool:
    """A container names something: some entry is not blank after stripping.

    ITERATING A MAPPING YIELDS ITS KEYS, which is not an incidental convenience
    -- it is the mechanism by which this gate never touches a VALUE. For
    ``observed_values`` the entries walked here are the key strings and nothing
    else, so the keys-not-values bound is a property of the iteration rather than
    a rule someone has to remember to apply. See ``_empty_evidence_fields`` for
    why touching a value would be unsafe rather than merely undesirable.
    """
    return any(entry.strip() for entry in value)


# EACH FIELD PAIRED WITH ITS RULE, IN ``Finding``'s OWN DECLARATION ORDER. The
# pairing is the structure, and it replaces a name -> shape lookup that had the
# exact rot hole such a lookup is built to close: a field added to the field list
# but forgotten in the shape sets FELL THROUGH to the string rule, and
# ``list.strip()`` then raised ``AttributeError`` out of the evidence stage --
# which sits outside both ``try`` blocks, from a function whose docstring promises
# it never raises. MEASURED, not feared: the AttributeError propagated all the way
# out of ``validate_finding``. (That stage was numbered 3 when this was written
# and is numbered 4 since Part 6 inserted the inert-value walk ahead of it; the
# position outside both guards is what mattered then and still does, which is why
# the walk is built to be unable to raise rather than guarded.)
#
# A ROW CANNOT OMIT ITS RULE. That is the whole point of pairing rather than
# maintaining two structures held together by a test: the bad state is now
# UNCONSTRUCTIBLE instead of merely detectable, which is how this package handles
# dangerous states everywhere else. There is no fall-through branch left to take,
# and no default anybody has to have chosen.
#
# TWO RULES, NOT THREE, and the collapse is deliberate. ``inspected`` and
# ``observed_values`` are judged by the identical expression because iterating a
# list yields its elements and iterating a mapping yields its keys -- the same
# question asked of the same kind of thing. Splitting them into two identically
# bodied functions would be two homes for one fact.
#
# ONE UNIVERSAL RULE WOULD ALSO HAVE WORKED, AND IS DECLINED. Measured:
# ``any(entry.strip() for entry in value)`` is correct for a ``str`` too, because
# iterating a string yields its characters and a string is blank exactly when
# every character is. That would collapse the table to a single expression with no
# pairing at all -- and it would make the ``str`` case read as a character walk,
# which is cleverness a reader has to stop and decode. The charter asks for
# meaningful over clever; two named rules cost one line and read as what they are.
EVIDENCE_RULES: tuple[tuple[str, Callable[[Any], bool]], ...] = (
    ("inspected", _some_entry_is_present),  # field 1
    ("observed_values", _some_entry_is_present),  # field 2
    ("calculation_ref", _text_is_present),  # field 3
    ("reason_flagged", _text_is_present),  # field 4
    ("rule_version", _text_is_present),  # field 5
    # field 6 is ``classification`` -- closed Literal, refused by the schema
    ("limitations_and_assumptions", _text_is_present),  # field 7
)

# DERIVED, NEVER WRITTEN TWICE. A second hand-maintained tuple of names would be
# the drift the pairing above exists to prevent, one structure further out.
EVIDENCE_FIELDS: tuple[str, ...] = tuple(name for name, _ in EVIDENCE_RULES)

_UNVALIDATABLE_DETAIL = (
    "the object is a Finding instance and reduced to plain data, but RE-VALIDATING "
    "that data raised something other than a validation error, so its validity "
    "could not be established. WHERE THAT FAILURE ORIGINATED IS NOT KNOWABLE HERE "
    "and is deliberately not attributed: a Finding subclass may return any object "
    "at all from model_dump, so the fault may lie in the reduced payload or in "
    "this package's own validators. The underlying error is deliberately not "
    "echoed here: its text may not be wrapper-authored."
)


def validate_finding(
    candidate: object, *, arrived_on: FindingSource, position: int
) -> Finding | RejectedFinding:
    """Force one candidate through validation, or refuse it.

    Args:
        candidate: the object the stream yielded. Typed ``object`` RATHER THAN
            ``Finding`` on purpose -- see the module docstring. Annotating it
            ``Finding`` would state a guarantee this function exists precisely
            because nobody can make.
        arrived_on: which stream yielded it. Used to LABEL a refusal, and passed
            to the caller's own source check. Nothing in this function branches
            on it -- see below.
        position: index within that stream, for the refusal record.

    Returns:
        An EXACT ``Finding`` (``type(x) is Finding``) on success, or a
        ``RejectedFinding`` naming why. Never raises for any input shape.

    PRECEDENCE IS A DECISION, NOT AN ARTEFACT OF STATEMENT ORDER, and it is
    written here because until it was, it was the latter. A finding can carry more
    than one defect at once, and exactly one refusal is emitted, so the order
    below DECIDES WHICH DEFECT IS REPORTED. The order is:

        not a Finding  ->  schema invalid  ->  non-inert value
                       ->  evidence incomplete
                       ->  source mismatch  (the caller's, in ``merge``)

    THE FIRST THREE ARE SEQUENTIAL PRECONDITIONS rather than a ranking: an object
    that is not a ``Finding`` cannot be schema-checked, and one whose schema
    cannot be established cannot have its values walked or its evidence read.
    There is no choice to make between them; each is simply unreachable until the
    one before it passes.

    NON-INERT BEFORE EVIDENCE IS THE PART 6 DECISION, and it is a genuine ranking
    rather than a precondition -- both are intrinsic defects on a schema-valid
    object, either check could run first, and Part 2's intrinsic-before-relational
    rule (below) cannot separate them because both are intrinsic. WHAT SEPARATES
    THEM IS WHAT THE RECORD PRESERVES. A ``RejectedFinding`` deliberately never
    carries the offending object, so its single ``reason`` is the ONLY thing that
    will ever be known about why this finding did not travel. Report
    ``evidence_incomplete`` on a finding that ALSO carried a bound method, and the
    fact that an engine emitted executable state into a wrapper artifact is lost
    permanently -- nothing else in the system records it. The converse loses only
    "a field was blank", which the producer's next submission re-reports
    immediately. The asymmetry is in what survives the refusal, not in which
    defect is graver.

    AND IT IS EXPLICITLY NOT CLAIMED AS A PRECONDITION FOR THE EVIDENCE GATE,
    because that would misrepresent Part 2's argument and make this ordering look
    forced when it was chosen. The evidence gate is already safe on its own terms
    on any input reaching it: it reads KEYS and never values, and stage 2 has
    already forced those keys to ``str``. It would be equally safe running before
    this stage. Nothing here rescues it.

    THE OTHER REAL DECISION IS EVIDENCE BEFORE SOURCE, because those two are
    genuinely
    simultaneous -- a finding can be both blank and mislabelled, and either check
    could run first. INTRINSIC BEFORE RELATIONAL, and the argument is made here
    rather than inherited from the stage ordering above, which rests on type
    safety and would not settle this:

      * AN EVIDENCE DEFECT IS A PROPERTY OF THE OBJECT; a source mismatch is a
        property of the object's RELATIONSHIP to the stream that carried it. The
        same blank finding is blank on either stream, while the same mislabelled
        finding is perfectly fine on the other one. Reporting the invariant defect
        first means the reason describes the finding rather than the transaction.
      * IT IS THE MORE ACTIONABLE OF THE TWO for whoever must fix the producer.
        "Your rule emitted no evidence" is fixed at the rule; "it arrived on the
        wrong stream" is fixed at a call site that may not even be the engine's.
      * IT KEEPS THE REASON STABLE ACROSS STREAMS, which is the same uniformity
        the Done bar asks of the gate itself. The evidence check is total -- it
        runs on every finding and needs nothing but the finding -- while the
        source check needs the stream. Ordering total-before-conditional means a
        blank finding reports ``evidence_incomplete`` no matter which stream it
        arrived on, instead of reporting one reason on one stream and another on
        the other.

    ONE REFUSAL REPORTS THE FIRST FAILURE, NEVER THE COMPLETE LIST. A
    ``RejectedFinding`` carries a single ``reason``, so a consumer must not read
    it as "this is everything wrong with the object" -- a finding refused as
    ``evidence_incomplete`` may ALSO be mislabelled, and that second defect is
    never surfaced. Stated because the field name invites the stronger reading.

    NO ACCEPT-OR-REFUSE DECISION HERE READS A SOURCE VALUE -- AND THAT NOW COVERS
    ALL THREE STAGES, the evidence gate included. Neither ``arrived_on`` nor any
    candidate's ``source`` attribute is compared, tested, switched on, or used to
    select a code path: ``arrived_on`` is carried into the refusal record as data
    and nothing else, and ``_empty_evidence_fields`` is not even given it. The
    evidence field set is one module-level tuple with no per-source variant, so
    "the gate is stricter for engine findings" is not a thing that could be
    written here without adding a parameter that does not exist. That is what
    makes the gate UNCONDITIONAL in the sense ADR-23 dec. 1 requires -- there is
    no source for which the requirement is relaxed, because the code deciding
    accept-or-refuse never branches on one. The one place a source value IS read
    is the caller's
    verification step, which ADDS an identical requirement for every stream
    rather than relaxing one for any; the two run in opposite directions and only
    the second is what ADR-23 forbids.

    STATED AS A PROPERTY OF BRANCHING, NOT AS A PROPERTY OF THE TEXT, AND THE
    DIFFERENCE IS A TRAP WORTH NAMING FOR WHOEVER WRITES THE AST CHECK. An
    earlier wording of this paragraph claimed "the string ``source`` does not
    appear in this function's body", which is FALSE and was already false when
    written: ``FindingSource`` contains that substring and is in the signature
    two lines up. A grep-shaped check of the old claim would have tripped on the
    type name and then been loosened until it asserted nothing -- the failure
    mode ``docs/support-matrix.md`` already carries, where a version string
    appears twelve times including inside the sentence warning against depending
    on it. The checkable property is the one stated above: no ``ast.Compare``,
    ``ast.If``, ``ast.Match`` or dict lookup in this function takes a source
    value as an operand. Check that, not the spelling.

    ``isinstance`` BELOW, NOT ``type(x) is Finding``, AND THE ASYMMETRY WITH THE
    RETURN IS DELIBERATE. The INPUT gate must ADMIT a subclass, so it can be
    normalized; refusing one outright would discard a judgment whose sixteen
    required fields are all present and correct, over a packaging detail. The
    OUTPUT is exact by construction because it is a fresh ``model_validate``
    result. So the loose check is on the way in, the exact guarantee is on the
    way out, and the round trip is what converts one into the other.
    """
    claimed = _claimed_finding_id(candidate)

    if not isinstance(candidate, Finding):
        return RejectedFinding(
            arrived_on=arrived_on,
            position=position,
            reason="not_a_finding",
            detail=_NOT_A_FINDING_DETAIL,
            claimed_finding_id=claimed,
        )

    # STAGE 1 -- REDUCE. Guarded alone, so a failure here cannot be reported with
    # the other stage's sentence. ``model_dump`` is an ordinary method and a
    # subclass can override it; such an object still passed the ``isinstance``
    # check above, so this is engine-supplied code running on our stack.
    #
    # ``warnings=False`` MAKES THIS INDEPENDENT OF THE AMBIENT WARNING FILTER,
    # which is a correctness requirement and not tidiness. Dumping a ghost whose
    # fields hold the wrong types emits pydantic serializer warnings; under
    # ``-W error`` those warnings BECOME an exception, so the same input would
    # refuse for a different reason -- or crash -- depending on global state set
    # by something else entirely. Suppressing them here is honest because this
    # dump is not consumed as data: it exists only as the input to stage 2, which
    # reports every one of those same problems properly. Measured both ways:
    # identical dict, identical sixteen validation errors, under the default
    # filter and under ``-W error``.
    try:
        payload = candidate.model_dump(warnings=False)
    except Exception:
        # DELIBERATELY BROAD, AND NARROWLY SCOPED TO ONE CALL. That call is either
        # pydantic's or a subclass's override of it, so no code of ours sits
        # inside this guard for its bug to be masked. The alternative is that one
        # hostile or merely broken object takes down the whole merge, which is
        # the exact failure the gate exists to prevent. ``BaseException`` is not
        # caught: a KeyboardInterrupt is not a malformed finding.
        return RejectedFinding(
            arrived_on=arrived_on,
            position=position,
            reason="schema_invalid",
            detail=_UNDUMPABLE_DETAIL,
            claimed_finding_id=claimed,
        )

    # STAGE 2 -- RE-VALIDATE. ``ValidationError`` is the ordinary outcome and gets
    # the detailed account; anything else is REACHABLE rather than theoretical and
    # gets a sentence that attributes nothing. Measured: a subclass whose
    # ``model_dump`` returns a ``Mapping`` raising from ``__getitem__`` reduces
    # cleanly and then makes this line raise ``RuntimeError``.
    try:
        validated = Finding.model_validate(payload)
    except ValidationError as error:
        return RejectedFinding(
            arrived_on=arrived_on,
            position=position,
            reason="schema_invalid",
            detail=_schema_detail(error),
            claimed_finding_id=claimed,
        )
    except Exception:
        return RejectedFinding(
            arrived_on=arrived_on,
            position=position,
            reason="schema_invalid",
            detail=_UNVALIDATABLE_DETAIL,
            claimed_finding_id=claimed,
        )

    # STAGE 3 -- INERT VALUES. The two ``Any``-typed fields are walked for any
    # object the allow-list does not admit. Like stage 4 it runs on ``validated``
    # and never on ``candidate``, for the same reason.
    #
    # OUTSIDE BOTH GUARDS ABOVE, DELIBERATELY, AND THE WALK IS BUILT TO EARN THAT
    # POSITION. Wrapping this call in a ``try`` would let a bug of ours be
    # reported as an engine-supplied object's fault, and would hide exactly the
    # class of defect Part 2 measured when a dispatch fall-through sent an
    # ``AttributeError`` out of a function documented never to raise. Instead
    # ``_carries_a_non_inert_object`` executes nothing belonging to the objects it
    # inspects and terminates on every input, including a cycle -- see its
    # docstring for what makes each of those true.
    non_inert = _non_inert_fields(validated)
    if non_inert:
        return RejectedFinding(
            arrived_on=arrived_on,
            position=position,
            reason="non_inert_value",
            detail=_non_inert_detail(non_inert),
            claimed_finding_id=validated.finding_id,
        )

    # STAGE 4 -- EVIDENCE COMPLETENESS. Runs on ``validated``, never on
    # ``candidate``, and the order is what makes it safe to write at all: after
    # stage 2 the declared types are GUARANTEED, so ``inspected`` is a
    # ``list[str]`` and ``observed_values`` is keyed by ``str``, and this gate can
    # call ``str.strip`` without first proving what it holds. Run before stage 2
    # it would be reading attributes off an object of unknown provenance to make a
    # decision, which is what ADR-9 forbids untrusted data from doing.
    empty = _empty_evidence_fields(validated)
    if empty:
        return RejectedFinding(
            arrived_on=arrived_on,
            position=position,
            reason="evidence_incomplete",
            detail=_evidence_detail(empty),
            claimed_finding_id=validated.finding_id,
        )

    return validated


def _empty_evidence_fields(finding: Finding) -> list[str]:
    """The evidence fields carrying nothing, in ``Finding``'s declaration order.

    A LIST RATHER THAN A BOOL, so the refusal can name what was missing instead of
    only that something was. Order is ``EVIDENCE_RULES``' -- the schema's own --
    so two findings with the same defect produce byte-identical details.

    WHITESPACE IS EMPTY. ``"   "``, ``"\\t"`` and ``"\\n"`` are refused exactly as
    ``""`` is, and that is a decision rather than an accident of using ``strip``.
    A field whose whole purpose is to state something states nothing when it holds
    only spacing, and the two are indistinguishable to every reader downstream --
    a renderer, a diff, or a person. Accepting whitespace would leave the gate
    passing a finding that is empty in every sense a caller cares about while
    reporting it as complete.

    THE BOUND, STATED RATHER THAN IMPLIED, because a caller must not assume more
    than this check makes true:

      * ``observed_values`` IS JUDGED BY ITS KEYS AND NEVER BY ITS VALUES. So
        ``{"determinable": None}`` is COMPLETE here: the finding named an
        observation, and what it observed was nothing. A caller may assume some
        observation is NAMED; it may not assume any value is meaningful, present,
        or non-null.
      * ``inspected`` is judged element by element, so ``[""]`` is INCOMPLETE --
        a list whose only entry names nothing has not stated what was looked at.
      * Nothing recurses. A nested structure inside ``observed_values`` is not
        descended into, so an empty dict as a VALUE is complete.

    WHY VALUES ARE NEVER INSPECTED, AND IT IS NOT A CONVENIENCE. ``observed_values``
    is ``dict[str, Any]`` and pydantic does not validate ``Any``, so a value can be
    any object at all. Deciding whether one is "empty" means calling ``bool()`` or
    ``len()`` on it -- which runs that object's ``__bool__`` or ``__len__``.
    Measured: a value defining either raises from inside the check. That would put
    ENGINE-SUPPLIED CODE in control of a wrapper gate decision, which is precisely
    the "untrusted data must never influence control flow" rule of ADR-9 §6.6.
    Keys are safe by contrast for a checkable reason: stage 2 already forced them
    to ``str``, so ``str.strip`` is a builtin on a known type and executes nothing
    of anyone else's.

    THAT THE CONTRACT FORBIDS READING INSIDE IS A SECOND, INDEPENDENT REASON.
    ``FreshnessEvidence`` states that consumers "must never branch on a key name",
    and there is no value vocabulary either; judging a value's emptiness would be
    inventing one.

    ``getattr`` RATHER THAN A TYPED ACCESSOR, and that is what keeps this function
    free of suppression comments. ``getattr`` returns ``Any``, so each paired rule
    receives a value no annotation has narrowed and no checker would object to --
    which is exactly the remedy ``snapshot/assembler.py`` names for its own
    comparable site rather than muting a tool this repo does not run.
    """
    return [
        name
        for name, carries_something in EVIDENCE_RULES
        if not carries_something(getattr(finding, name))
    ]


def _evidence_detail(empty: list[str]) -> str:
    """The refusal text, naming which evidence fields were blank.

    NAMING THEM IS WRAPPER-SAFE, and by the same rule ``_schema_detail`` already
    applies: every name here comes from ``EVIDENCE_FIELDS``, which is this
    module's own tuple of ``Finding``-declared field names. Nothing engine-authored
    reaches this string -- not a value, not a key, not an undeclared field name.
    The count and the names are the whole content.
    """
    return (
        f"{len(empty)} evidence field(s) carry nothing: {', '.join(empty)}. The "
        "finding satisfies the schema in every other respect, so this is not a "
        "malformed object -- it is a judgment presented without the evidence its "
        "own schema requires it to show. A field holding only whitespace is "
        "counted as carrying nothing."
    )


def _claimed_finding_id(candidate: object) -> str | None:
    """The candidate's own ``finding_id``, if one is readable as a string.

    TOTAL OVER EVERY INPUT SHAPE, which bare attribute access is not. Probe 4 of
    this step measured ten shapes: ``candidate.finding_id`` raised
    ``AttributeError`` on six of them (a ghost with a different field set, a
    ghost with nothing set, a dict, a foreign object, a bare string, ``None``),
    and returned a non-string on two more (an ``int``, and ``None`` itself).

    THREE GUARDS, EACH FOR A MEASURED SHAPE RATHER THAN AN IMAGINED ONE:

      * the dict branch, because ``getattr`` returns the default for a mapping
        even when the key is present -- a dict carries data in items, not
        attributes;
      * ``type(value) is str``, not ``isinstance``, because an ``int`` and a
        ``None`` both reached this point in the probe, and because a ``str``
        SUBCLASS carrying extra state is an object with behaviour -- the same
        exact-type reasoning W-8's inert-leaf walk records;
      * the ``try``, because ``getattr(x, name, default)`` returns the default
        ONLY for ``AttributeError``. An attribute whose access raises anything
        else propagates, and an object of unknown provenance can trivially define
        one. Measured: a property raising ``RuntimeError`` propagates straight
        through ``getattr``'s default.

    Returns:
        The string, or ``None`` when it is not readable as one. UNTRUSTED when
        present -- it is engine-authored text that has passed no gate.

    STILL VERBATIM AFTER PART 4, WHICH IS THE DECISION AND NOT A GAP. This value
    is carried exactly as it was read: control characters, instruction-shaped
    text and all. Two reasons, and the first is the load-bearing one.

    A REFUSAL RECORD IS DATA, AND ITS IDENTITY MUST MATCH WHAT THE PRODUCER SENT.
    A caller correlating a refusal against the finding it handed in has
    ``arrived_on`` and ``position`` for certain, and this field as the only
    content-derived handle; editing the value would break exactly the
    correspondence it exists to provide. ``merge._id_anomalies`` records the same
    argument at greater length for ``finding_id``, including what sanitizing it
    would change and why those changes -- though defensible -- lose more than they
    gain.

    NEUTRALIZATION HAPPENS AT RENDER, NOT HERE, and ``render._refusal_entry`` is
    the line that does it: the value is quoted as data, labelled CLAIMED rather
    than verified, and never placed in an instruction position. That is §6.6's own
    clause (c) remedy, and it is what ``adapter/sanitize`` means by neutralizing
    through framing rather than rewriting. Clause (b) -- the strip and the cap --
    belongs to the adapter by §6.6's own words, and this package cannot reach the
    tools for it in any case (Layer 6 imports ``contract`` only).
    """
    try:
        if isinstance(candidate, dict):
            value = candidate.get(_CLAIMED_ID_ATTR)
        else:
            value = getattr(candidate, _CLAIMED_ID_ATTR, None)
    except Exception:
        # See the docstring: a raising accessor is a shape an unknown object can
        # have, and "unreadable" is the honest answer for it.
        return None
    return value if type(value) is str else None


def _schema_detail(error: ValidationError) -> str:
    """A wrapper-authored account of a validation failure, echoing no content.

    WHAT MAY APPEAR HERE AND WHAT MAY NOT, derived rather than asserted. Pydantic
    reports each problem with a ``type``, a ``loc`` and an ``input``:

      * ``type`` is pydantic's own closed vocabulary (``missing``,
        ``extra_forbidden``, ``string_type``, ``model_type``, ...) -- safe;
      * ``input`` IS THE OFFENDING VALUE, echoed verbatim. Never read here.
      * ``loc`` is safe ONLY when it names a field ``Finding`` declares. For an
        ``extra_forbidden`` error it names the UNDECLARED key instead, and that
        name was chosen by whoever built the object -- an engine may name a field
        anything at all. So locations are filtered against
        ``Finding.model_fields`` and the rest are COUNTED, not named.

    The count still tells a reader that undeclared keys were present, which is
    the diagnostically load-bearing half; WHICH names they used is exactly the
    half that cannot be echoed. That trade is ``preflight/redaction.py``'s
    ``_dropped_argument_count`` made again, for the same reason.
    """
    problems = error.errors(include_url=False)
    declared = set(Finding.model_fields)
    named = sorted(
        {
            str(problem["loc"][0])
            for problem in problems
            if problem["loc"] and str(problem["loc"][0]) in declared
        }
    )
    undeclared = sum(
        1
        for problem in problems
        if not problem["loc"] or str(problem["loc"][0]) not in declared
    )
    kinds = sorted({str(problem["type"]) for problem in problems})

    parts = [f"{len(problems)} schema error(s) of kind(s) {', '.join(kinds)}"]
    if named:
        parts.append(f"on declared field(s) {', '.join(named)}")
    if undeclared:
        parts.append(
            f"and {undeclared} on key(s) Finding does not declare, whose names "
            "are engine-authored and are deliberately not echoed"
        )
    return "; ".join(parts) + "."
