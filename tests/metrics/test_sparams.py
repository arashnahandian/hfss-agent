"""W-7's six open formulas — values, refusals, and variation independence.

Every expected number below is either an exact integer in dB (the fixtures use
power-of-ten magnitudes deliberately, see ``sparams_helpers``) or written as the
arithmetic that produces it, so a reader can check the assertion against the
stated formula rather than against a number someone once observed.

Three properties carry most of the weight and each has its own section:
interpolation happens on the COMPLEX value and not on the magnitude; the -10 dB
band is walked over actual samples and stops at the first sample that leaves the
band; and two variations run through these functions cannot reach each other,
because there is no state between calls for them to reach through.
"""

from __future__ import annotations

import math

import pytest
from sparams_helpers import (
    BAND_EDGES,
    COMPLEX_SEGMENT,
    DISCONNECTED_DIP,
    GHZ,
    NEVER_REACHES_10DB,
    PERFECT_MATCH,
    RESONANT_AT_3GHZ,
    RESONANT_AT_6GHZ,
    SINGLE_SAMPLE,
    Z0,
    series,
)

from hfss_agent.metrics import sparams
from hfss_agent.metrics.sparams import (
    FORMULA_REFS,
    NO_BAND_REASON,
    Minus10dBBand,
    NoMinus10dBBand,
    impedance_at_target,
    minus_10db_bandwidth,
    resonant_frequency,
    s11_at_target,
    s11_min,
    vswr_at_target,
)

# Tight enough that a wrong formula cannot hide inside the tolerance, loose
# enough to absorb the last bit or two of floating-point rounding.
EXACT = {"rel": 1e-12, "abs": 1e-12}


# --- the six formulas on one hand-checkable fixture ---------------------------
# RESONANT_AT_3GHZ is [0, -20, -40, -20, 0] dB at 1..5 GHz.


def test_s11_min_is_the_deepest_sample_in_db() -> None:
    # 20*log10(0.01) = 20 * -2 = -40.
    assert s11_min(RESONANT_AT_3GHZ.s11) == pytest.approx(-40.0, **EXACT)


def test_resonant_frequency_is_where_that_minimum_sits() -> None:
    frequency = resonant_frequency(
        RESONANT_AT_3GHZ.frequencies, RESONANT_AT_3GHZ.s11
    )
    assert frequency == 3 * GHZ


def test_s11_at_target_on_a_swept_sample_returns_that_sample() -> None:
    # The target lands exactly on the 3 GHz sample, so no interpolation applies
    # and the answer is that sample's own -40 dB.
    decibels = s11_at_target(
        RESONANT_AT_3GHZ.frequencies, RESONANT_AT_3GHZ.s11, 3 * GHZ
    )
    assert decibels == pytest.approx(-40.0, **EXACT)


def test_s11_at_target_between_samples_interpolates_the_complex_value() -> None:
    # 2.5 GHz is the midpoint of the 2 GHz (0.1) and 3 GHz (0.01) samples, so
    # G = 0.1 + (0.01 - 0.1) * 0.5 = 0.055, and the answer is 20*log10(0.055).
    decibels = s11_at_target(
        RESONANT_AT_3GHZ.frequencies, RESONANT_AT_3GHZ.s11, 2.5 * GHZ
    )
    assert decibels == pytest.approx(20.0 * math.log10(0.055), **EXACT)


def test_minus_10db_bandwidth_spans_the_contiguous_run() -> None:
    # Walking out from the -40 dB sample at 3 GHz: the -20 dB neighbours at 2
    # and 4 GHz are in band, the 0 dB samples at 1 and 5 GHz are not.
    band = minus_10db_bandwidth(RESONANT_AT_3GHZ.frequencies, RESONANT_AT_3GHZ.s11)
    assert band == Minus10dBBand(
        low_frequency_hz=2 * GHZ, high_frequency_hz=4 * GHZ, width_hz=2 * GHZ
    )


def test_vswr_at_target_follows_from_the_interpolated_magnitude() -> None:
    # G = 0.055 (real), so VSWR = 1.055 / 0.945 = 211/189.
    vswr = vswr_at_target(
        RESONANT_AT_3GHZ.frequencies, RESONANT_AT_3GHZ.s11, 2.5 * GHZ
    )
    assert vswr == pytest.approx(211.0 / 189.0, **EXACT)


def test_impedance_at_target_uses_the_supplied_reference_impedance() -> None:
    # G = 0.055 (real), so Z = 50 * 1.055 / 0.945 = 10550/189 ohms, purely real.
    # For a real, positive G this equals Z0 * VSWR, which the second assertion
    # cross-checks against the other formula.
    impedance = impedance_at_target(
        RESONANT_AT_3GHZ.frequencies, RESONANT_AT_3GHZ.s11, 2.5 * GHZ, Z0
    )
    assert impedance.real == pytest.approx(10550.0 / 189.0, **EXACT)
    assert impedance.imag == pytest.approx(0.0, abs=1e-12)
    assert impedance.real == pytest.approx(
        Z0 * vswr_at_target(
            RESONANT_AT_3GHZ.frequencies, RESONANT_AT_3GHZ.s11, 2.5 * GHZ
        ),
        **EXACT,
    )


def test_a_different_reference_impedance_gives_a_different_impedance() -> None:
    # Z0 is a parameter, never an assumed 50: doubling it doubles the answer.
    at_50 = impedance_at_target(
        RESONANT_AT_3GHZ.frequencies, RESONANT_AT_3GHZ.s11, 2.5 * GHZ, 50.0
    )
    at_100 = impedance_at_target(
        RESONANT_AT_3GHZ.frequencies, RESONANT_AT_3GHZ.s11, 2.5 * GHZ, 100.0
    )
    assert at_100.real == pytest.approx(2.0 * at_50.real, **EXACT)


# --- complex-linear interpolation, not magnitude-linear -----------------------
# COMPLEX_SEGMENT is 0.6+0j at 1 GHz and 0+0.6j at 2 GHz: equal magnitudes, 90
# degrees apart. Midpoint G = 0.3+0.3j, |G| = sqrt(0.18).


def test_interpolation_is_complex_linear_not_magnitude_linear() -> None:
    decibels = s11_at_target(
        COMPLEX_SEGMENT.frequencies, COMPLEX_SEGMENT.s11, 1.5 * GHZ
    )
    # |G|^2 = 0.3^2 + 0.3^2 = 0.18, so the answer is 10*log10(0.18).
    assert decibels == pytest.approx(10.0 * math.log10(0.18), **EXACT)
    # Interpolating the magnitudes instead would have held |G| at 0.6 through
    # the whole segment. It differs by more than 3 dB, so this is not a
    # tolerance question.
    magnitude_linear = 20.0 * math.log10(0.6)
    assert decibels < magnitude_linear - 3.0


def test_vswr_and_impedance_read_the_same_interpolated_point() -> None:
    reflection = math.sqrt(0.18)
    vswr = vswr_at_target(
        COMPLEX_SEGMENT.frequencies, COMPLEX_SEGMENT.s11, 1.5 * GHZ
    )
    assert vswr == pytest.approx(
        (1.0 + reflection) / (1.0 - reflection), **EXACT
    )
    # Z = 50 * (1 + 0.3 + 0.3j) / (1 - 0.3 - 0.3j) = 50 * (0.82 + 0.60j) / 0.58
    #   = (41 + 30j) / 0.58 = 2050/29 + (1500/29)j.
    impedance = impedance_at_target(
        COMPLEX_SEGMENT.frequencies, COMPLEX_SEGMENT.s11, 1.5 * GHZ, Z0
    )
    assert impedance.real == pytest.approx(2050.0 / 29.0, **EXACT)
    assert impedance.imag == pytest.approx(1500.0 / 29.0, **EXACT)


# --- what the -10 dB band does and does not include ---------------------------


def test_no_band_when_resonance_never_reaches_minus_10db() -> None:
    # Deepest sample is 20*log10(0.5) = -6.02 dB, which does not cross -10 dB.
    result = minus_10db_bandwidth(
        NEVER_REACHES_10DB.frequencies, NEVER_REACHES_10DB.s11
    )
    assert isinstance(result, NoMinus10dBBand)
    assert result.reason == NO_BAND_REASON
    # Emphatically not the two shapes that would be easy to mistake for it.
    assert not isinstance(result, Minus10dBBand)
    assert result is not None


def test_band_edges_include_minus_10_1_db_and_exclude_minus_9_9_db() -> None:
    # The threshold is compared with <= and no tolerance, so a sample at
    # -10.1 dB is in band and one at -9.9 dB is not.
    band = minus_10db_bandwidth(BAND_EDGES.frequencies, BAND_EDGES.s11)
    assert band == Minus10dBBand(
        low_frequency_hz=2 * GHZ, high_frequency_hz=4 * GHZ, width_hz=2 * GHZ
    )


def test_a_disconnected_dip_elsewhere_is_not_counted() -> None:
    # A separate -20 dB dip at 2 GHz sits below the threshold but is cut off
    # from resonance by the 0 dB sample at 3 GHz, so the band is 4..6 GHz only.
    band = minus_10db_bandwidth(DISCONNECTED_DIP.frequencies, DISCONNECTED_DIP.s11)
    assert band == Minus10dBBand(
        low_frequency_hz=4 * GHZ, high_frequency_hz=6 * GHZ, width_hz=2 * GHZ
    )


def test_a_single_in_band_sample_is_a_zero_width_band_not_a_missing_one() -> None:
    band = minus_10db_bandwidth(SINGLE_SAMPLE.frequencies, SINGLE_SAMPLE.s11)
    assert isinstance(band, Minus10dBBand)
    assert band.width_hz == 0.0
    assert band.low_frequency_hz == band.high_frequency_hz == 1 * GHZ


# --- variation independence ---------------------------------------------------
# RESONANT_AT_3GHZ and RESONANT_AT_6GHZ share no frequency grid and no metric
# value, so a leak in either direction would be visible in every assertion.


def _all_six(data, target_hz: float) -> dict[str, object]:
    """Every formula run over one variation's data, at one target frequency."""
    return {
        "s11_min": s11_min(data.s11),
        "resonant_frequency": resonant_frequency(data.frequencies, data.s11),
        "s11_at_target": s11_at_target(data.frequencies, data.s11, target_hz),
        "minus_10db_bandwidth": minus_10db_bandwidth(data.frequencies, data.s11),
        "vswr_at_target": vswr_at_target(data.frequencies, data.s11, target_hz),
        "impedance_at_target": impedance_at_target(
            data.frequencies, data.s11, target_hz, Z0
        ),
    }


def test_two_variations_produce_independently_correct_results() -> None:
    first = _all_six(RESONANT_AT_3GHZ, 2.5 * GHZ)
    second = _all_six(RESONANT_AT_6GHZ, 5.0 * GHZ)

    # Variation 1: [0, -20, -40, -20, 0] dB at 1..5 GHz, G(2.5 GHz) = 0.055.
    assert first["s11_min"] == pytest.approx(-40.0, **EXACT)
    assert first["resonant_frequency"] == 3 * GHZ
    assert first["s11_at_target"] == pytest.approx(
        20.0 * math.log10(0.055), **EXACT
    )
    assert first["minus_10db_bandwidth"] == Minus10dBBand(
        low_frequency_hz=2 * GHZ, high_frequency_hz=4 * GHZ, width_hz=2 * GHZ
    )
    assert first["vswr_at_target"] == pytest.approx(211.0 / 189.0, **EXACT)
    assert first["impedance_at_target"].real == pytest.approx(
        10550.0 / 189.0, **EXACT
    )

    # Variation 2: [0, -20, -60, -20] dB at 2, 4, 6, 8 GHz. 5 GHz is the
    # midpoint of the 4 GHz (0.1) and 6 GHz (0.001) samples, so
    # G = 0.1 + (0.001 - 0.1) * 0.5 = 0.0505 and VSWR = 1.0505/0.9495.
    assert second["s11_min"] == pytest.approx(-60.0, **EXACT)
    assert second["resonant_frequency"] == 6 * GHZ
    assert second["s11_at_target"] == pytest.approx(
        20.0 * math.log10(0.0505), **EXACT
    )
    assert second["minus_10db_bandwidth"] == Minus10dBBand(
        low_frequency_hz=4 * GHZ, high_frequency_hz=8 * GHZ, width_hz=4 * GHZ
    )
    assert second["vswr_at_target"] == pytest.approx(
        1.0505 / 0.9495, **EXACT
    )
    assert second["impedance_at_target"].real == pytest.approx(
        Z0 * 1.0505 / 0.9495, **EXACT
    )

    # No pair of corresponding results coincides, so nothing was overwritten.
    for name in first:
        assert first[name] != second[name], name


def test_a_variation_reruns_identically_after_another_variation() -> None:
    # The formulas hold no state, so interleaving cannot perturb them.
    before = _all_six(RESONANT_AT_3GHZ, 2.5 * GHZ)
    _all_six(RESONANT_AT_6GHZ, 5.0 * GHZ)
    after = _all_six(RESONANT_AT_3GHZ, 2.5 * GHZ)
    assert before == after


# --- refusals -----------------------------------------------------------------


@pytest.mark.parametrize("target_hz", [0.5 * GHZ, 5.5 * GHZ])
def test_a_target_outside_the_swept_range_raises(target_hz: float) -> None:
    # Unreachable once W-9 gate (d) is wired in; a plain ValueError, because
    # reaching it means the gates were skipped.
    with pytest.raises(ValueError, match="outside the swept range"):
        s11_at_target(RESONANT_AT_3GHZ.frequencies, RESONANT_AT_3GHZ.s11, target_hz)


def test_vswr_refuses_a_reflection_greater_than_unity() -> None:
    # |G| > 1 is non-physical for a passive one-port, and the expression there
    # yields a finite NEGATIVE number that is not a VSWR and not a limit of one.
    hot = series([1 * GHZ, 2 * GHZ], [1.5, 1.5])
    with pytest.raises(ValueError, match="VSWR is undefined"):
        vswr_at_target(hot.frequencies, hot.s11, 1.5 * GHZ)


def test_impedance_refuses_an_ideal_open() -> None:
    # G = 1+0j at the 1 GHz sample, where (1 - G) is zero.
    with pytest.raises(ValueError, match="impedance is unbounded"):
        impedance_at_target(
            RESONANT_AT_3GHZ.frequencies, RESONANT_AT_3GHZ.s11, 1 * GHZ, Z0
        )


def test_an_empty_series_raises() -> None:
    empty = series([], [])
    with pytest.raises(ValueError, match="empty"):
        s11_min(empty.s11)
    with pytest.raises(ValueError, match="empty"):
        resonant_frequency(empty.frequencies, empty.s11)
    with pytest.raises(ValueError, match="empty"):
        minus_10db_bandwidth(empty.frequencies, empty.s11)


def test_misaligned_series_raise() -> None:
    # Three frequencies, two samples: "the S11 at this frequency" has no answer
    # for the third, and guessing which one to drop is not this module's call.
    misaligned = series([1 * GHZ, 2 * GHZ, 3 * GHZ], [0.1, 0.01])
    with pytest.raises(ValueError, match="aligned index-for-index"):
        resonant_frequency(misaligned.frequencies, misaligned.s11)


@pytest.mark.parametrize(
    "frequencies",
    [
        [2 * GHZ, 1 * GHZ, 3 * GHZ],  # out of order
        [1 * GHZ, 2 * GHZ, 2 * GHZ],  # duplicated
    ],
)
def test_non_increasing_frequencies_raise(frequencies: list[float]) -> None:
    data = series(frequencies, [1.0, 0.01, 1.0])
    with pytest.raises(ValueError, match="strictly increasing"):
        resonant_frequency(data.frequencies, data.s11)


@pytest.mark.parametrize("poison", [math.nan, math.inf, -math.inf])
def test_a_non_finite_sample_raises_and_names_its_index(poison: float) -> None:
    """A non-finite INPUT is refused; a non-finite COMPUTED value is returned.

    Same symptom, opposite causes, so deliberately opposite handling — see
    ``_require_samples``. A sample that arrives as NaN is upstream data
    corruption and every metric derived from it would be meaningless, whereas
    ``s11_min`` returning ``-inf`` for a perfect match is a real limiting value.
    Collapsing the two in either direction loses something: reject both and a
    perfect match becomes an error; return both and corrupt data silently becomes
    seven "infinite" metrics.
    """
    corrupt = series([1 * GHZ, 2 * GHZ, 3 * GHZ], [0.1, complex(poison, 0.0), 0.1])
    with pytest.raises(ValueError, match="index 1 is not a finite complex number"):
        s11_min(corrupt.s11)
    with pytest.raises(ValueError, match="index 1 is not a finite complex number"):
        resonant_frequency(corrupt.frequencies, corrupt.s11)


def test_a_non_finite_imaginary_part_is_caught_too() -> None:
    # The check reads both parts; a corrupt reactance is as fatal as a corrupt
    # resistance and neither is more likely than the other.
    corrupt = series([1 * GHZ, 2 * GHZ], [0.1, complex(0.0, math.nan)])
    with pytest.raises(ValueError, match="index 1 is not a finite complex number"):
        minus_10db_bandwidth(corrupt.frequencies, corrupt.s11)


@pytest.mark.parametrize("poison", [math.nan, math.inf])
def test_a_non_finite_frequency_raises_and_names_its_index(poison: float) -> None:
    """The NaN frequency the monotonicity check cannot see.

    Every comparison against NaN is False, so ``NaN <= previous`` never fires and
    a NaN frequency would pass the strictly-increasing loop untouched; an
    infinite frequency passes it too, since inf exceeds whatever preceded it.
    That is why finiteness is checked FIRST and separately.
    """
    corrupt = series([1 * GHZ, poison, 3 * GHZ], [0.1, 0.01, 0.1])
    with pytest.raises(ValueError, match="index 1 is not a finite number"):
        resonant_frequency(corrupt.frequencies, corrupt.s11)


def test_the_monotonicity_check_alone_would_not_have_caught_a_nan() -> None:
    # Asserting the reason the two checks are separate, so a later edit cannot
    # merge them on the assumption that one implies the other.
    assert not (math.nan <= 1.0)
    assert not (1.0 <= math.nan)
    assert math.inf > 1e9


# --- honest edges -------------------------------------------------------------


def test_a_perfect_match_reports_negative_infinity_rather_than_raising() -> None:
    # 20*log10(0) is -inf; reporting anything else would be a fabrication.
    assert s11_min(PERFECT_MATCH.s11) == -math.inf
    assert resonant_frequency(PERFECT_MATCH.frequencies, PERFECT_MATCH.s11) == 2 * GHZ


def test_a_total_reflection_reports_positive_infinity_rather_than_raising() -> None:
    # |G| = 1.0 at the 1 GHz sample. The exact mirror of the case above, and the
    # two must agree: both are a formula diverging at a physically meaningful
    # boundary, so both return the limit rather than refusing.
    assert (
        vswr_at_target(RESONANT_AT_3GHZ.frequencies, RESONANT_AT_3GHZ.s11, 1 * GHZ)
        == math.inf
    )


def test_the_two_divergent_boundaries_are_handled_the_same_way() -> None:
    """The consistency this pair of rules exists to guarantee, asserted directly.

    A perfect match (|G| = 0, infinitely deep return loss) and a total reflection
    (|G| = 1, infinite standing-wave ratio) are the same situation seen from the
    two ends of the scale. If a later edit makes one of them raise, this fails
    even if that edit's own test passes.
    """
    perfect_match = s11_min(PERFECT_MATCH.s11)
    total_reflection = vswr_at_target(
        RESONANT_AT_3GHZ.frequencies, RESONANT_AT_3GHZ.s11, 1 * GHZ
    )
    assert math.isinf(perfect_match) and math.isinf(total_reflection)
    # Neither is finite, and neither is a NaN standing in for "no answer".
    assert not math.isnan(perfect_match) and not math.isnan(total_reflection)


def test_a_tie_at_the_minimum_reports_the_lowest_frequency() -> None:
    # Two samples at exactly -40 dB; the stated tie-break takes the first.
    tied = series([1 * GHZ, 2 * GHZ, 3 * GHZ], [0.01, 0.01, 1.0])
    assert resonant_frequency(tied.frequencies, tied.s11) == 1 * GHZ
    # The band still walks outward from that sample and picks up its twin.
    assert minus_10db_bandwidth(tied.frequencies, tied.s11) == Minus10dBBand(
        low_frequency_hz=1 * GHZ, high_frequency_hz=2 * GHZ, width_hz=1 * GHZ
    )


# --- the reference strings ----------------------------------------------------


def test_every_formula_ref_resolves_to_a_public_function_here() -> None:
    # The whole point of the reference string is that a reader can follow it to
    # the code. This fails the moment a function is renamed without its ref.
    for name, reference in FORMULA_REFS.items():
        assert reference == f"hfss_agent.metrics.sparams:{name}"
        assert callable(getattr(sparams, name))


def test_formula_refs_covers_exactly_the_six_approved_metrics() -> None:
    assert set(FORMULA_REFS) == {
        "s11_min",
        "resonant_frequency",
        "s11_at_target",
        "minus_10db_bandwidth",
        "vswr_at_target",
        "impedance_at_target",
    }
