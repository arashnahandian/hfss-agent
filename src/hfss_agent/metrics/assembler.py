"""W-7 assembly: the ``ComputeMetricsResult`` builder (System Design §1.1, §3).

Turns one variation's solved data into ``MetricRecord``s, but only after being
shown that the W-9 gates passed. The six open formulas in ``sparams`` do the
arithmetic; this module decides what may be computed, how many records the six
formulas produce, and what happens to a value that has no place in a
``MetricRecord``.

TWO NAMES, ONE OF WHICH COLLIDES -- stated plainly, because W-5 and W-6 both set
the precedent of disclosing this rather than renaming around it:

  * ``compute_metrics`` BELOW is W-7's entry point: a plain module-level
    function, deliberately NOT a registered capability. It does not appear in
    ``session_routed_specs`` and must not be added there
    (``test_the_assembler_is_not_a_registered_capability`` pins that).
  * ``compute_metrics`` is ALSO the §3 TOOL name, and that tool does not exist
    yet -- Step 3.4 builds it on top of this module. Unlike W-5's case there is
    no third use of the spelling and no registered capability by this name at
    all, so the collision is only two-way.

TAKES NO BROKER, AND THAT IS A CORRECTNESS DECISION RATHER THAN A SCOPE ONE.
§5 permits ``metrics -> broker``, and W-5 and W-6 both take one, so the shape
below is the exception among the three Layer-4 siblings and needs its reason
stated:

W-7 may not import ``hfss_agent.gating`` (the Layer-4 import audit forbids it),
so gate outcomes MUST arrive as data. A W-7 that additionally held a broker
would fetch solved data by dispatch while receiving gates as data -- and those
are two separate reads of one solve, with nothing between them to guarantee the
sweep was not re-solved in the interval. ``MetricRecord``'s
``gate_status_at_computation`` asserts that the gates had passed *for the data
this value came from*. Taking both as data from a single caller that read the
solve once is the only arrangement in which that assertion is provable rather
than hopeful. So the broker dispatch belongs to the Step 3.4 tool, which reads
once and feeds both W-9 and W-7.

(Corroborating, though not proof: ``ProvenanceRecord.freshness_status`` is a
required field only W-9's freshness gate can honestly fill, so a caller cannot
construct the provenance this function requires without having run the gates.)

WHAT ASSEMBLY MEANS HERE -- four things, and judging is not among them:

  1. THE GATE CHECK -- an allow-list on the supplied ``Finding`` outcomes.
  2. THE RECORD MAPPING -- six formulas to seven records, because
     ``impedance_at_target`` returns a ``complex`` and ``MetricRecord.value`` is
     one float.
  3. THE OMISSION LEDGER -- a metric with no representable value is left out and
     the reason is stated, never fabricated and never silently dropped.
  4. ``template_text`` -- deterministic, complete without any LLM.

Interpreting any of it -- comparing a value to the design intent, calling a
result good or bad -- is Step 2.11's ``interpret``, not this module's.

THE THREE WAYS A METRIC CAN FAIL TO APPEAR, kept distinct on purpose because
they have different causes and only one of them is a defect:

  * NO VALUE EXISTS -- ``NoMinus10dBBand``, or no intent so no target frequency.
    Stated omission.
  * A VALUE EXISTS BUT CANNOT CROSS THE JSON BOUNDARY -- ``-inf`` from a perfect
    match, ``+inf`` from a total reflection. Stated omission; see
    ``_finite_records``.
  * A PRECONDITION WAS VIOLATED -- empty, misaligned, or non-finite series, or a
    target outside the swept range. NOT an omission: the ``ValueError`` from
    ``sparams`` propagates out of this function unchanged, because reaching one
    means the caller skipped the gates, and that is a programming error that
    should read as one rather than being reported as a missing metric.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from hfss_agent.contract import (
    ComplexSample,
    Finding,
    IntentObject,
    MetricRecord,
    ProvenanceRecord,
    SolvedData,
)
from hfss_agent.contract.tool_io import (
    # IMPORTED, NOT COPIED, and that closes ADR-30's fourth open gap. ``tool_io``
    # exports this "because W-7 must route on the SAME list the schema validates
    # against" -- and until now W-7 held its own spelling instead, with nothing
    # testing agreement. Two constants plus an agreement test would keep them
    # merely equal; one object makes them identical, so the router and the
    # ``MetricsComputedWithCaveats`` validator cannot disagree even in principle.
    # §5 permits ``metrics -> contract``, so this needs no new grant.
    GATE_OUTCOMES_THAT_QUALIFY_COMPUTATION,
    ComputeMetricsResult,
    MetricsComputed,
    MetricsComputedWithCaveats,
    MetricsRefused,
)
from hfss_agent.metrics.sparams import (
    IMPEDANCE_AT_TARGET_REF,
    MINUS_10DB_BANDWIDTH_REF,
    RESONANT_FREQUENCY_REF,
    S11_AT_TARGET_REF,
    S11_MIN_REF,
    VSWR_AT_TARGET_REF,
    Minus10dBBand,
    NoMinus10dBBand,
    impedance_at_target,
    minus_10db_bandwidth,
    resonant_frequency,
    s11_at_target,
    s11_min,
    vswr_at_target,
)

# The one S-parameter the approved Tier 1 metric set reads. Named once: the six
# formulas are S11-only because the APPROVED METRIC SET is (Locked Idea Spec
# Point 5 -- extraction is general N-port, which is why ``export`` is, and the
# interpreted set is the approved list, which is why this is not).
S11_KEY = "S(1,1)"

# The only gate outcome that permits the CLEAN arm. NOT a copy of
# ``GATE_OUTCOMES_THAT_QUALIFY_COMPUTATION`` and not in competition with it: that
# frozenset holds the outcomes that QUALIFY numbers, and ``pass`` is deliberately
# excluded from it (ADR-30 dec. 10 -- "a passing gate hedges nothing, and
# admitting one would let this arm be filled entirely with passes"). The two are
# complementary halves of one partition, and
# ``test_the_three_routes_partition_every_finding_outcome`` pins that they and the
# refusing remainder cover ``FindingOutcome`` exactly once each.
#
# STILL AN ALLOW-LIST, and the direction is still the whole point: a sixth
# ``FindingOutcome`` added later lands in the REFUSING remainder by default,
# because it is named by neither this constant nor the imported frozenset. The
# failure mode of the opposite arrangement is numbers where there should be none.
#
# THE THREE-WAY PARTITION LANDED HERE AT STEP 2.6b, which ADR-25 dec. 10
# pre-authorised at "a one-constant edit" and ADR-30 dec. 8 corrected. Both
# estimates were low; the true cost was the routing, the record stamp, and the
# rendered text, because the old behaviour was asserted in prose in a dozen places
# that a constant change leaves silently false.
#
# WHAT SUPERSEDED WHAT, kept because the reasoning is still instructive. Before
# 2.6a, ``warning`` and ``insufficient_evidence`` refused, and the reason was
# sound: ``MetricsComputed`` has three fields and none can carry a qualification,
# so permitting on a hedge would have produced numbers whose caveat existed only
# in prose. That FACT still holds. The INFERENCE no longer follows, because
# ``MetricsComputedWithCaveats`` now carries the caveat structurally in a required,
# ``min_length=1`` field. §1.1's "never a silent pass" is satisfied by that arm
# rather than bypassed: a caveated result is not a pass and does not read as one.
GATE_OUTCOME_THAT_PERMITS_COMPUTATION = "pass"

# Metric names, fixed here because they are what a downstream reader keys on.
S11_MIN = "s11_min"
RESONANT_FREQUENCY = "resonant_frequency"
S11_AT_TARGET = "s11_at_target"
MINUS_10DB_BANDWIDTH = "minus_10db_bandwidth"
VSWR_AT_TARGET = "vswr_at_target"
# ``impedance_at_target`` produces TWO records: ``MetricRecord.value`` is a
# single float and an impedance is complex, so the one formula's result is split
# into its resistive and reactive parts. Both records cite the SAME
# ``formula_ref``, so the split invents no second formula to point at.
# "resistance"/"reactance" rather than "real"/"imag": those are the engineering
# names for what the two parts are, and both are in ohms.
IMPEDANCE_AT_TARGET_RESISTANCE = "impedance_at_target_resistance"
IMPEDANCE_AT_TARGET_REACTANCE = "impedance_at_target_reactance"

# Units, spelled to match the conventions already in this package:
# ``export``'s ``reference_impedance_ohm`` column fixes "ohm" (singular, ASCII);
# ``IntentObject.target_frequency_hz`` and ``Minus10dBBand.low_frequency_hz``
# fix Hz. "ratio" rather than "" for VSWR: the field is a required string, and an
# empty one reads as a slot nobody filled rather than as "dimensionless".
DB = "dB"
HZ = "Hz"
RATIO = "ratio"
OHM = "ohm"

# Canonical record order -- the seven records the six approved formulas produce,
# whole-sweep metrics first, then the three that need a target frequency. ONE
# tuple governs both the record list and the omission list, so output order can
# never depend on the order failures happened to occur in. That is what makes
# ``template_text`` byte-deterministic; a test asserts this covers exactly the
# names above.
METRIC_ORDER: tuple[str, ...] = (
    S11_MIN,
    RESONANT_FREQUENCY,
    MINUS_10DB_BANDWIDTH,
    S11_AT_TARGET,
    VSWR_AT_TARGET,
    IMPEDANCE_AT_TARGET_RESISTANCE,
    IMPEDANCE_AT_TARGET_REACTANCE,
)

# The three metrics that need a target frequency, and the reason they are omitted
# without one. NOT computed against a defaulted target: spec Point 9's "never a
# silent nominal" is about the variation, and the same discipline applies to the
# frequency axis -- an assumed 2.4 GHz would put an unverified number inside a
# reported metric just as an assumed variation would.
AT_TARGET_METRICS: tuple[str, ...] = (
    S11_AT_TARGET,
    VSWR_AT_TARGET,
    IMPEDANCE_AT_TARGET_RESISTANCE,
    IMPEDANCE_AT_TARGET_REACTANCE,
)
NO_INTENT_REASON = (
    "no design intent was supplied, so there is no target frequency to evaluate "
    "at; a target is never assumed or defaulted"
)

# ``MetricRecord.gate_status_at_computation`` when every supplied gate passed.
# Spelling matches the contract-schema fixtures exactly, so producer and fixtures
# cannot drift.
ALL_GATES_PASSED = "all_gates_passed"

# THE SIBLING FOR THE CAVEATED ARM, and it exists because the alternative is a
# FALSE CLAIM IN A TYPED FIELD. ``gate_status_at_computation`` is what a record
# asserts about the gates behind its number; stamping ``all_gates_passed`` on a
# record whose freshness gate returned ``insufficient_evidence`` would be untrue in
# a machine-readable slot, which is worse than untrue in prose because nothing
# downstream can tell.
#
# THE SPELLING IS WIRE-VISIBLE AND IS CHOSEN, NOT DEFAULTED. Two candidates were
# rejected:
#
#   * ``all_gates_passed_with_caveats`` -- REJECTED, and it is the obvious one.
#     ``"all_gates_passed_with_caveats".startswith("all_gates_passed")`` is True,
#     so any consumer routing by prefix would read a caveated record as a clean
#     one. That is verbatim the collision ADR-30 dec. 11 REMOVED rather than
#     documented between ``metrics_computed`` and ``metrics_computed_with_caveats``,
#     and reintroducing it here would undo that decision one field over.
#   * ``gates_qualified`` -- REJECTED on ADR-30 dec. 11's other finding: in an RF
#     context "qualified" reads as CERTIFIED at least as loudly as HEDGED, because
#     qualification is what a part passes. That is why ``MetricsQualified`` was not
#     the arm's name, and the same word is no safer in a status string.
#
# ``some_gates_hedged`` shares no prefix with ``all_gates_passed`` in either
# direction, parallels its quantifier-subject-verb shape, and uses the word
# ``MetricsComputedWithCaveats``' own docstring uses for these gates.
# ``test_no_gate_status_literal_is_a_prefix_of_another`` pins the non-collision
# over both, so a third status cannot reintroduce it from either side.
SOME_GATES_HEDGED = "some_gates_hedged"

_NO_INTERPRETATION_NOTICE = (
    "Each value above is the output of the open formula named beside it, "
    "computed from the solved data as read. Nothing here is interpreted, "
    "compared against a design intent, or judged."
)

# WAS ``_ONLY_PASS_PERMITS_NOTICE`` UNTIL STEP 2.6b, and the rename is not
# cosmetic: the old text stated that "warning" and "insufficient_evidence" refuse,
# which became FALSE the moment the caveated arm acquired a producer. Renaming
# rather than editing in place is deliberate -- the old name asserted the old
# policy, so leaving it would have left a true sentence under a false label.
_REFUSAL_POLICY_NOTICE = (
    'Metrics are refused when any gate result supplied is "fail" or '
    '"not_evaluated". A "warning" or an "insufficient_evidence" does NOT refuse: '
    "those QUALIFY the numbers instead and are reported alongside them, under a "
    "notice. No numbers are reported here because at least one gate did neither."
)

# THE CAVEAT HEADING, rendered at the TOP of a caveated result rather than
# appended. Neda's ruling (ADR-30 dec. 7) chose "Show the numbers, with a clear
# notice on top", and the POSITION was part of what she chose -- a caveat below
# the numbers is read after the reader has already taken them in. See
# ``_template_text`` for what moved to make room for it.
_CAVEAT_HEADING = (
    "READ THIS BEFORE TRUSTING THE NUMBERS BELOW. They were computed, but not "
    "every validity gate could vouch for them:"
)


class MetricsAssemblyError(Exception):
    """Assembly could not complete honestly, so no metrics are reported.

    RAISED, NOT RETURNED, and forced by the contract rather than chosen. The
    FOUR arms of ``ComputeMetricsResult`` are a populated ``MetricsComputed``,
    a ``MetricsComputedWithCaveats`` carrying numbers beside the gate results
    that hedge them (added at Step 2.6a; no producer here yet, Step 2.6b), a
    ``MetricsRefused`` carrying gate results, and a ``CannotEvaluate``
    ("PyAEDT could not evaluate this"). None can say "the gates passed and the
    data arrived, but nothing computable was in it". Borrowing ``CannotEvaluate``
    would blame the solver for a wrapper-side or upstream-data problem -- the
    exact misattribution ADR-16 decision 5 narrowed that type to prevent.

    A DELIBERATE THIRD DUPLICATE of ``InspectionAssemblyError`` and
    ``NativeValidationAssemblyError``, for the four reasons W-6's copy sets out
    at length: the three Layer-4 siblings may not import one another (the audits
    forbid it in every direction), there is no legal shared home for an
    assembler-domain exception (``contract`` carries no behaviour beyond
    validation; ``broker`` must not know its consumers exist), the messages must
    differ materially, and catching one must not catch the others. A maintainer
    tempted to unify the three must first find a package all three may legally
    import; today there is none.
    """


@dataclass(frozen=True)
class _Omission:
    """One approved metric that has no record, and why.

    A stated absence rather than a missing key or a zero: ``NoMinus10dBBand``
    already established in ``sparams`` that "no band" needs its own reason
    attached, and the same holds for every other way a metric can fail to
    appear. There is nowhere in ``MetricRecord`` to put this -- see
    ``_template_text`` for the consequence.
    """

    metric_name: str
    reason: str


@dataclass(frozen=True)
class _Value:
    """A computed metric before the finiteness gate decides it can be a record."""

    metric_name: str
    value: float
    units: str
    formula_ref: str


@dataclass(frozen=True)
class _GateRouting:
    """The three-way decision the supplied gate results force (Step 2.6b).

    Exactly one of three states is live, and they are mutually exclusive by
    construction rather than by convention:

      * ``refusal`` set          -> at least one gate failed or did not run.
      * ``refusal`` None, ``qualifying`` non-empty -> the caveated arm.
      * ``refusal`` None, ``qualifying`` empty     -> the clean arm.

    A TUPLE, NOT A LIST, so the routing cannot be edited after the decision is
    made -- the frozen dataclass would otherwise hold a mutable payload and only
    look immutable.
    """

    refusal: MetricsRefused | None
    qualifying: tuple[Finding, ...]


def compute_metrics(
    gate_findings: Sequence[Finding],
    solved_data: SolvedData,
    provenance: ProvenanceRecord,
    intent: IntentObject | None = None,
) -> ComputeMetricsResult:
    """Compute the approved Tier 1 metric set for ONE variation, if the gates say so.

    Args:
        gate_findings: W-9's gate results for the solve ``solved_data`` came
            from. REQUIRED AND UNDEFAULTED -- see below.
        solved_data: the S-parameter series for the one variation being computed.
        provenance: the fully-built stamp every record carries. Passed in rather
            than assembled here because 14 of its fields (``snapshot_id``,
            ``solve_timestamp``, ``freshness_status``, ``expression``, ...) are
            not derivable from ``SolvedData``, and because ``export``'s content
            generators already fixed this convention for this module.
        intent: the optional design intent. Its ``target_frequency_hz`` is the
            ONLY thing read from it -- evaluating its threshold is
            interpretation, which belongs to Step 2.11.

    ``gate_findings`` IS REQUIRED, WITH NO DEFAULT, AND THAT IS THE FIRST OF TWO
    FAIL-CLOSED LAYERS. Omitting it is a ``TypeError`` from Python itself before
    any computation happens, which is the same structural trick used for
    ``CapabilitySpec.tier``, ``ExportRefused.outcome``, and
    ``impedance_at_target``'s Z0: make the dangerous omission un-expressible
    rather than handled. The second layer catches the empty list, which a default
    could not -- see ``_route_gates``.

    A SHARED ``ProvenanceRecord`` ACROSS ALL SEVEN RECORDS is honest only because
    the approved metric set is S11-only, so one ``expression`` describes every
    value. Far-field metrics are explicitly out of scope for this repo; were they
    ever added, this shortcut would be the first thing to break, and correctly.

    Returns:
        ``MetricsComputed`` with at least one record when every supplied gate
        passed; ``MetricsRefused`` with the non-passing gates otherwise. Never
        ``MetricsComputed`` with an empty list.

    Raises:
        MetricsAssemblyError: if the solved data holds no ``S(1,1)`` series, or
            (defensively) if no record survived assembly.
        ValueError: propagated unchanged from ``sparams`` when a precondition was
            violated -- an empty, misaligned or non-finite series, or a target
            outside the swept range. These mean the gates were skipped and are
            deliberately NOT converted into omissions.
    """
    routing = _route_gates(gate_findings, provenance)
    if routing.refusal is not None:
        return routing.refusal

    s11 = solved_data.s_parameters.get(S11_KEY)
    if s11 is None:
        # NOT a stated omission and not a CannotEvaluate. Every approved metric
        # reads this one series, so there is no partial result to report -- and
        # the canonical key spelling is an UNVERIFIED assumption about what
        # PyAEDT emits (``export``'s ``_S_PARAM_KEY`` comment sets out why that
        # matters). Refusing loudly turns the moment the assumption breaks into a
        # named failure at Phase 5.2 live validation; absorbing it would cost the
        # discovery.
        raise MetricsAssemblyError(
            f"the solved data carries no {S11_KEY!r} series (present: "
            f"{sorted(solved_data.s_parameters)!r}), and every approved Tier 1 "
            "metric is computed from it, so there is no metric to report. The "
            "canonical key spelling is an unverified assumption about what "
            "PyAEDT emits, so this is more likely an upstream bug worth "
            "reporting than a reason to guess which series was meant."
        )

    values, omissions, band = _computed_values(solved_data, s11, provenance, intent)
    # THE STAMP FOLLOWS THE ROUTE. ``all_gates_passed`` on a caveated record would
    # be a false claim in a typed field; see ``SOME_GATES_HEDGED``.
    gate_status = SOME_GATES_HEDGED if routing.qualifying else ALL_GATES_PASSED
    records, non_finite = _finite_records(values, provenance, gate_status)
    omissions = _ordered(omissions + non_finite)

    if not records:
        # DEFENSIVE, AND EXPECTED TO BE UNREACHABLE -- stated rather than left
        # undefined, because the alternative is falling through to a
        # ``MetricsComputed`` with an empty list, which would assert "the gates
        # passed and the metrics were computed" while carrying nothing, with all
        # three other arms of the union being lies.
        #
        # WHY IT IS UNREACHABLE, AND THE SINGLE POINT THAT GUARANTEES IT.
        # ``resonant_frequency`` is ALWAYS emitted, so at least one record always
        # survives. Three properties together make that true, and all three are
        # load-bearing:
        #
        #   1. it returns a VERBATIM COPY of one of the input frequencies
        #      (``float(frequencies[_resonance_index(s11)])``), so its value is
        #      whatever was handed in and is never derived;
        #   2. ``_require_series`` REJECTS A NON-FINITE FREQUENCY, so that copy is
        #      always finite and the uniform finiteness gate can never omit it;
        #   3. it has no divergence case and no "no value exists" case -- unlike
        #      every other metric here, there is no input for which it declines to
        #      produce a number.
        #
        # THIS IS A SINGLE POINT OF GUARANTEE. THE BANDWIDTH WIDTH IS NOT A SECOND
        # ONE, and it is the obvious candidate to mistake for one: the width is
        # finite whenever it exists (it is the difference of two finite input
        # frequencies), but it can LEGITIMATELY BE ABSENT -- ``minus_10db_bandwidth``
        # returns ``NoMinus10dBBand`` when the resonant sample never reaches -10 dB,
        # which is a normal result and not a failure. So on a sweep with no -10 dB
        # band the width contributes no record at all, and ``resonant_frequency``
        # is carrying this alone.
        #
        # IF A FUTURE CHANGE EVER MAKES ``resonant_frequency`` OMITTABLE -- a
        # divergence case, a "no value" case, an omission condition of its own, or
        # a precondition that stops guaranteeing finite input frequencies -- THEN
        # THIS RAISE BECOMES REACHABLE AND THE REASONING ABOVE MUST BE REVISITED.
        # It would no longer be a defensive branch but a live outcome needing a
        # decision this module has deliberately not made: which arm of
        # ``ComputeMetricsResult`` an all-omitted result belongs to. There is no
        # good answer today, which is why the guarantee is worth protecting rather
        # than working around.
        #
        # The path that USED to reach here was a NaN-poisoned series making every
        # value non-finite at once; that is now refused at the input by
        # ``_require_samples``, which is what property 2 above closed.
        raise MetricsAssemblyError(
            "every approved metric was omitted, so there is no metric to "
            f"report: {_omission_summary(omissions)}. This should be "
            "unreachable -- resonant_frequency is a copy of an input frequency, "
            "which the sparams preconditions guarantee is finite -- so reaching "
            "it means a formula or a precondition changed behaviour. No empty "
            "success is returned in its place."
        )

    text = _template_text(
        records,
        omissions,
        gate_findings,
        routing.qualifying,
        band,
        s11,
        provenance,
        intent,
    )
    # THE ARM FOLLOWS THE ROUTE, and the two are not interchangeable:
    # ``MetricsComputedWithCaveats`` is NOT a subclass of ``MetricsComputed``
    # (ADR-30 dec. 9), so a consumer wanting clean results only cannot silently
    # receive caveated ones.
    if routing.qualifying:
        return MetricsComputedWithCaveats(
            metrics=records,
            qualifying_gates=list(routing.qualifying),
            template_text=text,
        )
    return MetricsComputed(metrics=records, template_text=text)


def _route_gates(
    gate_findings: Sequence[Finding], provenance: ProvenanceRecord
) -> _GateRouting:
    """Partition the supplied gate results into refuse / qualify / permit.

    WAS ``_gate_refusal`` AND RETURNED ``MetricsRefused | None``. The rename comes
    with the semantics: a function named for one of three outcomes cannot report
    the other two, and a ``None`` that used to mean "compute cleanly" now has to
    distinguish "compute cleanly" from "compute under a caveat".

    THE SECOND FAIL-CLOSED LAYER IS UNCHANGED, covering what a required parameter
    cannot: an EMPTY list is perfectly expressible, and it means nothing was
    verified, so it must refuse. Computing on it would make "forgot to run the
    gates" produce numbers indistinguishable from verified ones -- the core
    failure mode the whole product exists to avoid.

    THE OUTCOME LABEL ON THE EMPTY CASE IS A KNOWING, DOCUMENTED MISLABEL, and
    Step 2.6b does not disturb it. ``MetricsRefused.outcome`` is fixed at
    ``"gates_failed"``, and when the list is empty no gate failed because no gate
    ran. It is used anyway, because every alternative is worse: ``CannotEvaluate``
    asserts "PyAEDT could not evaluate this" and nothing here reached PyAEDT
    (ADR-16 decision 5), and the two computed arms would both return numbers. The
    fourth arm added at 2.6a does NOT help here -- it requires at least one
    qualifying gate, and an empty list has none -- so the union still offers no
    honest home. This follows ``broker.classify_outcome``'s precedent for
    ``refused_by_gate`` (ADR-18 decision 6): a knowing, documented mislabelling is
    recoverable in-band, while ambiguity is not.

    REFUSAL WINS OVER QUALIFICATION when both are present, and
    ``failing_gates`` then echoes EVERY non-passing gate rather than only the
    refusing ones. That is the pre-2.6b behaviour, kept deliberately: dropping the
    hedgers would lose information a reader needs -- seeing the ``fail`` without
    seeing that convergence also stopped short tells them less than the current
    output does -- and ``MetricsRefused.failing_gates``' docstring already records
    that its name is a mild misnomer for a warning, with each Finding's own
    five-state ``outcome`` carrying the exact truth.
    """
    if not gate_findings:
        return _GateRouting(
            refusal=MetricsRefused(
                failing_gates=[],
                template_text=_refusal_text(provenance, [], supplied=0),
            ),
            qualifying=(),
        )

    not_passing = [
        finding
        for finding in gate_findings
        if finding.outcome != GATE_OUTCOME_THAT_PERMITS_COMPUTATION
    ]
    # THE ALLOW-LIST IS THE IMPORTED ONE, so this routing and the
    # ``MetricsComputedWithCaveats`` validator consult the same object. A gate
    # whose outcome is on neither list refuses, which is how a sixth
    # ``FindingOutcome`` fails closed.
    refusing = [
        finding
        for finding in not_passing
        if finding.outcome not in GATE_OUTCOMES_THAT_QUALIFY_COMPUTATION
    ]
    if refusing:
        return _GateRouting(
            refusal=MetricsRefused(
                failing_gates=not_passing,
                template_text=_refusal_text(
                    provenance, not_passing, supplied=len(gate_findings)
                ),
            ),
            qualifying=(),
        )

    # ONLY THE HEDGERS TRAVEL, never the passes. ADR-30 dec. 10 excludes ``pass``
    # from the allow-list precisely so this arm cannot be filled entirely with
    # passing gates -- "a result announcing a caveat in its own ``outcome`` and
    # naming none". ``not_passing`` IS the hedger list here, because every refusing
    # outcome was just ruled out.
    return _GateRouting(refusal=None, qualifying=tuple(not_passing))


def _computed_values(
    solved_data: SolvedData,
    s11: Sequence[ComplexSample],
    provenance: ProvenanceRecord,
    intent: IntentObject | None,
) -> tuple[list[_Value], list[_Omission], Minus10dBBand | NoMinus10dBBand]:
    """Run the six formulas, collecting values and stated absences.

    The band result is returned alongside rather than recomputed for the rendered
    text: it is the one formula output carrying detail (its two edge frequencies)
    that no ``MetricRecord`` field can hold, so ``_template_text`` needs the
    object itself and not just the width that became a record.

    THE CALL ORDER OF THE THREE AT-TARGET FORMULAS IS LOAD-BEARING, and it is
    what makes the narrow ``except ValueError`` below provably narrow rather than
    hopefully narrow. ``sparams`` raises ``ValueError`` for two unrelated classes
    of reason -- violated preconditions (which must propagate) and divergence
    over sound data (which must be reported) -- and a blanket catch cannot tell
    them apart, while re-checking the preconditions here would create a second
    source for rules ``sparams`` already owns (the defect ``export``'s Z0 comment
    refuses).

    So ``s11_at_target`` is called FIRST, on the same three arguments. It routes
    through the identical ``_interpolated_gamma``, so any series or target
    problem raises there and propagates. By the time ``vswr_at_target`` and
    ``impedance_at_target`` run on those same arguments, the ONLY remaining cause
    of a ``ValueError`` from either is its own divergence guard -- which is
    exactly what the catch is for.

    Reordering these three calls, or wrapping ``s11_at_target`` in the same
    ``try``, silently widens both catches into precondition-swallowers.
    """
    frequencies = solved_data.frequencies
    values: list[_Value] = []
    omissions: list[_Omission] = []

    # --- the whole-sweep metrics, which need no target frequency --------------
    values.append(_Value(S11_MIN, s11_min(s11), DB, S11_MIN_REF))
    values.append(
        _Value(
            RESONANT_FREQUENCY,
            resonant_frequency(frequencies, s11),
            HZ,
            RESONANT_FREQUENCY_REF,
        )
    )
    band = minus_10db_bandwidth(frequencies, s11)
    if isinstance(band, Minus10dBBand):
        # The WIDTH is the metric. The two edge frequencies are supporting
        # evidence with nowhere in MetricRecord to live (it has no
        # observed_values field), so they are rendered in template_text instead.
        values.append(
            _Value(
                MINUS_10DB_BANDWIDTH, band.width_hz, HZ, MINUS_10DB_BANDWIDTH_REF
            )
        )
    else:
        # A zero-width record here would be a fabrication: 0.0 is a legitimate
        # Minus10dBBand width (exactly one sample in band), so it cannot double
        # as "no band". The two are different types in sparams for this reason.
        omissions.append(_Omission(MINUS_10DB_BANDWIDTH, band.reason))

    # --- the at-target metrics ------------------------------------------------
    if intent is None:
        omissions += [_Omission(name, NO_INTENT_REASON) for name in AT_TARGET_METRICS]
        return values, omissions, band

    target = intent.target_frequency_hz
    # FIRST, AND NOT INSIDE A TRY: this call establishes the shared preconditions
    # for the two below. See the docstring.
    values.append(
        _Value(
            S11_AT_TARGET,
            s11_at_target(frequencies, s11, target),
            DB,
            S11_AT_TARGET_REF,
        )
    )

    try:
        reflection_ratio = vswr_at_target(frequencies, s11, target)
    except ValueError as exc:
        # |G| > 1 only. Physically implausible data that PyAEDT returned
        # perfectly well -- so NOT a CannotEvaluate, which would blame the solver
        # for a data condition, and NOT a gate failure, since no W-9 gate covers
        # reflection magnitude and inventing a fifth would mean owning a rule id
        # and version we do not have.
        omissions.append(_Omission(VSWR_AT_TARGET, str(exc)))
    else:
        values.append(
            _Value(VSWR_AT_TARGET, reflection_ratio, RATIO, VSWR_AT_TARGET_REF)
        )

    try:
        impedance = impedance_at_target(
            frequencies, s11, target, provenance.reference_impedance
        )
    except ValueError as exc:
        # G == 1+0j only. BOTH records are omitted together: the complex value
        # has no limit at all there (which phase an infinity would carry depends
        # on the direction of approach), so neither part exists -- unlike the
        # VSWR case one line up, where |G| = 1 has a true limiting value of +inf.
        omissions += [
            _Omission(IMPEDANCE_AT_TARGET_RESISTANCE, str(exc)),
            _Omission(IMPEDANCE_AT_TARGET_REACTANCE, str(exc)),
        ]
    else:
        # Z0 comes from provenance.reference_impedance and nowhere else; 50 is
        # never assumed, here or in the formula.
        values.append(
            _Value(
                IMPEDANCE_AT_TARGET_RESISTANCE,
                impedance.real,
                OHM,
                IMPEDANCE_AT_TARGET_REF,
            )
        )
        values.append(
            _Value(
                IMPEDANCE_AT_TARGET_REACTANCE,
                impedance.imag,
                OHM,
                IMPEDANCE_AT_TARGET_REF,
            )
        )
    return values, omissions, band


def _finite_records(
    values: Sequence[_Value], provenance: ProvenanceRecord, gate_status: str
) -> tuple[list[MetricRecord], list[_Omission]]:
    """Build a record per value, omitting any value strict JSON cannot carry.

    ONE UNIFORM GATE OVER EVERY VALUE, not three enumerated special cases, and
    the generality is the point: ``s11_min`` at |G| = 0 and ``vswr_at_target`` at
    |G| = 1 are the two KNOWN divergences, but ``s11_at_target`` yields ``-inf``
    on an exactly-zero interpolated reflection, an impedance can overflow to
    ``inf`` when ``1 - G`` is denormal-small, and a non-finite
    ``reference_impedance`` would poison both impedance parts. Enumerating cases
    would miss whichever one nobody thought of; checking the value cannot.

    WHY A NON-FINITE VALUE CANNOT SIMPLY BE STORED, measured rather than assumed
    (pydantic 2.13.4, and both defaults matter): ``allow_inf_nan`` is True, so
    ``MetricRecord(value=-inf)`` VALIDATES; ``ser_json_inf_nan`` is ``'null'``,
    so ``model_dump_json()`` then emits ``"value":null``. A consumer reading
    ``null`` where the schema declares ``float`` cannot tell "infinitely deep
    match" from "no value", and ``model_dump()`` keeps the ``-inf``, so an
    in-process consumer and a JSON consumer would disagree about one record. That
    silent divergence is the failure this gate exists to prevent, and it bites at
    the MCP tool response -- the user- and LLM-facing boundary -- because that is
    where ``MetricRecord`` travels. (It is NOT in the DesignSnapshot: the
    wrapper->engine seam is snapshot in, findings out, and carries no metrics.)

    THE FORMULAS ARE NOT CHANGED TO SUIT THIS, and must not be. ``sparams``'
    module docstring is explicit that serializability cannot distinguish a real
    limiting value from an error and must not be used to. So ``s11_min`` keeps
    returning ``-inf``, which is the true answer; this layer declines to put that
    answer in a JSON field and says so instead.

    THE COST, STATED: a perfect match is the BEST possible result and produces no
    ``s11_min`` record. Exact-zero |G| is effectively unreachable in measured
    data, and the value and reason are rendered in ``template_text``, so nothing
    is hidden -- but the |G| = 1 total-reflection case IS reachable (an unsolved
    or shorted port), so this path is not hypothetical.

    Fixing it properly means ``value: float | None`` plus a status field on
    ``MetricRecord``, which is a semver event on the contract and deliberately
    out of scope here.
    """
    records: list[MetricRecord] = []
    omissions: list[_Omission] = []
    for value in values:
        if not math.isfinite(value.value):
            omissions.append(
                _Omission(value.metric_name, _non_finite_reason(value))
            )
            continue
        records.append(
            MetricRecord(
                metric_name=value.metric_name,
                value=value.value,
                units=value.units,
                formula_ref=value.formula_ref,
                # ASSERTS MORE THAN W-7 CAN VERIFY, AND A READER SHOULD KNOW IT.
                # This says what the gates DID; W-7 checked only the Findings it
                # was HANDED. It cannot confirm the list is the COMPLETE set of
                # four, because that needs the four rule ids, which live in
                # ``gating`` (which metrics may not import) or in a new contract
                # constant (a semver event). Gate-set completeness is therefore
                # the CALLER'S responsibility, and from Step 3.4 there is exactly
                # one caller constructing this list from ``evaluate_gates`` -- one
                # auditable call site. The count and the rule ids of what was
                # actually supplied are rendered in template_text, which is the
                # honest place for a claim this string is too coarse to make.
                #
                # PASSED IN RATHER THAN CONSTANT since Step 2.6b: the caller chose
                # the route, and a record must not stamp ``all_gates_passed`` when
                # its own result arm says otherwise.
                gate_status_at_computation=gate_status,
                provenance=provenance,
            )
        )
    return records, omissions


def _non_finite_reason(value: _Value) -> str:
    """Why a computed value has no record, naming the value it would have held.

    The number is stated in the prose precisely BECAUSE it cannot be stated in
    the field: omitting the record without saying what was omitted would turn a
    real answer into silence, which is the one outcome worse than an
    unrepresentable one.
    """
    limit = "positive infinity" if value.value > 0 else "negative infinity"
    if math.isnan(value.value):
        limit = "not a number (NaN)"
    return (
        f"the computed value is {limit} ({value.value!r} {value.units}), which is "
        "a true limiting value of the formula but is not representable in strict "
        "JSON (RFC 8259). It is reported here rather than in a MetricRecord, "
        "whose value field would serialize to null and become "
        "indistinguishable from no value at all"
    )


def _ordered(omissions: Sequence[_Omission]) -> list[_Omission]:
    """Omissions in ``METRIC_ORDER``, so output cannot depend on failure order.

    Two omissions can be produced at three different points (the band check, the
    no-intent branch, the finiteness gate), and their collection order reflects
    the code path rather than anything meaningful. Sorting on the canonical tuple
    is what keeps ``template_text`` byte-identical for identical inputs.
    """
    return sorted(
        omissions, key=lambda omission: METRIC_ORDER.index(omission.metric_name)
    )


def _template_text(
    records: Sequence[MetricRecord],
    omissions: Sequence[_Omission],
    gate_findings: Sequence[Finding],
    qualifying: Sequence[Finding],
    band: Minus10dBBand | NoMinus10dBBand,
    s11: Sequence[ComplexSample],
    provenance: ProvenanceRecord,
    intent: IntentObject | None,
) -> str:
    """The deterministic core text (§3): complete without any LLM.

    BYTE-DETERMINISTIC AND TIMESTAMP-FREE, following W-5 and W-6. The same inputs
    render identical bytes, so tests can pin the wording and a diff between two
    results shows only what actually changed in the data. No instant is echoed:
    ``provenance.solve_timestamp`` is the typed, machine-readable home for it.
    Determinism holds structurally -- ``records`` is built in ``METRIC_ORDER``
    and ``omissions`` is sorted into it, with no dict iteration on this path.

    NEWLINE-JOINED, not space-joined as W-5's is: a metric set IS a list, and
    flattening it onto one line would misrepresent its shape. This follows W-6's
    reasoning for the same choice.

    THE VALUES ARE RENDERED, because for this tool they ARE the content -- §3
    requires the deterministic text to be complete without an LLM, and a metrics
    read-out that withheld its numbers would be a receipt for content it does not
    contain. Rendered at ``repr(float(...))``, matching ``export``'s ``_number``:
    full round-trippable precision, nothing rounded.

    THIS TEXT IS THE ONLY HOME FOR THREE THINGS MetricRecord CANNOT HOLD, and
    that is a named contract limitation rather than a preference: the omission
    reasons (``MetricRecord`` has no ``read_status``/``limitation`` field the way
    ``InspectionSection`` does), the -10 dB band EDGES (no ``observed_values``
    field), and the gate count and rule ids that qualify
    ``gate_status_at_computation``.

    ``project`` and ``design`` are untrusted HFSS-sourced strings (pre-sanitized
    at the adapter, ADR-9) and are rendered inside quotes as data, never in an
    instruction position (§6.6).
    """
    parts: list[str] = []
    # THE CAVEAT GOES FIRST. Neda's ruling (ADR-30 dec. 7) chose "Show the
    # numbers, with a clear notice ON TOP", and the position was part of what she
    # chose -- a notice below the numbers is read after the reader has already
    # taken them in. See this function's docstring for what moved.
    if qualifying:
        parts.append(_CAVEAT_HEADING)
        parts += [
            f"  [{finding.rule_id}] {finding.outcome}: {finding.reason_flagged}"
            for finding in qualifying
        ]

    parts.append(
        f'Metrics for project "{provenance.project}", design '
        f'"{provenance.design}", variation '
        f"{provenance.variation.variation_hash}: {len(records)} of "
        f"{len(METRIC_ORDER)} approved metric record(s) computed, "
        f"{len(omissions)} omitted. {_gate_sentence(gate_findings, qualifying)}"
    )
    if intent is not None:
        parts.append(
            "Target frequency: "
            f"{_number(intent.target_frequency_hz)} Hz (from the design intent)."
        )
    parts.append(f"Computed from {len(s11)} swept sample(s):")
    parts += [
        f"  {record.metric_name} = {_number(record.value)} {record.units} "
        f"[{record.formula_ref}]"
        for record in records
    ]
    if isinstance(band, Minus10dBBand):
        parts.append(
            "  -10 dB band edges: "
            f"{_number(band.low_frequency_hz)} Hz to "
            f"{_number(band.high_frequency_hz)} Hz. These are ACTUAL SWEPT "
            "frequencies, not interpolated ones, so the bandwidth's resolution "
            "is bounded by the sweep's step size."
        )
    if omissions:
        parts.append("Not computed:")
        parts += [
            f"  {omission.metric_name}: {omission.reason}" for omission in omissions
        ]
    parts.append(_NO_INTERPRETATION_NOTICE)
    return "\n".join(parts)


def _gate_sentence(
    gate_findings: Sequence[Finding], qualifying: Sequence[Finding]
) -> str:
    """What the supplied gates did, stated without overclaiming either way.

    TWO SENTENCES, NOT ONE WITH A CONDITIONAL CLAUSE. "All N gate result(s)
    supplied passed" is simply FALSE on the caveated arm, and it is the kind of
    false that a reader trusts because it is stated in the same breath as a true
    count. The completeness disclaimer is common to both, because W-7's inability
    to confirm the set of four does not depend on how the gates came out.
    """
    disclaimer = (
        "the wrapper verified the outcomes it was handed and does not itself "
        "confirm that this is the complete set of four gates."
    )
    if not qualifying:
        return (
            f"All {len(gate_findings)} gate result(s) supplied passed "
            f"({_rule_ids(gate_findings)}); {disclaimer}"
        )
    return (
        f"{len(qualifying)} of {len(gate_findings)} gate result(s) supplied did "
        f"NOT pass and qualify the values above ({_rule_ids(qualifying)}); the "
        f"rest passed. No gate failed -- numbers are never reported when one "
        f"does. Of the gates supplied ({_rule_ids(gate_findings)}), {disclaimer}"
    )


def _refusal_text(
    provenance: ProvenanceRecord, not_passing: Sequence[Finding], supplied: int
) -> str:
    """The deterministic refusal text: why there are no numbers.

    States the gate outcomes verbatim and reports NO metric value of any kind --
    not even one that was computable. The refusal is the whole result.

    The zero-gate case gets its own sentence rather than rendering as "0 of 0
    failed", because silence there would read as a verdict: a reader seeing an
    empty gate list will supply "so there was nothing wrong with the gates" on
    their own. This is the same misread W-6's ``_NO_MESSAGES_NOTICE`` guards
    against, refused out loud for the same reason.
    """
    parts = [
        f'Metrics refused for project "{provenance.project}", design '
        f'"{provenance.design}": no metrics were computed and no numbers are '
        "reported."
    ]
    if supplied == 0:
        parts.append(
            "NO GATE RESULTS WERE SUPPLIED AT ALL, so nothing was verified. This "
            "is not a statement that the gates passed, and it is not a statement "
            "that they failed -- they did not run. The result is labelled "
            '"gates_failed" because that is the only refusal outcome the '
            "contract provides; the label is imprecise here and this sentence is "
            "the correction."
        )
    else:
        parts.append(
            f"{len(not_passing)} of {supplied} gate result(s) supplied did not "
            "pass:"
        )
        parts += [
            f"  [{finding.rule_id}] {finding.outcome}: {finding.reason_flagged}"
            for finding in not_passing
        ]
    parts.append(_REFUSAL_POLICY_NOTICE)
    return "\n".join(parts)


def _rule_ids(gate_findings: Sequence[Finding]) -> str:
    """The supplied gates' rule ids, in the order supplied, as readable data."""
    if not gate_findings:
        return "none"
    return ", ".join(finding.rule_id for finding in gate_findings)


def _omission_summary(omissions: Sequence[_Omission]) -> str:
    """Every omitted metric name, for the defensive all-omitted error message."""
    return ", ".join(omission.metric_name for omission in omissions) or "none recorded"


def _number(value: float) -> str:
    """A float at full round-trippable precision -- Python's default repr.

    The same choice ``export._number`` makes, for the same reason: a rounded
    number in a rendered read-out no longer matches the one in the typed field
    beside it, and a reader cannot tell which is authoritative.
    """
    return repr(float(value))
