"""Hand-checkable synthetic S11 fixtures for the W-7 formula tests.

Every magnitude here is a power of ten, so its value in dB is an exact integer
that can be read off without a calculator: 1.0 -> 0 dB, 0.1 -> -20 dB,
0.01 -> -40 dB, 0.001 -> -60 dB. The three fixtures that need non-round values
(``NEVER_REACHES_10DB``, ``BAND_EDGES``, ``COMPLEX_SEGMENT``) each state the
arithmetic that produces their expected answers in a comment above them.

These are synthetic curves, not physical antenna responses -- they are shaped to
make each formula's behaviour checkable in isolation, and none of them is meant
to resemble a real S11 sweep.
"""

from __future__ import annotations

from dataclasses import dataclass

from hfss_agent.contract import ComplexSample

GHZ = 1.0e9

# The reference impedance the at-target tests pass in. Sourced by a real caller
# from ProvenanceRecord.reference_impedance; there is no default in the formulas.
Z0 = 50.0


@dataclass(frozen=True)
class Series:
    """One variation's S11 data: the two arrays the formulas take, together.

    Bundled only so a test can hand both to a formula in one go. The formulas
    themselves take the two arrays separately and know nothing about this type.
    """

    frequencies: list[float]
    s11: list[ComplexSample]


def series(frequencies: list[float], values: list[complex | float]) -> Series:
    """Build a ``Series`` from plain frequencies and plain complex/real values."""
    return Series(
        frequencies=list(frequencies),
        s11=[
            ComplexSample(real=complex(value).real, imag=complex(value).imag)
            for value in values
        ],
    )


# dB: [0, -20, -40, -20, 0]. Resonance at 3 GHz, -10 dB band 2..4 GHz (2 GHz
# wide). "Variation 1" for the independence test.
RESONANT_AT_3GHZ = series(
    [1 * GHZ, 2 * GHZ, 3 * GHZ, 4 * GHZ, 5 * GHZ],
    [1.0, 0.1, 0.01, 0.1, 1.0],
)

# dB: [0, -20, -60, -20]. Resonance at 6 GHz, -10 dB band 4..8 GHz (4 GHz wide).
# "Variation 2": a different grid AND a different value for every metric, so no
# result of variation 1 could be mistaken for a result of this one.
RESONANT_AT_6GHZ = series(
    [2 * GHZ, 4 * GHZ, 6 * GHZ, 8 * GHZ],
    [1.0, 0.1, 0.001, 0.1],
)

# dB: [0, -6.0206..., 0]. 20*log10(0.5) = -20*log10(2) = -6.020599913279624, so
# the deepest point misses -10 dB and there is no band at all.
NEVER_REACHES_10DB = series(
    [1 * GHZ, 2 * GHZ, 3 * GHZ],
    [1.0, 0.5, 1.0],
)

# dB: [-9.9, -10.1, -40, -10.1, -9.9], built by inverting the dB definition
# (|S11| = 10 ** (dB/20)). Brackets the threshold from both sides without
# landing on it: the -10.1 dB samples are in band, the -9.9 dB samples are not,
# so the band is 2..4 GHz.
BAND_EDGES = series(
    [1 * GHZ, 2 * GHZ, 3 * GHZ, 4 * GHZ, 5 * GHZ],
    [
        10 ** (-9.9 / 20),
        10 ** (-10.1 / 20),
        0.01,
        10 ** (-10.1 / 20),
        10 ** (-9.9 / 20),
    ],
)

# dB: [0, -20, 0, -20, -40, -20, 0]. Resonance at 5 GHz with a band of
# 4..6 GHz, plus an unconnected -20 dB dip at 2 GHz that must NOT be counted.
DISCONNECTED_DIP = series(
    [1 * GHZ, 2 * GHZ, 3 * GHZ, 4 * GHZ, 5 * GHZ, 6 * GHZ, 7 * GHZ],
    [1.0, 0.1, 1.0, 0.1, 0.01, 0.1, 1.0],
)

# Two samples whose magnitudes are equal (0.6) but whose phases are 90 degrees
# apart. The midpoint of a COMPLEX-linear interpolation is 0.3+0.3j, magnitude
# sqrt(0.18) ~ 0.424; a magnitude-linear interpolation would give 0.6. The gap
# between those two is what makes this fixture discriminating.
COMPLEX_SEGMENT = series([1 * GHZ, 2 * GHZ], [0.6 + 0.0j, 0.0 + 0.6j])

# A one-sample sweep: the degenerate case where the -10 dB "band" is a single
# point and its width is legitimately 0.0.
SINGLE_SAMPLE = series([1 * GHZ], [0.1])

# A sample of exactly zero magnitude -- a perfect match, effectively unreachable
# in measured data, whose value in dB is -inf rather than an error.
PERFECT_MATCH = series([1 * GHZ, 2 * GHZ, 3 * GHZ], [0.1, 0.0, 0.1])
