"""W-7 open formulas: the approved Tier 1 S-parameter metric set (§1.1).

Six pure, public, individually referenceable functions over ONE variation's S11
series. "Individually referenceable" is the load-bearing property: each function
has a stable reference string (the ``*_REF`` constants below) that populates
``MetricRecord.formula_ref`` and a ``Finding``'s ``calculation_ref`` — the Axis F
evidence requirement's field 3. A reader handed a metric can follow that string
straight to the function that produced it, which is the whole point of keeping
these formulas open.

ONE VARIATION, EXPLICITLY SUPPLIED — NEVER A SILENT "NOMINAL" (spec Point 9).
These functions hold no state, read no selection, and consult no global: the
caller passes the frequency array and complex S11 array for the one variation it
means, and gets back a value computed from exactly those numbers. There is no
code path by which a second variation's data could reach a result, because there
is nowhere for a first variation's data to live between calls. The variation key
itself never appears here; it travels alongside the value on
``ProvenanceRecord.variation`` when W-7's later wiring builds the MetricRecord.

CONTRACT-ONLY IMPORTS. This file imports ``hfss_agent.contract`` and the standard
library, nothing else — the formulas themselves are pure (§5, Layer 4 note). NO
MODULE UNDER ``metrics/`` FETCHES ``SolvedData`` FROM A LIVE SESSION, including
the assembler beside this file: it takes the series as data from its caller. The
broker dispatch that reads solved data belongs to the ``compute_metrics`` TOOL at
Step 3.4, which sits in the server layer. (An earlier draft of this paragraph
predicted that wiring would land in this step; it did not, for the reason
``assembler.compute_metrics`` documents — a W-7 that fetched its own numbers
while receiving gate results as data could not prove the two describe the same
solve.)

WHAT THIS MODULE DOES NOT DO: decide whether the data is trustworthy enough to
compute on. That is W-9's job, and W-7 refuses to run before the gates pass
(§1.1). In particular, gate (d) — target coverage — is what guarantees a target
frequency lies inside the swept range. The target-range check below therefore
raises a plain ``ValueError`` rather than offering a graceful
``cannot_evaluate``: once gating is wired in, reaching it means a caller skipped
the gates, which is a programming error and should read as one.

REFERENCE IMPEDANCE. Z0 is a parameter of ``impedance_at_target``, not a field
read from the S11 series: the contract carries it on
``ProvenanceRecord.reference_impedance`` (``SolvedData`` has no such field), so
the caller sources it from there and passes it in.

THE RULE FOR EXTREME INPUTS, stated once because all six formulas obey it:
A FORMULA RETURNS THE METRIC'S VALUE WHEREVER ONE EXISTS -- INCLUDING AN INFINITE
ONE, WHEN INFINITY IS THE TRUE LIMITING VALUE -- AND RAISES ``ValueError`` ONLY
WHEN NO VALUE EXISTS AT ALL. The three places it bites:

  * ``s11_min`` on a sample of exactly zero magnitude returns ``-inf``. A
    perfect match IS infinitely deep return loss; -inf is the answer, not the
    absence of one.
  * ``vswr_at_target`` at |G| = 1 returns ``+inf``. Total reflection IS infinite
    standing-wave ratio, and it is the exact mirror of the case above -- both
    are a formula diverging at a physically meaningful boundary. At |G| > 1 it
    RAISES instead: there the expression yields a finite NEGATIVE number, which
    is not a VSWR at all and is not a limit of one.
  * ``impedance_at_target`` at G = 1+0j RAISES. The magnitude diverges but the
    COMPLEX value does not converge -- which phase infinity carries depends on
    the direction of approach -- so there is no complex number, extended or
    otherwise, to return.

A NON-FINITE INPUT IS THE OPPOSITE CASE AND IS REJECTED, NOT RETURNED. All three
bullets above are formulas diverging over SOUND data. A sample or frequency that
arrives already non-finite is not that: it is upstream data corruption, and every
metric derived from it would be meaningless rather than infinite. ``ComplexSample``
accepts NaN and ±inf (pydantic's ``allow_inf_nan`` defaults to True), so nothing
upstream rejects them and the precondition checks below are the first layer that
can. They raise ``ValueError`` naming the offending index, joining the
misaligned-array and non-increasing-frequency checks in the class of failures a
caller must fix rather than report. See ``_require_samples`` for the full
same-symptom-opposite-cause argument.

SERIALIZABILITY IS NOT PART OF THAT RULE, deliberately. Strict JSON carries
neither ``inf`` nor ``-inf``, so "will this serialize" cannot distinguish the
cases above and must not be used to. Deciding how a non-finite value crosses
into a ``MetricRecord`` and out to a file is the assembly layer's problem, and
it is not solved by having the formulas quietly report something finite instead.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from dataclasses import dataclass

from hfss_agent.contract import ComplexSample

# The -10 dB return-loss threshold that defines the bandwidth metric. Compared
# with `<=` against the computed dB value, with no tolerance band: a tolerance
# would be an undeclared judgment about how close counts as crossing, and this
# module states its rules rather than tuning them.
MINUS_10_DB_THRESHOLD_DB = -10.0

# Stable reference strings for the six formulas. Convention: the dotted module
# path, a colon, then the public function name -- matching the shape already
# used across the contract's schema fixtures (e.g.
# "hfss_agent.gating.solution_exists:evaluate"). The SAME string populates
# MetricRecord.formula_ref and Finding.calculation_ref; the two field names
# differ but they point at the same open code.
S11_MIN_REF = "hfss_agent.metrics.sparams:s11_min"
RESONANT_FREQUENCY_REF = "hfss_agent.metrics.sparams:resonant_frequency"
S11_AT_TARGET_REF = "hfss_agent.metrics.sparams:s11_at_target"
MINUS_10DB_BANDWIDTH_REF = "hfss_agent.metrics.sparams:minus_10db_bandwidth"
VSWR_AT_TARGET_REF = "hfss_agent.metrics.sparams:vswr_at_target"
IMPEDANCE_AT_TARGET_REF = "hfss_agent.metrics.sparams:impedance_at_target"

# Function name -> reference string, so a caller building a MetricRecord can look
# the reference up rather than retyping it. Kept in step with the constants above
# by a test that resolves every value back to a real public function here.
FORMULA_REFS: dict[str, str] = {
    "s11_min": S11_MIN_REF,
    "resonant_frequency": RESONANT_FREQUENCY_REF,
    "s11_at_target": S11_AT_TARGET_REF,
    "minus_10db_bandwidth": MINUS_10DB_BANDWIDTH_REF,
    "vswr_at_target": VSWR_AT_TARGET_REF,
    "impedance_at_target": IMPEDANCE_AT_TARGET_REF,
}

NO_BAND_REASON = (
    "the deepest sample in the given sweep does not reach -10 dB, so there is "
    "no contiguous <= -10 dB run around the resonant point"
)


@dataclass(frozen=True)
class Minus10dBBand:
    """A contiguous run of swept samples at or below -10 dB, around resonance.

    The two edges are ACTUAL SWEPT FREQUENCIES, never interpolated ones -- see
    ``minus_10db_bandwidth`` for why, and for what that costs in resolution.

    ``width_hz`` is ``high_frequency_hz - low_frequency_hz``. A width of exactly
    0.0 is a real, if degenerate, answer: it means precisely one swept sample
    reached -10 dB and its neighbours did not. That is NOT the "no band" case,
    which is a different type entirely (``NoMinus10dBBand``) so the two can never
    be confused for one another.
    """

    low_frequency_hz: float
    high_frequency_hz: float
    width_hz: float


@dataclass(frozen=True)
class NoMinus10dBBand:
    """The stated absence of a -10 dB band, with the reason it is absent.

    Returned instead of a ``Minus10dBBand`` when the resonant point itself never
    reaches -10 dB. A separate type rather than ``None`` or a zero width: zero is
    a legitimate ``Minus10dBBand`` width, and ``None`` would carry no reason,
    leaving a caller to invent one when it reports why there is no number.

    It shares no base class with ``Minus10dBBand`` deliberately -- a caller must
    look at which type it got, and cannot read a frequency off this one by
    accident.
    """

    reason: str


def s11_min(s11: Sequence[ComplexSample]) -> float:
    """Global minimum of 20*log10(|S11(f)|), in dB, across the full given sweep.

    Takes no frequency array: the value is a property of the magnitudes alone.
    ``resonant_frequency`` is the function that answers "where", and it is the
    one that needs the frequencies.

    Ties: if several samples share the exact minimum, the value is the same
    number either way, so tie-breaking is only visible through
    ``resonant_frequency`` (which reports the lowest such frequency).

    A sample of exactly zero magnitude -- a perfect match, effectively
    unreachable in measured data -- yields ``-inf`` rather than raising: see the
    module docstring's rule for extreme inputs, of which this is one of the three
    cases. ``vswr_at_target`` at |G| = 1 is the same case mirrored.

    Raises:
        ValueError: if ``s11`` is empty, or any sample is non-finite.
    """
    _require_samples(s11)
    return min(_magnitude_db(_as_complex(sample)) for sample in s11)


def resonant_frequency(
    frequencies: Sequence[float], s11: Sequence[ComplexSample]
) -> float:
    """Frequency in Hz at which ``s11_min``'s global minimum occurs.

    Shares ``_resonance_index`` with ``s11_min``'s underlying scan, so the two
    can never disagree about which sample is the deepest. It remains its own
    public, individually referenceable function with its own reference string:
    a "how deep" claim and a "where" claim are separate claims and must be
    separately traceable.

    Ties: the LOWEST frequency among samples sharing the exact minimum wins.
    Arbitrary but fixed and stated, so the answer is reproducible.

    Raises:
        ValueError: if the series are empty, of unequal length, carry a
            non-finite sample or frequency, or the frequencies are not strictly
            increasing.
    """
    _require_series(frequencies, s11)
    return float(frequencies[_resonance_index(s11)])


def s11_at_target(
    frequencies: Sequence[float],
    s11: Sequence[ComplexSample],
    target_frequency_hz: float,
) -> float:
    """|S11| in dB at ``target_frequency_hz``, by complex-linear interpolation.

    Interpolation is performed on the COMPLEX reflection coefficient between the
    two nearest swept samples, and the magnitude is taken afterwards -- not the
    other way round. Interpolating magnitudes (or dB values) would discard the
    phase relationship between the bracketing samples and read high through a
    resonance, where the real and imaginary parts move in opposite directions.

    The target is assumed to lie inside the swept range; confirming that is W-9
    gate (d)'s job, not this module's. See the module docstring for why an
    out-of-range target is a ``ValueError`` here rather than a graceful outcome.

    Raises:
        ValueError: if the series are empty, of unequal length, carry a
            non-finite sample or frequency, the frequencies are not strictly
            increasing, or the target is outside the swept range.
    """
    return _magnitude_db(_interpolated_gamma(frequencies, s11, target_frequency_hz))


def minus_10db_bandwidth(
    frequencies: Sequence[float], s11: Sequence[ComplexSample]
) -> Minus10dBBand | NoMinus10dBBand:
    """The contiguous <= -10 dB run of swept samples around the resonant point.

    ACTUAL SAMPLE POINTS ONLY -- no interpolation is performed, so the returned
    edges are frequencies HFSS actually swept. THE CONSEQUENCE IS THAT
    BANDWIDTH RESOLUTION IS BOUNDED BY THE SWEEP'S FREQUENCY STEP SIZE: the true
    -10 dB crossing lies somewhere between the last in-band sample and its
    out-of-band neighbour, so a coarse sweep reports a coarse bandwidth. This is
    a deliberate trade -- an interpolated edge would be a computed frequency
    presented next to two measured ones, and a caller could not tell which was
    which.

    Starts at the resonant sample and walks outward in both directions while
    samples stay at or below -10 dB, stopping at the first sample that does not.
    A separate deep dip elsewhere in the sweep is therefore excluded: this metric
    describes the band around resonance, not the total swept extent below -10 dB.

    Returns:
        ``Minus10dBBand`` with the two edge frequencies and their difference, or
        ``NoMinus10dBBand`` if the resonant sample itself never reaches -10 dB.
        Never a zero-width stand-in for "no band" and never an exception for it.

    Raises:
        ValueError: if the series are empty, of unequal length, carry a
            non-finite sample or frequency, or the frequencies are not strictly
            increasing.
    """
    _require_series(frequencies, s11)
    decibels = [_magnitude_db(_as_complex(sample)) for sample in s11]
    resonance = _resonance_index(s11)

    # The deepest point of the sweep is by definition the most likely to be in
    # band; if it is not, nothing else can be, and there is no band to walk.
    if decibels[resonance] > MINUS_10_DB_THRESHOLD_DB:
        return NoMinus10dBBand(reason=NO_BAND_REASON)

    low_index = resonance
    while low_index > 0 and decibels[low_index - 1] <= MINUS_10_DB_THRESHOLD_DB:
        low_index -= 1

    high_index = resonance
    last = len(decibels) - 1
    while high_index < last and decibels[high_index + 1] <= MINUS_10_DB_THRESHOLD_DB:
        high_index += 1

    low_frequency = float(frequencies[low_index])
    high_frequency = float(frequencies[high_index])
    return Minus10dBBand(
        low_frequency_hz=low_frequency,
        high_frequency_hz=high_frequency,
        width_hz=high_frequency - low_frequency,
    )


def vswr_at_target(
    frequencies: Sequence[float],
    s11: Sequence[ComplexSample],
    target_frequency_hz: float,
) -> float:
    """VSWR at ``target_frequency_hz``: (1 + |G|) / (1 - |G|).

    G is the SAME complex-interpolated reflection coefficient
    ``s11_at_target`` uses, and |G| is its LINEAR magnitude, not its value in dB.
    Sharing the interpolation means the VSWR and the S11 reported for one target
    frequency always describe the same interpolated point.

    At |G| = 1 -- total reflection, as an unsolved or shorted port can genuinely
    produce -- this returns ``+inf``. That is the true limiting value and the
    standard engineering statement, and it is the same case as ``s11_min``
    returning ``-inf`` for a perfect match: see the module docstring's rule for
    extreme inputs. Raising there would make a real physical answer read like a
    defect.

    Raises:
        ValueError: on the series/target problems ``s11_at_target`` raises for,
            and additionally when |G| > 1. Above 1 the expression yields a finite
            NEGATIVE number, which is not a VSWR and is not a limit of one; a
            passive one-port cannot reflect more than it was given. There is no
            value to return, infinite or otherwise, so the caller is told.
    """
    reflection_magnitude = abs(
        _interpolated_gamma(frequencies, s11, target_frequency_hz)
    )
    if reflection_magnitude > 1.0:
        raise ValueError(
            "VSWR is undefined for a reflection coefficient magnitude of "
            f"{reflection_magnitude!r} (> 1, non-physical for a passive "
            f"one-port) at {target_frequency_hz!r} Hz"
        )
    if reflection_magnitude == 1.0:
        return math.inf
    return (1.0 + reflection_magnitude) / (1.0 - reflection_magnitude)


def impedance_at_target(
    frequencies: Sequence[float],
    s11: Sequence[ComplexSample],
    target_frequency_hz: float,
    reference_impedance: float,
) -> complex:
    """Complex input impedance at ``target_frequency_hz``: Z0 * (1 + G)/(1 - G).

    G is the same complex-interpolated reflection coefficient the two other
    at-target formulas use, kept COMPLEX here (magnitude alone cannot give a
    reactance).

    ``reference_impedance`` is Z0, in ohms. It is a parameter because the
    contract carries it on ``ProvenanceRecord.reference_impedance`` and nowhere
    on the S11 series itself -- the caller reads it from the provenance it is
    already building for the metric and passes it in. Nothing is assumed about
    it here, and in particular 50 is not defaulted: a silently assumed Z0 would
    put an unverified number inside a reported impedance.

    Returns:
        The complex impedance in ohms. Splitting it into the real and reactive
        parts a ``MetricRecord`` can carry (its ``value`` is a single float) is
        the caller's job, not the formula's.

    Raises:
        ValueError: on the series/target problems ``s11_at_target`` raises for,
            and additionally when G is exactly 1+0j -- an ideal open circuit. The
            magnitude diverges there, but unlike ``vswr_at_target``'s |G| = 1
            case this cannot return an infinity: the COMPLEX value has no limit,
            because which phase it carries depends on the direction of approach.
            See the module docstring's rule for extreme inputs.
    """
    gamma = _interpolated_gamma(frequencies, s11, target_frequency_hz)
    denominator = 1.0 - gamma
    if denominator == 0:
        raise ValueError(
            "impedance is unbounded for a reflection coefficient of exactly "
            f"1+0j at {target_frequency_hz!r} Hz"
        )
    return reference_impedance * (1.0 + gamma) / denominator


# --- private helpers ---------------------------------------------------------
# These are deliberately private: only the six public functions above carry
# reference strings, so only they may be cited as the origin of a reported value.


def _as_complex(sample: ComplexSample) -> complex:
    """The contract's JSON-safe real/imag pair as a Python ``complex``.

    The snapshot cannot carry ``complex`` (it is not JSON-serializable), so the
    conversion happens here, once, at the point the arithmetic starts.
    """
    return complex(sample.real, sample.imag)


def _magnitude_db(gamma: complex) -> float:
    """20*log10(|G|), with an exactly-zero magnitude reported as ``-inf``.

    ``math.log10(0.0)`` raises, so the guard is needed to get the answer the
    module's rule for extreme inputs calls for: negative infinity is the true
    limiting value, and returning it keeps a perfect-match sample honest instead
    of turning it into an exception the caller would have to invent a story for.
    """
    magnitude = abs(gamma)
    if magnitude == 0.0:
        return -math.inf
    return 20.0 * math.log10(magnitude)


def _require_samples(s11: Sequence[ComplexSample]) -> None:
    """Reject an empty S11 series, and any sample that is not a finite number.

    There is no minimum of nothing, and no meaningful metric over a NaN.

    A NON-FINITE INPUT PROPAGATES AS ``ValueError``; A NON-FINITE COMPUTED VALUE
    DOES NOT. Same symptom, opposite causes, so deliberately opposite handling:

      * a non-finite INPUT sample is upstream data corruption -- the solver, the
        adapter, or a de-embedding step produced something that is not a
        measurement. Every metric derived from it would be meaningless, so this
        is worth surfacing loudly at the point of entry, with the index named.
      * a non-finite COMPUTED value (``s11_min`` at |G| = 0, ``vswr_at_target``
        at |G| = 1) is a real mathematical limit of a real formula over sound
        data. The module's rule for extreme inputs says that IS the answer, so
        it is returned, and the assembler reports it as a stated omission rather
        than a failure.

    Collapsing the two would lose the distinction in whichever direction it was
    collapsed: reject both and a perfect match becomes an error; return both and
    corrupt data silently becomes seven "infinite" metrics.

    ``ComplexSample`` accepts NaN and ±inf on ``real``/``imag`` (pydantic's
    ``allow_inf_nan`` defaults to True), so nothing upstream of here rejects
    them and this is the first layer that can.
    """
    if len(s11) == 0:
        raise ValueError("S11 series is empty; no metric can be computed from it")
    for index, sample in enumerate(s11):
        if not (math.isfinite(sample.real) and math.isfinite(sample.imag)):
            raise ValueError(
                f"S11 sample at index {index} is not a finite complex number "
                f"(real={sample.real!r}, imag={sample.imag!r}); a non-finite "
                "INPUT sample is upstream data corruption, not a metric with an "
                "infinite value, so it is refused rather than computed on"
            )


def _require_series(frequencies: Sequence[float], s11: Sequence[ComplexSample]) -> None:
    """Reject series that cannot support a well-defined frequency-domain read.

    Strictly increasing frequencies are required, not merely sorted: the
    bracketing search and the contiguity walk both assume each sample sits at its
    own distinct frequency, and a duplicated frequency would make "the two
    nearest samples" ambiguous and a zero-width interpolation interval possible.
    """
    _require_samples(s11)
    if len(frequencies) != len(s11):
        raise ValueError(
            f"frequency array ({len(frequencies)}) and S11 array ({len(s11)}) "
            "must be aligned index-for-index"
        )
    # FINITENESS BEFORE MONOTONICITY, AND THE ORDER IS LOAD-BEARING. Every
    # comparison against a NaN is False, so `frequencies[i] <= frequencies[i-1]`
    # does not fire for a NaN and the loop below would wave it straight through;
    # an infinite frequency passes that loop too, since inf exceeds whatever
    # preceded it. Checking finiteness first is what makes the monotonicity check
    # meaningful rather than merely true. It also underwrites the assembler's
    # guarantee that `resonant_frequency` -- a verbatim copy of one of these
    # numbers -- can never itself be non-finite.
    for index, frequency in enumerate(frequencies):
        if not math.isfinite(frequency):
            raise ValueError(
                f"frequency at index {index} is not a finite number "
                f"({frequency!r}); a non-finite INPUT frequency is upstream data "
                "corruption, so it is refused rather than computed on"
            )
    for index in range(1, len(frequencies)):
        if frequencies[index] <= frequencies[index - 1]:
            raise ValueError(
                "frequencies must be strictly increasing; "
                f"index {index} ({frequencies[index]!r}) does not exceed "
                f"index {index - 1} ({frequencies[index - 1]!r})"
            )


def _resonance_index(s11: Sequence[ComplexSample]) -> int:
    """Index of the deepest sample; the lowest index wins an exact tie.

    The shared root of ``s11_min`` and ``resonant_frequency`` -- one scan, so the
    depth and the frequency can never be reported off different samples.
    """
    deepest_index = 0
    deepest_db = _magnitude_db(_as_complex(s11[0]))
    for index in range(1, len(s11)):
        candidate = _magnitude_db(_as_complex(s11[index]))
        # Strict `<`: an equal value leaves the earlier (lower-frequency) index
        # in place, which is the stated tie-break.
        if candidate < deepest_db:
            deepest_db = candidate
            deepest_index = index
    return deepest_index


def _interpolated_gamma(
    frequencies: Sequence[float],
    s11: Sequence[ComplexSample],
    target_frequency_hz: float,
) -> complex:
    """Complex S11 at ``target_frequency_hz``, linearly between its two brackets.

    The single interpolation used by all three at-target formulas, so they can
    never describe different points. Returns the sample verbatim when the target
    lands exactly on one.
    """
    _require_series(frequencies, s11)
    lowest = frequencies[0]
    highest = frequencies[-1]
    if not lowest <= target_frequency_hz <= highest:
        raise ValueError(
            f"target frequency {target_frequency_hz!r} Hz is outside the swept "
            f"range [{lowest!r}, {highest!r}] Hz; W-9 gate (d) is what keeps "
            "this unreachable, so reaching it means the gates were skipped"
        )

    # First index whose frequency is >= the target. Bounded by the range check
    # above, so it always exists.
    index = bisect.bisect_left(frequencies, target_frequency_hz)
    if frequencies[index] == target_frequency_hz:
        return _as_complex(s11[index])

    # Not an exact hit and not below the first sample, so index >= 1 and the
    # target sits strictly inside (frequencies[index - 1], frequencies[index]).
    lower_frequency = frequencies[index - 1]
    upper_frequency = frequencies[index]
    lower_gamma = _as_complex(s11[index - 1])
    upper_gamma = _as_complex(s11[index])
    weight = (target_frequency_hz - lower_frequency) / (
        upper_frequency - lower_frequency
    )
    return lower_gamma + (upper_gamma - lower_gamma) * weight
