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

    NO ACCEPT-OR-REFUSE DECISION HERE READS A SOURCE VALUE. Neither
    ``arrived_on`` nor any candidate's ``source`` attribute is compared, tested,
    switched on, or used to select a code path: ``arrived_on`` is carried into
    the refusal record as data and nothing else. That is what makes the gate
    UNCONDITIONAL in the sense ADR-23 dec. 1 requires -- there is no source for
    which the requirement is relaxed, because the code deciding accept-or-refuse
    never branches on one. The one place a source value IS read is the caller's
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

    return validated


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
