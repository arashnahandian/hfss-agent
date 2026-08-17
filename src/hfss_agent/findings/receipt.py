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

WHAT IT DOES NOT CATCH, so the claim stays the size of the mechanism: a
``Finding`` whose ``observed_values`` carries a callable, a ``pathlib.Path`` or a
live handle validates CLEANLY through this pass and the object survives intact.
``Finding.observed_values`` is ``dict[str, Any]`` and pydantic does not validate
``Any``. That hole is real, it was measured, and it belongs to this step's
inert-leaf part -- not to this module, which would only be able to pretend.

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
# ``list.strip()`` then raised ``AttributeError`` out of stage 3 -- which sits
# outside both ``try`` blocks, from a function whose docstring promises it never
# raises. MEASURED, not feared: the AttributeError propagated all the way out of
# ``validate_finding``.
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

        not a Finding  ->  schema invalid  ->  evidence incomplete
                       ->  source mismatch  (the caller's, in ``merge``)

    THE FIRST THREE ARE SEQUENTIAL PRECONDITIONS rather than a ranking: an object
    that is not a ``Finding`` cannot be schema-checked, and one whose schema
    cannot be established cannot have its evidence read. There is no choice to
    make between them; each is simply unreachable until the one before it passes.

    THE REAL DECISION IS EVIDENCE BEFORE SOURCE, because those two are genuinely
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

    # STAGE 3 -- EVIDENCE COMPLETENESS. Runs on ``validated``, never on
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
        present -- it is engine-authored text that has passed no gate, and the
        envelope for it is Part 4's.
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
