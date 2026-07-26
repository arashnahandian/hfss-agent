"""Provenance schemas.

``ProvenanceRecord`` — attached to every metric and finding (§2, spec Point 4).
``InspectionProvenance`` — the structural-read counterpart, for tool results
that were produced without a solve behind them.
``NativeValidationProvenance`` — the counterpart for one native HFSS
validation run, which has neither a solve nor a calculation of ours behind it.

The three are INDEPENDENT types sharing no base class; see
``NativeValidationProvenance``'s docstring for why that separation is
load-bearing rather than incidental.
"""

from datetime import datetime

from pydantic import AwareDatetime

from hfss_agent.contract.common import StrictModel, UntrustedStr, Variation


class ProvenanceRecord(StrictModel):
    """Full provenance for a computed value or finding (§2 ProvenanceRecord).

    Carries the ``variation`` key so every metric and finding is
    self-describing for the exact variation it was produced under — no need to
    reach back into the snapshot to know which point in the design space a
    value belongs to.

    ``engine_version`` and ``rule_version`` are optional: gate provenance and
    metric provenance have no engine or supplemental rule behind them, so those
    slots are legitimately empty there.

    Native validation is NOT among the cases this type covers (ADR-23). It has
    its own ``NativeValidationProvenance``, which shares no base class with this
    one and is not a variant of it: a validation run has no solve, so almost
    every field below would have to be invented for it.
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
    engine_version: str | None = None
    rule_version: str | None = None


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

    NO SHARED BASE CLASS; THREE INDEPENDENT TYPES. This shares no base class
    with ``ProvenanceRecord`` or ``InspectionProvenance``, and no mixin was
    introduced between any of them. Their kinship is only the identical
    ``project``/``design`` field names and types, and nothing may come to
    depend on the three staying aligned. A future field on one is not a field
    on the others.

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
