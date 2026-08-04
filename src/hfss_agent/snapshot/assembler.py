"""W-8 assembly: the ``DesignSnapshot`` builder (System Design §1.1, ADR-28).

Layer 5 (§5): imports ``contract`` ONLY — the layer number reflects ASSEMBLY
order, not imports (corrected ADR-28). W-8 EVALUATES NOTHING and CALLS NOTHING.
It receives the upstream outputs as data and composes them; the composition
itself — reading a session, dispatching through a broker, deciding what to read
first — belongs to the server layer, which is the only place that can hold both
a broker and this module.

TAKES NO BROKER, AND THE REASON DIFFERS FROM W-7'S. W-7 also takes none, but for
a correctness reason about gate provenance (see its module docstring); it is
*permitted* a broker by §5 and declines one. W-8 is not permitted one at all.
That is the whole content of the contract-only grant: a module whose output
crosses the wrapper->engine seam holds no capability that could have reached
HFSS, the filesystem, the network, or the OS, so what the engine sees can only
be what a caller handed in.

WHAT "CONTRACT ONLY" ADMITS, decided at Step 2.5b and recorded here because the
narrow reading is the tempting one. It is the PREFIX reading: the whole
``hfss_agent.contract`` package, ``tool_io`` included. The constraint is about
CAPABILITIES, not about which data shapes W-8 may name — ``tool_io`` types are
inert pydantic models and grant nothing. The narrow reading (§2 schemas only)
would make ADR-28 decision 8 unimplementable, because the refusal arms W-8 must
raise on are ``tool_io`` types; being unable to express the decision is the tell
that it is not what §5 meant. ``tests/boundary/test_snapshot_import_audit.py``
carries this as a named test so a future reader cannot narrow it silently.

THE THREE REASONS ASSEMBLY REFUSES, all raising ``SnapshotAssemblyError``:

  1. A REFUSAL ARM WAS RECEIVED (ADR-28 decision 8). ``SelectionRefused`` gets no
     representation on any field: a refusal means a selection stage was missing,
     and ``Selection`` requires all seven — so a snapshot with a refused
     selection is not a lesser snapshot, it is no snapshot. The same holds for a
     ``CannotEvaluate`` on the inspection or native-validation input.
  2. THE ``SelectionChain`` WAS INCOMPLETE. The chain carries every stage as
     optional (it is built stage by stage and reset downstream on any change),
     while ``DesignSnapshot.Selection`` requires all seven. A chain missing a
     stage cannot be narrowed without inventing one, so it is refused rather
     than defaulted.
  3. THE INSPECTION WAS A SUBSET READ. ``InspectionResult`` carries whatever
     subset the caller requested; ``DesignSnapshot.Inspection`` requires all
     eight sections and deliberately has NO absence arm (ADR-28) — its PARTIAL
     failures are already carried section by section as ``read_status`` and
     ``limitation``, which is finer-grained honesty than an arm could give. A
     three-section read therefore yields no snapshot.

WHAT ``created_at`` MEANS. Stated here in the words a stranger should be able to
read in six months, because the natural misreading — "this is when we looked at
the design" — is the one that matters:

    ``created_at`` is the UTC instant this snapshot was ASSEMBLED — not when
    anything in it was read. Every read it describes happened earlier and
    carries its own timestamp; this field says only when the pieces were
    composed into one artifact.

Stamped with an inline ``datetime.now(timezone.utc)`` at construction, with no
injected clock, following W-5 and W-6 exactly (``inspect/assembler.py`` and
``validate_native/assembler.py`` each call it inline at the instant they are
describing). The instant differs from theirs in what it means, not in how it is
taken: those two stamp a read they just performed, and W-8 performs no read at
all, so there is no read for this field to be the instant OF. Taking the
earliest input instant would make it a silently-drifting duplicate of
``read_at``; taking the latest would claim the snapshot existed before it did.

``snapshot_id`` IS ``"snap-" + uuid4().hex``, and it identifies a CAPTURE EVENT
rather than a design state. All three carriers of the field want that reading:
``AuditRecord`` correlates one dispatch, ``ProvenanceRecord`` says which capture
a metric came from, and ``DesignSnapshot`` is the capture. A content hash would
identify a design STATE instead, which is a different question — ADR-6's
"diffing two snapshots answers what changed" is answered by diffing payloads,
not by comparing ids — and it would collide across two captures of an unchanged
design, leaving the audit log unable to say which call produced which.

THE VARIATION HASH IS RECEIVED AS DATA AND NEVER COMPUTED HERE. §2 assigned the
canonical hash to this module; under the contract-only grant that assignment is
unimplementable (W-8 cannot import the adapter, and the adapter must mint a
``Variation`` at select time, long before any snapshot exists), so ownership
moves to the adapter and §2 is corrected. Recomputing and comparing was rejected
on measurement, not taste: ``_resolve_variation`` carries an unparseable
variation token through AS the hash, so a comparison would fire on legitimate
data — a design whose variation string is "nominal" has ``values={}`` and
``variation_hash="nominal"``, which no recomputation can reproduce.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from hfss_agent.contract import (
    CONTRACT_VERSION,
    DesignSnapshot,
    Environment,
    Inspection,
    IntentObject,
    NativeValidation,
    NativeValidationUnavailable,
    Selection,
    SolveDataUnavailable,
    SolvedData,
    SolveState,
)
from hfss_agent.contract.tool_io import (
    CannotEvaluate,
    InspectDesignResult,
    InspectionResult,
    NativeValidationBlock,
    SelectionChain,
    SelectionRefused,
)

# ``snapshot_id``'s prefix. Named once so the form is stated in one place rather
# than living inside an f-string; see the module docstring for why the id
# identifies a capture event rather than a design state.
_SNAPSHOT_ID_PREFIX = "snap-"

# The seven stages ``Selection`` requires, DERIVED from the contract and never
# retyped, following W-5's ``_CANONICAL_ORDER`` precedent. ``SelectionChain``
# declares the same seven names with every one optional, which is what makes a
# single ``getattr`` loop able to check both shapes at once; a test asserts the
# two field-name sets are equal, so a contract change surfaces there rather than
# as an AttributeError at assembly time.
_REQUIRED_STAGES: tuple[str, ...] = tuple(Selection.model_fields)

# The eight sections ``Inspection`` requires, DERIVED from the type being
# constructed rather than from ``InspectionSectionName``. Both are contract, and
# either would work; this one is the more direct statement, because it is
# literally the set of keys the constructor needs.
_REQUIRED_SECTIONS: tuple[str, ...] = tuple(Inspection.model_fields)

# The two union-typed inputs, named for the refusal message so it can say WHICH
# input refused without interpolating anything read from HFSS. See
# ``_refusal_error`` for why the message names the field and never its content.
_INSPECTION_INPUT = "inspection"
_NATIVE_VALIDATION_INPUT = "native_validation"


class SnapshotAssemblyError(Exception):
    """Assembly could not complete honestly, so no snapshot is emitted.

    RAISED, NOT RETURNED, and forced by the contract rather than chosen.
    ``DesignSnapshot`` has three absence arms — ``native_validation``,
    ``solve_state`` and ``solved_data`` — and none of them can say "the inputs
    arrived, but they do not compose into an artifact anyone should trust".
    ``inspection`` and ``selection`` have no arm at all, deliberately: every
    whole-read failure the first has is a session fault or a session/adapter
    state divergence, under either of which the snapshot itself is not
    trustworthy; and ADR-28 decision 8 fixes that a refused selection means "no
    snapshot", not "a snapshot with an absence arm".

    Every raise site therefore DISCARDS the inputs it was holding. A snapshot
    with a defaulted selection stage, a synthesized eighth section, or an
    absence arm standing in for a refusal is not a lesser artifact to fall back
    on; it is a record asserting something nobody verified, and it is the one
    thing that must never cross the wrapper->engine seam.

    See this module's docstring for the three reasons that reach here: a refusal
    arm was received, the ``SelectionChain`` was incomplete, or the
    ``Inspection`` was a subset read.

    A DELIBERATE FOURTH DUPLICATE of ``InspectionAssemblyError``,
    ``NativeValidationAssemblyError`` and ``MetricsAssemblyError``, and ADR-28
    decision 15 records the reasoning pre-emptively rather than waiting for
    someone to propose the cleanup:

        "W-8's assembly error will be a fourth duplicate, and that is correct.
         Three assembler exception types already exist with docstrings arguing
         that unification is impossible because no legal shared home exists
         under the import map. `SnapshotAssemblyError` will be the fourth. Four
         is the count at which someone proposes a base class; the base class
         would have to live in `contract`, which W-12 restricts to validation,
         or in a shared module no layer may import. Recorded pre-emptively so
         the proposal arrives already answered."

    The four reasons W-6's copy sets out at length all still hold, and this
    type's import position makes two of them STRICTER rather than merely equal.
    W-5, W-6 and W-7 may each at least import ``broker``; W-8 may not, so the
    set of packages all four may legally import is exactly ``contract`` — and an
    assembler-domain exception is not a contract schema (W-12 restricts that
    subpackage to validation, and it is closed at its current version). The
    messages must differ materially, because these say no SNAPSHOT is emitted
    and must never call the composition a "read" or a "run". And catching one
    must not catch another: the server-layer tool that composes W-5, W-6 and
    W-8 in a single operation needs to know which assembly failed, and a shared
    base class would let one bare ``except`` swallow the wrong one.

    A future maintainer tempted to unify the four must first find a package all
    four may legally import. Today there is none, and the count is now four
    rather than three because W-8 removed the only candidate that was left.
    """


def assemble_snapshot(
    *,
    inspection: InspectDesignResult,
    native_validation: (
        NativeValidationBlock
        | NativeValidationUnavailable
        | CannotEvaluate
        | SelectionRefused
    ),
    solve_state: SolveState | SolveDataUnavailable,
    solved_data: SolvedData | SolveDataUnavailable,
    selection: SelectionChain,
    environment: Environment,
    intent: IntentObject | None = None,
) -> DesignSnapshot:
    """Compose one ``DesignSnapshot`` from inputs a caller already holds.

    KEYWORD-ONLY, AND THE DEVIATION FROM THE THREE SIBLINGS IS THE POINT (ADR-29).
    ``inspect_design``, ``validate_native`` and ``compute_metrics`` are all
    positional, and none of them faced this: no sibling has two adjacent
    parameters that can hold the SAME type. ``solve_state`` and ``solved_data``
    share the ``SolveDataUnavailable`` arm, and in the never-solved case BOTH hold
    it with different reasons — so transposing them produces a snapshot that
    validates, round-trips through JSON, and asserts the wrong reason for each
    absence. Measured, not feared: with a real ``SolvedData`` in the
    ``solve_state`` slot pydantic refuses (``model_type`` at
    ``('solve_state', 'SolveState')``), so the ONLY input shape that
    mis-assembles silently is the both-absent one — which ADR-28 calls the
    ordinary case for a design that was never solved.

    The siblings' shape is evidence that nobody needed a ``*``, not that one is
    wrong here. Seven parameters is also past the point where a positional call
    reads clearly.

    THE PARAMETER TYPES ARE A HYBRID, AND THE SPLIT IS FORCED RATHER THAN CHOSEN.
    ``inspection`` and ``native_validation`` arrive as the UNIONS their producers
    return, refusal arms included, because ADR-28 decision 8 puts the "no
    snapshot" decision here and those arms are ``contract.tool_io`` types this
    module may legally name. ``solve_state`` and ``solved_data`` cannot arrive
    that way: their refusal type is ``AdapterCannotEvaluate``, which lives in
    ``hfss_agent.adapter`` and is unreachable from a contract-only module — so
    they arrive already mapped onto the contract's own absence arm. That mapping
    (an adapter refusal reason onto ``SolveDataUnavailableReason``) belongs to
    the caller and is deliberately not built here.

    ``native_validation`` ACCEPTS ``NativeValidationUnavailable`` FOR THE SAME
    REASON, which is a small widening of "the two unions" worth stating: ADR-28
    gave that field an absence arm, and if the only inputs were W-6's three
    return arms the arm would have no path into a snapshot at all. Accepting the
    already-mapped value is exactly what ``solve_state`` does; it is not the
    mapping itself, which stays the caller's.

    Args:
        inspection: W-5's result. An ``InspectionResult`` must carry all eight
            sections — see ``_inspection``.
        native_validation: W-6's result, or the contract absence arm.
        solve_state: the solve-state block, or why there is none.
        solved_data: the S-parameter series, or why there is none.
        selection: the session's chain, narrowed here to the snapshot's
            seven-stage ``Selection`` — see ``_selection`` for what is dropped.
        environment: the attached session's four version strings.
        intent: the optional design intent; ``None`` is an honest value, not a
            missing one, and is the field's own default.

    Returns:
        A ``DesignSnapshot``. There is no failure arm — see
        ``SnapshotAssemblyError``.

    Raises:
        SnapshotAssemblyError: a refusal arm was supplied, the selection chain
            was incomplete, or the inspection did not carry all eight sections.
    """
    narrowed_selection = _selection(selection)
    narrowed_inspection = _inspection(inspection)
    narrowed_native = _native_validation(native_validation)
    # STAMPED HERE, after every narrowing has passed and immediately before
    # construction, which is the instant this field actually describes (see the
    # module docstring). Stamping earlier would put a time on an artifact that
    # may still be refused; stamping it inline in the call below would leave the
    # order of argument evaluation deciding what "assembled" means.
    created_at = datetime.now(timezone.utc)
    return DesignSnapshot(
        # IMPORTED, NEVER RESTATED. Every site in this package takes the
        # constant so an accidental edit to its value is one loud diff rather
        # than a literal that silently disagrees with the schema it labels.
        contract_version=CONTRACT_VERSION,
        created_at=created_at,
        snapshot_id=_SNAPSHOT_ID_PREFIX + uuid4().hex,
        environment=environment,
        selection=narrowed_selection,
        inspection=narrowed_inspection,
        native_validation=narrowed_native,
        # PASSED THROUGH UNTOUCHED, both arms. A ``SolveDataUnavailable`` is
        # already the honest artifact for "there is none"; re-wrapping it would
        # add wrapper text over a reason the adapter already worded correctly.
        solve_state=solve_state,
        solved_data=solved_data,
        intent=intent,
    )


def _selection(chain: SelectionChain) -> Selection:
    """Narrow the session's partial chain onto the snapshot's complete one.

    WHAT THIS DROPS: the project's absolute filesystem PATH, and that is the
    whole reason this function is a named site rather than a dict copy.

    ADR-28 decided the path stays on ``SelectionChain`` and never reaches the
    block that crosses into the engine, because a default AEDT project lives
    under ``%USERPROFILE%\\Documents\\Ansoft`` — so the path routinely carries
    the operator's Windows account name into the one artifact that leaves this
    machine. Nothing downstream of the snapshot has any use for it. The session
    keeps its copy (it compares the path to detect a project that moved between
    a read and a re-verification) and so does the audit log; what is dropped is
    only the copy that would have travelled.

    THE TYPE SYSTEM CATCHES THE CLUMSY VERSION OF THIS MISTAKE AND NOT THE REAL
    ONE, which is why the drop is asserted by a test rather than trusted to
    pydantic. ``Selection.project`` is an ``UntrustedStr``, so passing the whole
    ``Project`` raises a ``string_type`` ``ValidationError`` — but passing
    ``chain.project.path`` is a perfectly valid ``str`` and validates silently.
    The plausible regression is the one pydantic cannot see.

    A stage that is ``None`` raises: the chain is built stage by stage and reset
    downstream on any change, so an absent stage means the snapshot would have to
    invent one, and ADR-28 decision 8 fixes that a snapshot missing a selection
    stage is no snapshot rather than a lesser one.
    """
    missing = [stage for stage in _REQUIRED_STAGES if getattr(chain, stage) is None]
    if missing:
        # Names the STAGES, never their values — see ``_refusal_error``. The
        # stage names are this package's own field names, not anything read from
        # HFSS.
        raise SnapshotAssemblyError(
            "the selection chain does not name a "
            f"{', '.join(missing)}, so the snapshot's selection block cannot be "
            "completed without inventing one. No snapshot is assembled: a "
            "selection stage that was never chosen has no truthful value to "
            "substitute, and a snapshot missing one is not a lesser snapshot."
        )
    # THE INVARIANT, STATED IN WORDS RATHER THAN AS A SUPPRESSION COMMENT.
    # ``missing`` being empty is what guarantees the two shaped stages below are
    # not None; re-checking them here would add a branch no input can reach.
    #
    # The check is a loop over a DERIVED tuple, which no static type checker can
    # follow — the three sibling assemblers avoid that by narrowing each Optional
    # with an explicit ``if x is None: raise`` a checker can see, and they carry
    # no suppressions at their comparable sites. This module does not follow them
    # there, because the derived tuple is what a test can hold to the contract's
    # own field set, and hand-written narrowing cannot be.
    #
    # NO ``# type: ignore`` IS WRITTEN HERE, deliberately (ADR-29). This repo runs
    # no type checker: CI is ``ruff check .`` and ``pytest``, there is no mypy or
    # pyright in pyproject or the lockfile, and there are no pre-commit or git
    # hooks. A suppression comment would therefore assert an interaction with a
    # tool that never runs — and at the one line executing ADR-28's decision that
    # is worse than noise, because a reader could take it to mean a checker
    # validated everything around it and this was the known exception. If a
    # checker is ever adopted, these two lines are where it will complain first;
    # the fix at that point is to build the kwargs through ``getattr`` (whose
    # ``Any`` return satisfies any checker) rather than to mute it here.
    project = chain.project
    variation = chain.variation
    return Selection(
        process_id=chain.process_id,
        # THE PATH DROP. ``chain.project`` is a ``Project`` carrying name AND
        # path; only the name continues. This single expression is the whole
        # execution of ADR-28's decision — see this function's docstring.
        project=project.name,
        design=chain.design,
        solution_type=chain.solution_type,
        setup=chain.setup,
        sweep=chain.sweep,
        # PROPAGATED BYTE-FOR-BYTE, hash included. W-8 computes no hash: the
        # canonical variation hash is the adapter's, and an unparseable variation
        # token is carried through AS the hash by ``_resolve_variation``, so a
        # value here is not always a digest and must not be treated as one.
        variation=variation,
    )


def _inspection(result: InspectDesignResult) -> Inspection:
    """Narrow W-5's per-section dict onto the snapshot's complete eight.

    WHAT THIS DROPS: nothing, on the success path — and that is the point. A
    subset is REFUSED rather than padded, because ``Inspection`` deliberately has
    no absence arm (ADR-28): its partial failures are already carried section by
    section as ``read_status`` and ``limitation``, which is finer-grained honesty
    than an arm could give, and synthesizing a ninth state for "not requested"
    would make an incomplete capture look like a complete one.

    W-5's ``InspectionResult`` also carries ``provenance`` and ``template_text``,
    and both are dropped: the snapshot has no field for either, the provenance
    describes W-5's read rather than this composition, and ``template_text`` is a
    rendering for a tool response rather than data for the engine.
    """
    if isinstance(result, (CannotEvaluate, SelectionRefused)):
        raise _refusal_error(_INSPECTION_INPUT, result)
    if not isinstance(result, InspectionResult):
        raise SnapshotAssemblyError(
            f"the {_INSPECTION_INPUT} input was a {type(result).__name__}, which "
            "is not a type this parameter is declared to accept. No snapshot is "
            "assembled: this is a wiring problem, and composing around a value "
            "of unknown meaning would hide it inside a valid-looking artifact."
        )
    absent = [name for name in _REQUIRED_SECTIONS if name not in result.sections]
    if absent:
        raise SnapshotAssemblyError(
            f"the inspection carries {len(result.sections)} of "
            f"{len(_REQUIRED_SECTIONS)} sections and is missing "
            f"{', '.join(absent)}. No snapshot is assembled: the snapshot's "
            "inspection block requires all eight and has no absence arm, so a "
            "subset would have to be padded with a section nobody looked at."
        )
    return Inspection(**{name: result.sections[name] for name in _REQUIRED_SECTIONS})


def _native_validation(
    block: (
        NativeValidationBlock
        | NativeValidationUnavailable
        | CannotEvaluate
        | SelectionRefused
    ),
) -> NativeValidation | NativeValidationUnavailable:
    """Take W-6's messages out of their block, or pass the absence arm through.

    WHAT THIS DROPS: ``NativeValidationBlock.provenance``, deliberately and with
    nothing lost. That stamp records the project, design, instant and AEDT
    version of ONE validation run, which is W-6's honest receipt for its own tool
    response — and the snapshot has no field to put it in. It carries no
    ``snapshot_id`` and could not: W-6 emits no snapshot, and W-8 is what mints
    that id, so the two records describe different events. The messages
    themselves cross unchanged, which is the part the engine is owed.

    ``NativeValidation`` is reused UNMODIFIED across the seam — the same type the
    adapter returned, the same object W-6 held — so there is no re-shaping step
    here that could misrepresent anything.
    """
    if isinstance(block, (CannotEvaluate, SelectionRefused)):
        raise _refusal_error(_NATIVE_VALIDATION_INPUT, block)
    if isinstance(block, NativeValidationUnavailable):
        # The already-mapped absence arm, passed through untouched for the reason
        # ``solve_state`` is: it is already the honest artifact.
        return block
    if not isinstance(block, NativeValidationBlock):
        raise SnapshotAssemblyError(
            f"the {_NATIVE_VALIDATION_INPUT} input was a "
            f"{type(block).__name__}, which is not a type this parameter is "
            "declared to accept. No snapshot is assembled: this is a wiring "
            "problem, and composing around a value of unknown meaning would hide "
            "it inside a valid-looking artifact."
        )
    return block.validation


def _refusal_error(
    field: str, refusal: CannotEvaluate | SelectionRefused
) -> SnapshotAssemblyError:
    """The error for a refusal arm supplied where a payload was required.

    NAMES THE FIELD AND THE ARM'S TYPE, NEVER THE ARM'S CONTENT, and the omission
    is deliberate. ``CannotEvaluate`` and ``SelectionRefused`` each carry
    ``reason``, ``limitation`` and ``template_text``, and those strings can
    interpolate values read from HFSS — a setup name, a sweep's unit token. An
    exception message is a line-oriented renderer like any other, so this follows
    the precedent W-5 sets at its own provenance-failure site: when an untrusted
    name is in hand, it names the FIELD that is missing and not the value it
    would have held. (W-7 is the one sibling that does interpolate an
    adapter-sourced value — the S-parameter key list, under ``!r`` — because
    there the unexpected key IS the diagnostic. Here it is not: the caller still
    holds the refusal object with every field intact.)

    ``outcome`` IS INTERPOLATED, and it is not an exception to the rule above: it
    is a closed ``Literal`` on both types, so its value is one of four
    wrapper-authored tags and cannot carry text from anywhere else. It is what
    makes the four refusal cases distinguishable from the message alone.
    """
    return SnapshotAssemblyError(
        f"a refusal arm was supplied as the {field} input: a "
        f"{type(refusal).__name__} tagged {refusal.outcome!r}. No snapshot is "
        "assembled. A refusal means the upstream step declined before it "
        "produced anything, so there is no payload to compose and no absence arm "
        "on this field to carry one — the refusal itself is the result, and the "
        "caller still holds it with every field intact."
    )
