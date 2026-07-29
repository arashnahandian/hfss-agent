"""W-7 assembly: the gate check, the record mapping, and the three seams.

Distinct from ``test_sparams.py``, which pins the six formulas' arithmetic. This
file pins what the ASSEMBLER does with those numbers: which gate outcomes permit
computation at all, how six formulas become seven ``MetricRecord``s, and what
happens to a value that cannot be a record.

THREE PROPERTIES CARRY MOST OF THE WEIGHT, each with its own section:

  1. FAIL-CLOSED. Only ``pass`` permits computation, and a caller who supplies no
     gate results gets a refusal rather than numbers — in two layers, because a
     required parameter cannot cover the empty list.
  2. THE NARROW CATCH IS NARROW. ``sparams`` raises ``ValueError`` both for
     violated preconditions (which must propagate — reaching one means the gates
     were skipped) and for divergence over sound data (which must be reported as
     an omission). ``test_a_skipped_gate_precondition_still_propagates`` is the
     assertion that keeps the two apart; if it ever fails, the catch has widened
     into a precondition-swallower and a skipped gate has become invisible.
  3. NO NON-FINITE VALUE REACHES JSON. ``MetricRecord(value=-inf)`` validates and
     then serializes to ``"value":null``, so the assertions here are made against
     ``model_dump_json()`` and against strict ``json.loads``, never against the
     Python-mode dump that would happily keep the ``inf`` and prove nothing.
"""

from __future__ import annotations

import json
import math

import pytest
from assembly_helpers import (
    FOUR_GATE_NAMES,
    GHZ,
    IDEAL_OPEN,
    NEVER_REACHES_10DB,
    PERFECT_MATCH,
    REFLECTION_ABOVE_UNITY,
    RESONANT_AT_3GHZ,
    RESONANT_AT_6GHZ,
    TARGET_2GHZ,
    TARGET_3GHZ,
    TARGET_6GHZ,
    TOTAL_REFLECTION_SHORT,
    Z0,
    four_gates_with,
    four_passing_gates,
    gate,
    intent_at,
    provenance_for,
    solved,
)

from hfss_agent.broker import session_routed_specs
from hfss_agent.contract import MetricRecord
from hfss_agent.contract.tool_io import CannotEvaluate, MetricsComputed, MetricsRefused
from hfss_agent.metrics import (
    ALL_GATES_PASSED,
    AT_TARGET_METRICS,
    DB,
    HZ,
    IMPEDANCE_AT_TARGET_REACTANCE,
    IMPEDANCE_AT_TARGET_RESISTANCE,
    METRIC_ORDER,
    MINUS_10DB_BANDWIDTH,
    OHM,
    RATIO,
    RESONANT_FREQUENCY,
    S11_AT_TARGET,
    S11_MIN,
    VSWR_AT_TARGET,
    MetricsAssemblyError,
    compute_metrics,
)
from hfss_agent.metrics.sparams import (
    IMPEDANCE_AT_TARGET_REF,
    MINUS_10DB_BANDWIDTH_REF,
    RESONANT_FREQUENCY_REF,
    S11_AT_TARGET_REF,
    S11_MIN_REF,
    VSWR_AT_TARGET_REF,
)

EXACT = {"rel": 1e-12, "abs": 1e-12}


def _by_name(result: MetricsComputed) -> dict[str, MetricRecord]:
    return {record.metric_name: record for record in result.metrics}


def _computed(**kwargs: object) -> MetricsComputed:
    """Call the assembler on the nominal fixture, asserting the success arm.

    Keeps every test below from repeating the isinstance narrowing, and makes an
    accidental refusal fail at the call site rather than three assertions later.
    """
    result = compute_metrics(
        kwargs.pop("gate_findings", four_passing_gates()),  # type: ignore[arg-type]
        kwargs.pop("solved_data", RESONANT_AT_3GHZ),  # type: ignore[arg-type]
        kwargs.pop("provenance", provenance_for()),  # type: ignore[arg-type]
        kwargs.pop("intent", intent_at(TARGET_3GHZ)),  # type: ignore[arg-type]
    )
    assert not kwargs, f"unused kwargs: {sorted(kwargs)}"
    assert isinstance(result, MetricsComputed), result
    return result


# --- 1. the gate check and the two fail-closed layers -------------------------


def test_all_gates_passing_yields_metrics_computed() -> None:
    result = _computed()
    assert result.outcome == "metrics_computed"
    assert result.metrics


def test_a_failing_gate_refuses_and_returns_no_numbers() -> None:
    """The runbook's Step 2.3 Done criterion: the refusal stub, exercised.

    Three assertions, because "no numbers" has to hold structurally and not just
    in this instance: the arm is the refusal one, the failing gate is echoed, and
    the returned object has no ``metrics`` attribute AT ALL — ``MetricsRefused``
    declares none and forbids extras, so "refused, but here are numbers anyway"
    is unconstructible rather than merely absent.
    """
    gates = four_gates_with("convergence", "fail")
    result = compute_metrics(
        gates, RESONANT_AT_3GHZ, provenance_for(), intent_at(TARGET_3GHZ)
    )
    assert isinstance(result, MetricsRefused)
    assert result.outcome == "gates_failed"
    assert [finding.rule_id for finding in result.failing_gates] == [
        "gate.convergence"
    ]
    assert not hasattr(result, "metrics")


def test_insufficient_evidence_refuses_like_a_failure() -> None:
    """§1.1: the freshness gate must be able to say "cannot determine", and that
    must never read as a pass. This is the gate Neda flagged as the one most
    likely to hit a PyAEDT limitation, so it gets its own named test rather than
    riding along in the parametrized case below."""
    gates = four_gates_with("freshness", "insufficient_evidence")
    result = compute_metrics(
        gates, RESONANT_AT_3GHZ, provenance_for(), intent_at(TARGET_3GHZ)
    )
    assert isinstance(result, MetricsRefused)
    assert result.failing_gates[0].outcome == "insufficient_evidence"


@pytest.mark.parametrize("outcome", ["fail", "warning", "not_evaluated"])
def test_every_non_passing_outcome_refuses(outcome: str) -> None:
    """The allow-list, asserted across every non-passing outcome in the enum.

    ``warning`` and ``not_evaluated`` are the two that could plausibly have been
    read as permitting. They do not: ``MetricsComputed`` has no field to carry a
    caveat, so permitting on a warning would produce numbers whose qualification
    existed only in prose. The Finding still reaches the caller with its
    five-state outcome intact.
    """
    gates = four_gates_with("solution_exists", outcome)  # type: ignore[arg-type]
    result = compute_metrics(
        gates, RESONANT_AT_3GHZ, provenance_for(), intent_at(TARGET_3GHZ)
    )
    assert isinstance(result, MetricsRefused)
    assert result.failing_gates[0].outcome == outcome


def test_no_gate_results_refuses() -> None:
    """Fail-closed layer 2: the empty list, which a required parameter cannot catch.

    Also pins the knowing mislabel: the outcome literal says "gates_failed" when
    in fact no gate ran, so the template text must say so outright — the
    imprecision is allowed to live in the enum value and nowhere else.
    """
    result = compute_metrics(
        [], RESONANT_AT_3GHZ, provenance_for(), intent_at(TARGET_3GHZ)
    )
    assert isinstance(result, MetricsRefused)
    assert result.failing_gates == []
    assert "NO GATE RESULTS WERE SUPPLIED AT ALL" in result.template_text
    assert "they did not run" in result.template_text


def test_omitting_gate_results_is_a_type_error() -> None:
    """Fail-closed layer 1: the omission is un-expressible, not handled.

    ``gate_findings`` has no default, so a caller who forgets it cannot reach any
    code path at all — the same structural trick as ``CapabilitySpec.tier`` and
    ``ExportRefused.outcome``. A defaulted parameter would have made this a
    silent computation on unverified data.
    """
    with pytest.raises(TypeError):
        compute_metrics(  # type: ignore[call-arg]
            solved_data=RESONANT_AT_3GHZ, provenance=provenance_for()
        )


def test_only_non_passing_gates_are_echoed() -> None:
    # Four gates in, two failing: the refusal carries the two, not all four. A
    # passing gate is not a finding about a problem and does not belong in a list
    # the caller will read as "what went wrong".
    gates = [
        gate("solution_exists", "pass"),
        gate("convergence", "fail"),
        gate("freshness", "insufficient_evidence"),
        gate("target_coverage", "pass"),
    ]
    result = compute_metrics(
        gates, RESONANT_AT_3GHZ, provenance_for(), intent_at(TARGET_3GHZ)
    )
    assert isinstance(result, MetricsRefused)
    assert [finding.rule_id for finding in result.failing_gates] == [
        "gate.convergence",
        "gate.freshness",
    ]


# --- 2. the record mapping: six formulas, seven records -----------------------


def test_the_six_formulas_produce_seven_metric_records() -> None:
    """The count and the exact names, pinned together.

    Seven rather than six because ``impedance_at_target`` returns a ``complex``
    and ``MetricRecord.value`` is one float, so its result is split into the
    resistive and reactive parts. Nothing else splits.
    """
    result = _computed()
    assert len(result.metrics) == 7
    assert [record.metric_name for record in result.metrics] == list(METRIC_ORDER)
    assert set(METRIC_ORDER) == {
        S11_MIN,
        RESONANT_FREQUENCY,
        MINUS_10DB_BANDWIDTH,
        S11_AT_TARGET,
        VSWR_AT_TARGET,
        IMPEDANCE_AT_TARGET_RESISTANCE,
        IMPEDANCE_AT_TARGET_REACTANCE,
    }


def test_every_record_names_its_units_and_formula_ref() -> None:
    # The units table, asserted as data rather than described in a comment: a
    # record whose units field drifted would otherwise be invisible.
    records = _by_name(_computed())
    assert {name: record.units for name, record in records.items()} == {
        S11_MIN: DB,
        RESONANT_FREQUENCY: HZ,
        MINUS_10DB_BANDWIDTH: HZ,
        S11_AT_TARGET: DB,
        VSWR_AT_TARGET: RATIO,
        IMPEDANCE_AT_TARGET_RESISTANCE: OHM,
        IMPEDANCE_AT_TARGET_REACTANCE: OHM,
    }
    assert {name: record.formula_ref for name, record in records.items()} == {
        S11_MIN: S11_MIN_REF,
        RESONANT_FREQUENCY: RESONANT_FREQUENCY_REF,
        MINUS_10DB_BANDWIDTH: MINUS_10DB_BANDWIDTH_REF,
        S11_AT_TARGET: S11_AT_TARGET_REF,
        VSWR_AT_TARGET: VSWR_AT_TARGET_REF,
        IMPEDANCE_AT_TARGET_RESISTANCE: IMPEDANCE_AT_TARGET_REF,
        IMPEDANCE_AT_TARGET_REACTANCE: IMPEDANCE_AT_TARGET_REF,
    }


def test_both_impedance_records_cite_the_one_impedance_formula() -> None:
    # The split must not invent a second formula to point at: there is one
    # function, one reference string, and a reader following either record's
    # formula_ref must land on it.
    records = _by_name(_computed())
    assert (
        records[IMPEDANCE_AT_TARGET_RESISTANCE].formula_ref
        == records[IMPEDANCE_AT_TARGET_REACTANCE].formula_ref
        == IMPEDANCE_AT_TARGET_REF
    )


def test_the_values_are_the_hand_checkable_ones() -> None:
    """The seven values on the nominal fixture, each readable off the fixture.

    RESONANT_AT_3GHZ is [0, -20, -40, -20, 0] dB at 1..5 GHz, target 3 GHz lands
    exactly on the resonant sample so nothing is interpolated, and |G| = 0.01
    there.
    """
    records = _by_name(_computed())
    assert records[S11_MIN].value == pytest.approx(-40.0, **EXACT)
    assert records[RESONANT_FREQUENCY].value == 3 * GHZ
    assert records[MINUS_10DB_BANDWIDTH].value == 2 * GHZ  # 4 GHz - 2 GHz
    assert records[S11_AT_TARGET].value == pytest.approx(-40.0, **EXACT)
    assert records[VSWR_AT_TARGET].value == pytest.approx(1.01 / 0.99, **EXACT)
    assert records[IMPEDANCE_AT_TARGET_RESISTANCE].value == pytest.approx(
        Z0 * 1.01 / 0.99, **EXACT
    )
    # G is purely real at this sample, so the reactance is exactly zero -- and a
    # zero-valued record is a real record, not an omission.
    assert records[IMPEDANCE_AT_TARGET_REACTANCE].value == pytest.approx(0.0, abs=1e-12)


def test_gate_status_is_recorded_on_every_record() -> None:
    # Spelled to match the contract-schema fixtures exactly, so the producer and
    # the fixtures cannot drift apart.
    assert all(
        record.gate_status_at_computation == ALL_GATES_PASSED
        for record in _computed().metrics
    )
    assert ALL_GATES_PASSED == "all_gates_passed"


def test_the_gate_status_string_is_qualified_in_the_text() -> None:
    """The documented gap, asserted so it cannot quietly disappear.

    ``gate_status_at_computation`` asserts the gates passed, but W-7 cannot
    confirm the list it was handed is the complete set of four — that needs the
    four rule ids, which live in ``gating`` (unimportable) or a new contract
    constant (a semver event). So the text must state the count and the rule ids
    actually supplied, and must not claim more.
    """
    text = _computed().template_text
    assert "does not itself confirm that this is the complete set of four" in text
    for name in FOUR_GATE_NAMES:
        assert f"gate.{name}" in text


def test_a_single_passing_gate_still_computes_but_says_so() -> None:
    # The gap above is real and this is what it looks like: one passing gate is
    # enough to satisfy the allow-list, because W-7 has no way to know three are
    # missing. What it CAN do is report exactly what it was given, which is why
    # the count in the text is not decorative.
    result = _computed(gate_findings=[gate("solution_exists", "pass")])
    assert "All 1 gate result(s) supplied passed" in result.template_text
    assert "gate.solution_exists" in result.template_text


def test_no_band_omits_the_bandwidth_record_and_states_why() -> None:
    """``NoMinus10dBBand`` becomes a stated omission, never a zero-valued record.

    Zero is a legitimate ``Minus10dBBand`` width (exactly one sample in band), so
    it cannot double as "no band" — the two are different types in ``sparams``
    for precisely this reason, and collapsing them here would undo that.
    """
    result = _computed(solved_data=NEVER_REACHES_10DB, intent=intent_at(TARGET_2GHZ))
    names = [record.metric_name for record in result.metrics]
    assert MINUS_10DB_BANDWIDTH not in names
    assert len(result.metrics) == 6
    assert "does not reach -10 dB" in result.template_text


def test_no_intent_omits_the_four_at_target_records() -> None:
    """No target frequency is ever assumed — spec Point 9 on the frequency axis.

    Three records, not seven, and the four at-target records say why they are
    absent. A defaulted 2.4 GHz would have put an unverified number inside four
    reported metrics.

    Four records from three formulas: ``impedance_at_target`` alone contributes
    two, which is why the count here is not the number of at-target formulas.
    """
    result = _computed(intent=None)
    names = [record.metric_name for record in result.metrics]
    assert names == [S11_MIN, RESONANT_FREQUENCY, MINUS_10DB_BANDWIDTH]
    for omitted in AT_TARGET_METRICS:
        assert omitted not in names
        assert omitted in result.template_text
    assert "no design intent was supplied" in result.template_text


def test_metrics_computed_is_never_returned_empty() -> None:
    """``MetricsComputed(metrics=[])`` is constructible, so it must be refused.

    An empty success arm would assert "the gates passed and the metrics were
    computed" while carrying nothing, with all three other arms of the union
    being lies. The assembler raises instead — and this asserts the property
    across every fixture, since the all-omitted case is now unreachable by
    construction rather than by inspection.
    """
    # Constructible, which is why the guard is needed at all.
    assert MetricsComputed(metrics=[], template_text="x").metrics == []
    for data, intent in (
        (RESONANT_AT_3GHZ, intent_at(TARGET_3GHZ)),
        (NEVER_REACHES_10DB, intent_at(TARGET_2GHZ)),
        (PERFECT_MATCH, intent_at(TARGET_2GHZ)),
        (IDEAL_OPEN, intent_at(TARGET_2GHZ)),
        (REFLECTION_ABOVE_UNITY, intent_at(TARGET_2GHZ)),
        (RESONANT_AT_3GHZ, None),
    ):
        assert _computed(solved_data=data, intent=intent).metrics


def test_resonant_frequency_is_what_makes_the_empty_case_unreachable() -> None:
    """The load-bearing reason the all-omitted case cannot happen.

    ``resonant_frequency`` returns a verbatim copy of an input frequency, and the
    ``sparams`` preconditions now reject a non-finite frequency — so it has no
    divergence case, no "no value exists" case, and always survives. The -10 dB
    width is finite whenever it exists but can legitimately be ABSENT, so it is
    not a second guarantee; this one metric carries it alone.
    """
    # No intent AND no -10 dB band is the MINIMUM record count the assembler can
    # emit: only s11_min and resonant_frequency remain, with the band and all four
    # at-target records omitted.
    assert len(_computed(solved_data=NEVER_REACHES_10DB, intent=None).metrics) == 2

    for data, intent in (
        (NEVER_REACHES_10DB, None),
        (PERFECT_MATCH, intent_at(TARGET_2GHZ)),
        (IDEAL_OPEN, intent_at(TARGET_2GHZ)),
    ):
        records = _by_name(_computed(solved_data=data, intent=intent))
        assert RESONANT_FREQUENCY in records
        assert math.isfinite(records[RESONANT_FREQUENCY].value)


# --- 3. seam (a): a divergence no W-9 gate covers -----------------------------


def test_a_reflection_above_unity_omits_vswr_and_states_why() -> None:
    """|G| > 1 is reachable with all four gates green, and is not a solver fault.

    The other six records survive — and that matters, because they are the
    numbers a user needs in order to diagnose the |G| > 1 condition in the first
    place. Discarding them all would destroy exactly the evidence.
    """
    result = _computed(
        solved_data=REFLECTION_ABOVE_UNITY, intent=intent_at(TARGET_2GHZ)
    )
    names = [record.metric_name for record in result.metrics]
    assert VSWR_AT_TARGET not in names
    assert len(result.metrics) == 6
    assert "non-physical for a passive" in result.template_text
    # The impedance at |G| = 1.5 is a finite (negative) number, and it IS
    # reported: W-7 does not judge plausibility, and inventing a rule against a
    # negative resistance would mean owning a fifth gate we do not have.
    assert IMPEDANCE_AT_TARGET_RESISTANCE in names


def test_an_implausible_value_is_not_reported_as_a_pyaedt_failure() -> None:
    """The misattribution guard, asserted directly.

    ``CannotEvaluate`` means specifically "PyAEDT could not evaluate this"
    (ADR-16 decision 5). PyAEDT returned this data perfectly well; the data is
    just non-physical. Reporting it as a solver limitation would blame the wrong
    component, and reporting it as a gate failure would mean fabricating a
    Finding for a gate that does not exist.
    """
    result = compute_metrics(
        four_passing_gates(),
        REFLECTION_ABOVE_UNITY,
        provenance_for(),
        intent_at(TARGET_2GHZ),
    )
    assert not isinstance(result, CannotEvaluate)
    assert not isinstance(result, MetricsRefused)
    assert isinstance(result, MetricsComputed)


def test_an_ideal_open_omits_both_impedance_records() -> None:
    """G = 1+0j: the complex value has no limit, so neither part exists.

    Both records go together, unlike the VSWR case at the same |G| = 1, where
    +inf IS the true limiting value. Pinning them at one data point is what keeps
    the two divergences from being "fixed" into agreement later.
    """
    result = _computed(solved_data=IDEAL_OPEN, intent=intent_at(TARGET_2GHZ))
    names = [record.metric_name for record in result.metrics]
    assert IMPEDANCE_AT_TARGET_RESISTANCE not in names
    assert IMPEDANCE_AT_TARGET_REACTANCE not in names
    assert "impedance is unbounded" in result.template_text


def test_the_two_unit_circle_cases_are_distinguished() -> None:
    """|G| = 1 alone does not decide the impedance's fate — WHERE on the circle does.

    A short (G = -1) and an open (G = 1+0j) both make VSWR diverge, and both have
    |G| = 1 exactly. The impedance is 0+0j for the short (finite, reported) and
    has no limit for the open (omitted). If a later edit collapses these, the
    short's perfectly good zero-ohm reading disappears.
    """
    short = _computed(
        solved_data=TOTAL_REFLECTION_SHORT, intent=intent_at(TARGET_2GHZ)
    )
    short_records = _by_name(short)
    assert VSWR_AT_TARGET not in short_records
    assert short_records[IMPEDANCE_AT_TARGET_RESISTANCE].value == pytest.approx(
        0.0, abs=1e-12
    )
    assert short_records[IMPEDANCE_AT_TARGET_REACTANCE].value == pytest.approx(
        0.0, abs=1e-12
    )

    ideal_open = _by_name(
        _computed(solved_data=IDEAL_OPEN, intent=intent_at(TARGET_2GHZ))
    )
    assert VSWR_AT_TARGET not in ideal_open
    assert IMPEDANCE_AT_TARGET_RESISTANCE not in ideal_open


@pytest.mark.parametrize(
    ("target_hz", "match"),
    [
        (0.5 * GHZ, "outside the swept range"),
        (9.0 * GHZ, "outside the swept range"),
    ],
)
def test_a_skipped_gate_precondition_still_propagates(
    target_hz: float, match: str
) -> None:
    """THE MOST LOAD-BEARING TEST IN THIS FILE.

    An out-of-range target is what W-9 gate (d) exists to prevent, so reaching it
    means the gates were skipped — a programming error. It must escape as a
    ``ValueError``, NOT be absorbed into a stated omission, because an omission
    would report a skipped gate as a missing metric and the caller would never
    learn they bypassed the gates.

    This is the assertion that proves the ``except ValueError`` blocks around
    ``vswr_at_target`` and ``impedance_at_target`` are narrow. If someone widens
    one of them, or wraps ``s11_at_target`` in the same ``try``, this fails while
    that edit's own test passes.
    """
    with pytest.raises(ValueError, match=match):
        compute_metrics(
            four_passing_gates(),
            RESONANT_AT_3GHZ,
            provenance_for(),
            intent_at(target_hz),
        )


def test_the_narrow_catch_runs_after_the_shared_precondition_check() -> None:
    """Series-level preconditions raise rather than yielding seven omissions.

    ``s11_at_target`` is called first, on the same three arguments, precisely so
    that any series or target problem surfaces before the two guarded calls run.
    A misaligned series would otherwise reach the guarded calls and be reported
    as two omissions with a precondition message inside them.
    """
    misaligned = solved([1 * GHZ, 2 * GHZ, 3 * GHZ], [0.1, 0.01])
    with pytest.raises(ValueError, match="aligned index-for-index"):
        compute_metrics(
            four_passing_gates(),
            misaligned,
            provenance_for(),
            intent_at(TARGET_2GHZ),
        )


@pytest.mark.parametrize("poison", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_input_sample_propagates_and_names_its_index(
    poison: float,
) -> None:
    """A non-finite INPUT is upstream corruption, not a metric with an infinite value.

    This is what closes the all-omitted case at the input: without it, a
    NaN-poisoned series makes every computed value non-finite, every record gets
    omitted, and the assembler lands on an empty success arm. Rejected at entry
    instead, with the index named so the corruption is locatable.
    """
    corrupt = solved([1 * GHZ, 2 * GHZ, 3 * GHZ], [0.1, poison, 0.1])
    with pytest.raises(ValueError, match="index 1 is not a finite complex number"):
        compute_metrics(
            four_passing_gates(), corrupt, provenance_for(), intent_at(TARGET_2GHZ)
        )


def test_a_non_finite_input_frequency_propagates() -> None:
    """A NaN frequency escapes the strictly-increasing check, so it needs its own.

    Every comparison against NaN is False, so ``NaN <= previous`` never fires and
    the monotonicity loop would wave it straight through. This also underwrites
    ``resonant_frequency``'s guaranteed finiteness, which is what makes the
    all-omitted case unreachable.
    """
    corrupt = solved([1 * GHZ, float("nan"), 3 * GHZ], [0.1, 0.01, 0.1])
    with pytest.raises(ValueError, match="index 1 is not a finite number"):
        compute_metrics(
            four_passing_gates(), corrupt, provenance_for(), intent_at(TARGET_3GHZ)
        )


# --- 4. seam (c): nothing non-finite reaches JSON -----------------------------


def test_a_perfect_match_omits_s11_min_rather_than_serializing_a_null() -> None:
    """-inf is the true answer AND unrepresentable, so it is stated, not stored.

    The ``model_dump_json()`` assertion is the one that matters: omitting the
    record proves nothing on its own, because a stored ``-inf`` would ALSO be
    absent from a naive check while silently becoming ``"value":null`` on the
    wire.
    """
    result = _computed(solved_data=PERFECT_MATCH, intent=intent_at(TARGET_2GHZ))
    assert S11_MIN not in _by_name(result)
    assert "negative infinity" in result.template_text
    assert "RFC 8259" in result.template_text
    assert '"value":null' not in result.model_dump_json()
    assert "null" not in json.dumps(
        [record.value for record in result.metrics]
    )


def test_a_total_reflection_omits_the_vswr_record() -> None:
    # The +inf mirror of the case above. Both are formulas diverging at a
    # physically meaningful boundary; both are omitted for the same reason, and
    # sparams still returns the infinity so the formulas stay honest.
    result = _computed(
        solved_data=TOTAL_REFLECTION_SHORT, intent=intent_at(TARGET_2GHZ)
    )
    assert VSWR_AT_TARGET not in _by_name(result)
    assert "positive infinity" in result.template_text
    assert '"value":null' not in result.model_dump_json()


def test_every_emitted_metric_value_is_finite() -> None:
    """The uniform gate as a property, over every fixture including the poisoned ones.

    Stated once over all fixtures rather than per case, because the gate is
    deliberately one check over every value and not three enumerated special
    cases — ``s11_at_target`` can also yield -inf, an impedance can overflow, and
    a non-finite Z0 would poison both impedance parts.
    """
    for data, intent in (
        (RESONANT_AT_3GHZ, intent_at(TARGET_3GHZ)),
        (RESONANT_AT_6GHZ, intent_at(TARGET_6GHZ)),
        (NEVER_REACHES_10DB, intent_at(TARGET_2GHZ)),
        (PERFECT_MATCH, intent_at(TARGET_2GHZ)),
        (IDEAL_OPEN, intent_at(TARGET_2GHZ)),
        (TOTAL_REFLECTION_SHORT, intent_at(TARGET_2GHZ)),
        (REFLECTION_ABOVE_UNITY, intent_at(TARGET_2GHZ)),
    ):
        result = _computed(solved_data=data, intent=intent)
        for record in result.metrics:
            assert math.isfinite(record.value), (
                f"{record.metric_name} emitted a non-finite value for {data!r}"
            )


def test_a_non_finite_reference_impedance_omits_the_impedance_records() -> None:
    """The case no enumeration of formulas would have caught.

    Z0 comes from provenance and is not validated for finiteness by anything
    upstream, so an infinite Z0 makes both impedance parts infinite while every
    other metric stays perfectly good. The uniform gate handles it without
    knowing it exists.
    """
    result = _computed(
        provenance=provenance_for(reference_impedance=float("inf")),
        intent=intent_at(TARGET_3GHZ),
    )
    names = [record.metric_name for record in result.metrics]
    assert IMPEDANCE_AT_TARGET_RESISTANCE not in names
    assert IMPEDANCE_AT_TARGET_REACTANCE not in names
    assert S11_MIN in names
    assert '"value":null' not in result.model_dump_json()


def test_the_whole_result_round_trips_through_strict_json() -> None:
    """The "would this actually cross MCP" proof.

    ``json.loads`` accepts ``Infinity`` and ``NaN`` by default — they are a Python
    extension, not RFC 8259 — so ``parse_constant`` is wired to reject them. This
    is the assertion that would catch a future change to
    ``ser_json_inf_nan='constants'``, which would emit valid-looking output that
    no conforming JSON parser can read.
    """

    def reject(constant: str) -> object:
        raise AssertionError(f"non-RFC-8259 JSON constant in the payload: {constant}")

    for data, intent in (
        (RESONANT_AT_3GHZ, intent_at(TARGET_3GHZ)),
        (PERFECT_MATCH, intent_at(TARGET_2GHZ)),
        (IDEAL_OPEN, intent_at(TARGET_2GHZ)),
        (REFLECTION_ABOVE_UNITY, intent_at(TARGET_2GHZ)),
    ):
        result = _computed(solved_data=data, intent=intent)
        payload = json.loads(result.model_dump_json(), parse_constant=reject)
        for record in payload["metrics"]:
            assert isinstance(record["value"], float), record
            assert math.isfinite(record["value"]), record


def test_the_refusal_arm_also_round_trips() -> None:
    # The refusal carries Findings, not floats, but it crosses the same boundary
    # and nothing about it should be assumed.
    result = compute_metrics(
        four_gates_with("convergence", "fail"),
        RESONANT_AT_3GHZ,
        provenance_for(),
        intent_at(TARGET_3GHZ),
    )
    assert isinstance(result, MetricsRefused)
    payload = json.loads(result.model_dump_json())
    assert payload["outcome"] == "gates_failed"
    assert len(payload["failing_gates"]) == 1


# --- 5. determinism, provenance, and variation independence -------------------


def test_the_same_inputs_render_byte_identical_text() -> None:
    """Byte-determinism, following W-5 and W-6: no timestamp, no dict iteration.

    ``NEVER_REACHES_10DB`` with no intent is the strongest case: it produces
    omissions from three different code paths (the band check and the no-intent
    branch), so if their order depended on collection order rather than on
    ``METRIC_ORDER``, this would flicker.
    """
    first = _computed(solved_data=NEVER_REACHES_10DB, intent=None)
    second = _computed(solved_data=NEVER_REACHES_10DB, intent=None)
    assert first.template_text == second.template_text
    assert first.model_dump_json() == second.model_dump_json()


def test_omissions_are_rendered_in_canonical_order() -> None:
    # Collected from three different points, reported in one fixed order.
    text = _computed(solved_data=NEVER_REACHES_10DB, intent=None).template_text
    positions = [
        text.index(f"  {name}:")
        for name in (MINUS_10DB_BANDWIDTH, S11_AT_TARGET, VSWR_AT_TARGET)
    ]
    assert positions == sorted(positions)


def test_the_text_carries_no_timestamp() -> None:
    # The instant lives in provenance.solve_timestamp, typed and machine-readable.
    # Echoing it here would make every pair of read-outs differ.
    text = _computed().template_text
    assert "2026-07-17" not in text
    assert "09:30" not in text


def test_two_variations_produce_independently_correct_records() -> None:
    """The Done criterion's variation-awareness, at the RECORD level.

    ``test_sparams.py`` already proves the formulas hold no state between calls.
    What this adds is that each record's provenance carries ITS OWN variation, so
    a value and the variation it belongs to cannot be separated or crossed.
    """
    first = _computed(
        solved_data=RESONANT_AT_3GHZ,
        provenance=provenance_for(
            variation_hash="sha256:aaaa", variation_values={"width": "2.0mm"}
        ),
        intent=intent_at(TARGET_3GHZ),
    )
    second = _computed(
        solved_data=RESONANT_AT_6GHZ,
        provenance=provenance_for(
            variation_hash="sha256:bbbb", variation_values={"width": "3.0mm"}
        ),
        intent=intent_at(TARGET_6GHZ),
    )
    assert all(
        record.provenance.variation.variation_hash == "sha256:aaaa"
        for record in first.metrics
    )
    assert all(
        record.provenance.variation.variation_hash == "sha256:bbbb"
        for record in second.metrics
    )
    # Every metric differs between the two, so no result of one could be mistaken
    # for a result of the other.
    first_values = _by_name(first)
    second_values = _by_name(second)
    for name in METRIC_ORDER:
        if name == IMPEDANCE_AT_TARGET_REACTANCE:
            continue  # exactly 0.0 in both: G is purely real at both targets
        assert first_values[name].value != second_values[name].value, name


def test_a_variation_reruns_identically_after_another_variation() -> None:
    # The state-leak check at the assembler level: running variation 2 in between
    # must not change variation 1's answer.
    provenance = provenance_for(variation_hash="sha256:aaaa")
    before = _computed(solved_data=RESONANT_AT_3GHZ, provenance=provenance)
    _computed(
        solved_data=RESONANT_AT_6GHZ,
        provenance=provenance_for(variation_hash="sha256:bbbb"),
        intent=intent_at(TARGET_6GHZ),
    )
    after = _computed(solved_data=RESONANT_AT_3GHZ, provenance=provenance)
    assert before.model_dump_json() == after.model_dump_json()


def test_the_supplied_reference_impedance_is_the_one_used() -> None:
    # 50 is never assumed, here or in the formula. Doubling Z0 doubles the
    # impedance and leaves every other metric untouched.
    at_50 = _by_name(_computed(provenance=provenance_for(reference_impedance=50.0)))
    at_75 = _by_name(_computed(provenance=provenance_for(reference_impedance=75.0)))
    assert at_75[IMPEDANCE_AT_TARGET_RESISTANCE].value == pytest.approx(
        at_50[IMPEDANCE_AT_TARGET_RESISTANCE].value * 1.5, **EXACT
    )
    assert at_75[S11_MIN].value == at_50[S11_MIN].value


def test_every_record_carries_the_supplied_provenance() -> None:
    provenance = provenance_for(project="patch\nantenna")
    result = _computed(provenance=provenance)
    assert all(record.provenance == provenance for record in result.metrics)


def test_untrusted_names_are_rendered_as_quoted_data() -> None:
    # project/design are UntrustedStr and are framed as data, never in an
    # instruction position (§6.6). The adapter keeps newlines deliberately, so one
    # can genuinely arrive here.
    result = _computed(provenance=provenance_for(project="patch\nantenna"))
    assert 'project "patch\nantenna"' in result.template_text


# --- 6. structure -------------------------------------------------------------


def test_the_assembler_is_not_a_registered_capability() -> None:
    """W-7's entry point is not dispatchable, and must not become so quietly.

    Mirrors the same assertion in the W-5 and W-6 assembly suites. It pins the
    Part 3 scope decision: registering this would put a differently-shaped
    ``compute_metrics`` in the registry and audit an assembly step as a tool
    call. The §3 TOOL of the same name is Step 3.4's, built on top of this.
    """
    from hfss_agent.adapter.fake import FakeAdapter
    from hfss_agent.session import Session

    session = Session(FakeAdapter())
    names = {spec.name for spec in session_routed_specs(session)}
    assert "compute_metrics" not in names
    # And the reads the Step 3.4 tool will need are still unregistered, which is
    # why W-7 could not have dispatched for them even if it wanted to.
    assert "read_solved_data" not in names
    assert "read_solve_state" not in names


def test_metric_order_covers_exactly_the_seven_record_names() -> None:
    # One tuple governs both the record list and the omission ordering, so a name
    # missing from it would raise a ValueError inside _ordered rather than
    # producing subtly misordered output.
    assert len(METRIC_ORDER) == len(set(METRIC_ORDER)) == 7
    assert set(AT_TARGET_METRICS) <= set(METRIC_ORDER)


def test_missing_s11_series_raises_rather_than_returning_an_empty_success() -> None:
    """A non-canonical key is an upstream bug worth surfacing, not a gap to absorb.

    ``export``'s strict key parsing makes the same call for the same reason: the
    canonical ``S(1,1)`` spelling is an unverified assumption about what PyAEDT
    emits, and a tolerant fallback here would absorb the moment it turns out
    wrong, costing the discovery at Phase 5.2 live validation.
    """
    from hfss_agent.contract import ComplexSample, SolvedData

    wrong_key = SolvedData(
        frequencies=[1 * GHZ, 2 * GHZ],
        s_parameters={"S11": [ComplexSample(real=0.1, imag=0.0)] * 2},
    )
    with pytest.raises(MetricsAssemblyError, match="no 'S\\(1,1\\)' series"):
        compute_metrics(
            four_passing_gates(), wrong_key, provenance_for(), intent_at(1.5 * GHZ)
        )


def test_the_assembly_error_is_not_one_of_its_siblings() -> None:
    """Catching one assembler's failure must not catch another's.

    ``export_diagnostics_bundle`` will later compose inspect, validate_native and
    metrics in one operation, and a caller holding all three needs to know which
    assembly failed. A shared base class would let one bare ``except`` swallow the
    wrong one.
    """
    from hfss_agent.inspect import InspectionAssemblyError
    from hfss_agent.validate_native import NativeValidationAssemblyError

    assert not issubclass(MetricsAssemblyError, InspectionAssemblyError)
    assert not issubclass(MetricsAssemblyError, NativeValidationAssemblyError)
    assert not issubclass(InspectionAssemblyError, MetricsAssemblyError)
    assert not issubclass(NativeValidationAssemblyError, MetricsAssemblyError)
