"""Provenance schemas.

``ProvenanceRecord`` — attached to every metric (§2, spec Point 4). It covered
findings too until ADR-30; see ``FindingProvenance`` for why it could not.
``InspectionProvenance`` — the structural-read counterpart, for tool results
that were produced without a solve behind them.
``NativeValidationProvenance`` — the counterpart for one native HFSS
validation run, which has neither a solve nor a calculation of ours behind it.
``FindingProvenance`` — the counterpart for a JUDGMENT, from either of the two
sources that make one: a W-9 gate or an E-2 engine rule.

The four are INDEPENDENT types sharing no base class; see
``NativeValidationProvenance``'s docstring for why that separation is
load-bearing rather than incidental, and ``FindingProvenance``'s for the one
optional field among the four and the rule that permits it.
"""

from datetime import datetime

from pydantic import AwareDatetime

from hfss_agent.contract.common import StrictModel, UntrustedStr, Variation


class ProvenanceRecord(StrictModel):
    """Full provenance for a COMPUTED VALUE (§2 ProvenanceRecord).

    Carries the ``variation`` key so every metric is self-describing for the
    exact variation it was produced under — no need to reach back into the
    snapshot to know which point in the design space a value belongs to.

    ``engine_version`` AND ``rule_version`` WERE REMOVED AT STEP 2.6a. The
    tombstone stays because records stamped ``snapshot-3.0.0`` or earlier still
    carry both slots, and a reader meeting one needs to know they were dropped
    rather than never existing.

    SUCH A RECORD IS REFUSED, NOT SILENTLY STRIPPED — the consequence worth
    stating, because "the fields are gone" and "the old record no longer
    validates" are different facts. This type is ``extra="forbid"`` like every
    contract schema, so validating a ``snapshot-3.0.0`` payload against this shape
    raises a ``ValidationError`` naming both keys, one ``extra_forbidden`` error
    each. Measured against this schema, not inferred from the config.

    THAT IS INTENDED, and it is what makes the version rule enforceable at all.
    ``contract_version`` is a plain ``str`` that no code in this package compares,
    so if the two keys were merely ignored, a 3.0.0 record would validate clean
    under 4.0.0 while still CLAIMING to be 3.0.0 — exactly the "stamped record
    claiming a schema version whose shape it no longer has" that the second clause
    of ``common.py``'s version arithmetic exists to prevent. The refusal is the
    only mechanism that catches the mismatch. Nothing in this package
    deserializes a ``ProvenanceRecord`` (the adapter's sanitizer re-validates
    against the same current type, so it cannot present a stale shape), so the
    refusal has no inbound path here at all: it bites an external consumer
    replaying an old record, which is precisely who should hear about it loudly.

    ADR-30 created the state that forced it rather than finding it: the
    engine-rule finding was this type's third carrier and the only case that ever
    filled them, and that case moved to ``FindingProvenance``. What remained was
    ``MetricRecord`` and ``SolveHealthReport`` — derived and pinned rather than
    recalled (``test_provenance_record_has_exactly_two_carriers``) — and neither
    can have an engine or a supplemental rule behind it, because the seam is
    ``evaluate(DesignSnapshot) -> list[Finding]`` and nothing crossing it is a
    metric or a solve-health readout.

    That left two optionals NO producer could fill, which the rule written at
    ``FindingProvenance.engine_version`` calls dishonest in as many words: an
    optional is honest when one producer fills it and another genuinely cannot,
    and dishonest when none can, because the slot then advertises a capability
    that does not exist. An empty value read as "a producer looked and found
    nothing" when the truth was "no producer exists".

    TAKEN INSIDE A SCHEMA MAJOR THAT WAS MOVING ANYWAY. Deleting a field from a
    ``contract_version``-carrying type is breaking for an exhaustive consumer, so
    it was held back from the ADR-30 retype rather than smuggled in as a side
    effect of it. ``snapshot-4.0.0`` is the first major since, and doing it here
    costs no version event at all; declining would have forced a second major
    later for two fields nobody filled.

    A SUPPLEMENTAL RULE BEHIND A COMPUTED VALUE IS NOW INEXPRESSIBLE HERE — the
    honest consequence, not an oversight. Tier 1 metrics come from this package's
    open formulas and cite them in ``MetricRecord.formula_ref``; no supplemental
    rule stands behind one. If a rule ever does back a computed value, that is a
    new capability and earns its own contract event, which is the right cost for a
    change that size. The two spellings meant DIFFERENT things and still do:
    ``Finding.rule_version`` is the version of the rule that PRODUCED a finding,
    is required, and is untouched by this.

    NEITHER NATIVE VALIDATION NOR A FINDING IS AMONG THE CASES THIS TYPE COVERS,
    and each has its own type for its own reason. ``NativeValidationProvenance``
    (ADR-23): a validation run has no solve, so almost every field below would
    have to be invented for it. ``FindingProvenance`` (ADR-30): a judgment
    performs no calculation, so ``expression`` and ``reference_impedance`` have
    no truthful value — and neither has any source in ``DesignSnapshot``, which
    is all a gate or an engine rule ever sees. Both share no base class with this
    one, and neither is a variant of it.
    """

    project: UntrustedStr
    design: UntrustedStr
    solution_type: str
    setup: str
    sweep: str
    variation: Variation
    expression: str
    reference_impedance: float
    solve_timestamp: datetime
    freshness_status: str
    snapshot_id: str
    contract_version: str
    wrapper_version: str


class InspectionProvenance(StrictModel):
    """Honest provenance for a structural design read (ADR-20, Option B, gap 11).

    A structural read performs no solve, so there is no setup, sweep, variation,
    expression, reference impedance, solve timestamp, freshness status, or
    engine/rule version to report — and no computed value or judgment for them
    to stand behind. Filling a ProvenanceRecord for such a read would mean
    inventing those fields or leaving them empty-but-declared; either way the
    record would assert more than the read actually knows. This type carries no
    solve, metric, or judgment field by construction, so it cannot make a claim
    it has not earned.

    It deliberately shares no base class with ProvenanceRecord (Option B chose a
    separate type over widening ProvenanceRecord, and no mixin was introduced
    between them). The two are independent: their kinship is only the identical
    ``project``/``design`` field names and types, and nothing may come to depend
    on them staying aligned. A future field on one is not a field on the other.
    """

    project: UntrustedStr
    design: UntrustedStr
    # The UTC instant W-5 performed the atomic inspection read. AwareDatetime,
    # not datetime: a naive value is rejected rather than silently read as local
    # time, so "when was this read" is never ambiguous by an offset.
    read_at: AwareDatetime
    contract_version: str
    wrapper_version: str
    # The AEDT version of the attached process, read at attach time. "Read
    # under" is the honest framing: a process's AEDT version cannot change
    # without a new process, and every re-attach re-reads it — so this states
    # the version the read happened under, not the version the design was
    # authored in (which is not readable on a read-only path). Plain str, not
    # UntrustedStr: it is solver-reported via the attached Desktop, not sourced
    # from the HFSS design, matching Environment.aedt_version's precedent. The
    # value is supplied by the W-5 assembler, like contract_version.
    read_under_aedt_version: str


class NativeValidationProvenance(StrictModel):
    """Honest provenance for ONE native HFSS validation run (ADR-23, W-6).

    A validation run performs no solve, and no calculation of ours: HFSS's own
    ValidateDesign inspected the design and emitted messages. There is no
    setup, sweep, variation, expression, reference impedance, solve timestamp,
    freshness status, snapshot id, or engine/rule version behind it, and no
    computed value or judgment for any of them to stand behind. This type
    carries no such field by construction, so it cannot make a claim it has not
    earned.

    ONE RECORD PER RUN, NOT PER MESSAGE. One ValidateDesign invocation produces
    one message list under exactly one project/design/instant/version tuple.
    Copying this record onto every message would imply that per-message
    provenance exists — that we know something message by message — when
    nothing individuates a message: we cannot even say which of the validator's
    internal checks emitted it. It would be per-message in shape only, never in
    content.

    NO SHARED BASE CLASS; FOUR INDEPENDENT TYPES. This shares no base class
    with ``ProvenanceRecord``, ``InspectionProvenance`` or
    ``FindingProvenance``, and no mixin was introduced between any of them.
    Their kinship is only the identical ``project``/``design`` field names and
    types, and nothing may come to depend on the four staying aligned. A future
    field on one is not a field on the others.

    ``validated_under_aedt_version`` IS NOT A RULE VERSION and must never be
    presented as one. We own no rule here, and HFSS exposes no version for the
    checks its validator runs. What this field states is the version of the
    PRODUCT whose validator ran. That matters more here than the equivalent
    field does for a structural read: ValidateDesign's BEHAVIOUR is
    version-dependent in a way reading a design's structure is not — a
    different AEDT version may emit different messages for the same design — so
    the version is part of what makes the messages interpretable at all. It
    remains a product version, and the distinction is the whole point.

    DELIBERATELY ABSENT, each for its own reason: ``setup``/``sweep``/
    ``variation`` (ValidateDesign is design-level; the adapter does not require
    them selected to run it); ``solve_timestamp``/``freshness_status`` (no
    solve); ``expression``/``reference_impedance`` (no calculation);
    ``snapshot_id`` (W-6 emits no snapshot — W-8 does);
    ``engine_version``/``rule_version`` (no engine, no rule — and NOT as
    optionals either: a declared-but-empty slot still asserts the slot exists,
    which is the same unearned claim this type is shaped to avoid); and any
    message, error, or warning count (deriving one would mean reading inside
    the validator's messages, which is where passing output through stops and
    judging it begins).
    """

    project: UntrustedStr
    design: UntrustedStr
    # The UTC instant the native validation call RETURNED — the closest
    # observable moment to the completed run. Named ``validated_at``, never
    # ``read_at``: invoking the solver's own validator is not a structural read,
    # and sharing that name would invite exactly the kinship the docstring
    # above refuses. AwareDatetime, not datetime: a naive value is rejected
    # rather than silently read as local time, so "when" is never ambiguous by
    # an offset.
    validated_at: AwareDatetime
    contract_version: str
    wrapper_version: str
    # The AEDT version of the attached process, read at attach time. Plain str,
    # not UntrustedStr: solver-reported via the attached Desktop, not sourced
    # from the HFSS design, matching Environment.aedt_version's precedent. See
    # the docstring for why this is NOT a rule version. The value is supplied
    # by the W-6 assembler, like contract_version.
    validated_under_aedt_version: str


class FindingProvenance(StrictModel):
    """Honest provenance for one JUDGMENT — a gate result or an engine rule
    (ADR-30, W-9 and E-2).

    A judgment reads a snapshot and decides something about it. It runs no solve
    of its own and evaluates no expression, so ``ProvenanceRecord`` — built for a
    COMPUTED VALUE — cannot be filled honestly for one. This type carries no such
    field by construction, so it cannot make a claim it has not earned.

    EVERY FIELD BELOW IS SOURCEABLE FROM A ``DesignSnapshot`` UNDER BOTH ARMS OF
    ``solve_state``, and that is the test this type is shaped to pass. A design
    that was never solved is an ordinary case, not an edge one (ADR-28), and a
    gate must be able to report on it — so a provenance that exists only when a
    solve does would block the judgment most worth making.

    THE FIRST PROVENANCE TYPE WITH TWO PRODUCERS, and the axis it divides on is
    JUDGES RATHER THAN COMPUTES — not "is a gate." W-9's gates and E-2's engine
    rules read the same snapshot across the same ``evaluate()`` seam and both
    emit ``Finding``s, and neither can source an ``expression`` or a Z0. A type
    named ``GateProvenance`` would have had to be renamed or duplicated the day
    E-2 landed.

    NO SHARED BASE CLASS; FOUR INDEPENDENT TYPES. This shares no base class with
    ``ProvenanceRecord``, ``InspectionProvenance`` or
    ``NativeValidationProvenance``, and no mixin was introduced between any of
    them. Their kinship is only the identical ``project``/``design`` field names
    and types, and nothing may come to depend on the four staying aligned. A
    future field on one is not a field on the others.

    DELIBERATELY ABSENT, each for its own reason — an unlisted omission is
    indistinguishable from an unconsidered one (ADR-29 dec. 4):

      * ``expression`` — a judgment evaluates none. The snapshot does carry
        S-parameter keys that the adapter calls "expressions", but it carries
        one per port pair and this would be a single slot, so there is no basis
        for choosing among them. WHICH snapshot elements a finding rested on
        belongs in ``Finding.inspected``, which is typed for exactly that, and
        the code behind a computed one belongs in ``Finding.calculation_ref``.
      * ``reference_impedance`` — no calculation, so no Z0 was used. Nothing in
        this package reads a reference impedance from HFSS at all today, so a
        value here could only be invented by whoever built the record.
      * ``solve_timestamp`` — absent whenever ``solve_state`` takes its
        ``SolveDataUnavailable`` arm, which is the ordinary never-solved case
        above. A freshness finding that wants to state the solve instant puts it
        in ``Finding.observed_values``: per-finding evidence, rather than a claim
        about the identity of the record carrying it.
      * ``freshness_status`` — a gate OUTPUT, not an input. Stamping it into the
        provenance of the very gate that decides it is circular, and on the other
        three gates it is an unearned claim. It is also absent on the arm above.
      * ``rule_version`` — ``Finding.rule_version`` is required and already
        carries it, and two homes for one fact is the drift the charter above
        exists to prevent. The two spellings meant DIFFERENT things, which is why
        dropping this resolved a collision rather than losing a field:
        ``ProvenanceRecord.rule_version`` was the SUPPLEMENTAL rule behind a
        computed value, while ``Finding.rule_version`` is the version of the rule
        that PRODUCED the finding, and a gate owns the second and never the
        first. ``ProvenanceRecord``'s spelling was itself REMOVED later in Step
        2.6a — see that class's tombstone — once this type took its only
        producer, so the collision no longer exists in either direction.
      * ``evaluated_under_aedt_version`` — NOT ADDED, unlike both sibling types,
        which carry one. Their acts are version-situated: ``ValidateDesign``'s
        BEHAVIOUR differs across AEDT versions, and a structural read happens
        against one live process. A judgment is arithmetic over a snapshot and is
        version-independent — and the snapshot it names in ``snapshot_id``
        already carries ``environment.aedt_version``, so a field here would
        duplicate a field of the artifact being judged.
      * ``evaluated_at`` — NOT ADDED, unlike both sibling types, which stamp an
        instant. Those modules performed an act against a live process at a
        moment. A judgment is a PURE FUNCTION of the snapshot: the same snapshot
        yields the same findings forever, so an evaluation instant carries
        nothing ``DesignSnapshot.created_at`` does not already situate. The cost
        would be real rather than notional — ``gating`` may import only
        ``contract``, so minting one means calling a clock from the module whose
        determinism is what makes it testable, and it would put a clock inside
        E-2 as well.
    """

    project: UntrustedStr
    design: UntrustedStr
    solution_type: str
    setup: str
    sweep: str
    variation: Variation
    # WHICH CAPTURE THIS JUDGMENT RESTED ON — the exact and complete statement of
    # what was judged, and the reason this type needs no solve field to be
    # traceable. A Finding travels to W-10 and into a tool response without the
    # snapshot beside it, so this is what lets a reader return to the artifact
    # the judgment was made against.
    snapshot_id: str
    contract_version: str
    wrapper_version: str
    # OPTIONAL — THE ONLY OPTIONAL ACROSS THE FOUR PROVENANCE TYPES, so the rule
    # that permits it is written here rather than left to be inferred.
    # ``NativeValidationProvenance`` refuses an ``engine_version`` slot in as
    # many words ("NOT as optionals either: a declared-but-empty slot still
    # asserts the slot exists"), and a reader who meets that line one class up
    # will otherwise read this field as contradicting it.
    #
    # THE DISTINGUISHING RULE: an optional is honest when one producer of the
    # type genuinely fills it and another genuinely cannot. It is dishonest when
    # NO producer can fill it, because the slot then advertises a capability that
    # does not exist. That is the case the three sibling types face, and it is
    # why they drop their equivalents — not because optionals are forbidden.
    #
    # This is the first provenance type with TWO producers, which is what puts it
    # on the honest side of that rule. A gate has no engine behind it and never
    # will, by construction. An engine rule knows its own version, and this is
    # the only place it can record it — ``Finding.rule_version`` carries the
    # RULE's version, which is a different fact about a different thing.
    #
    # STATED PRECISELY, BECAUSE A READER CAN CHECK IT: neither producer exists
    # yet (W-9 is Step 2.6b, E-2 is Step 2.10), so today the field is filled by
    # nobody. What makes it committed rather than speculative is the seam —
    # ``evaluate(DesignSnapshot) -> list[Finding]`` is pinned across both repos,
    # and ``FindingSource`` carries ``engine_rule`` for exactly that traffic. If
    # that seam is ever withdrawn, this field loses its justification and should
    # be removed with it.
    engine_version: str | None = None
