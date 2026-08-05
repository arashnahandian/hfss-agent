"""Fixtures for the W-7 assembler tests: gate Findings, solved data, intent.

THE GATE FINDINGS ARE HAND-BUILT HERE, AND THAT IS THE POINT OF THE STUB. W-9
does not exist yet (Step 2.6), and W-7 may not import it when it does — gate
outcomes reach the assembler as DATA. So a test can construct any gate state it
wants without a gating module existing, and at Step 2.6 the same tests keep
working while a new end-to-end test replaces ``gate(...)`` with real
``evaluate_gates`` output. Nothing in ``metrics/`` changes at that point.

``rule_id``s below use the ``gate.<name>`` spelling the contract-schema fixture
already uses (``tests/schemas/conftest.py``), and ``calculation_ref`` uses the
one-module-per-gate form ``hfss_agent.gating.<name>:evaluate`` that the same
fixture pins for W-9's future layout. Neither is invented here.

S11 VALUES USE POWER-OF-TEN MAGNITUDES, following ``sparams_helpers``: 1.0 -> 0
dB, 0.1 -> -20 dB, 0.01 -> -40 dB. Every expected number in the assembler tests
is therefore readable off the fixture without a calculator.
"""

from __future__ import annotations

from datetime import datetime, timezone

from hfss_agent.contract import (
    CONTRACT_VERSION,
    Applicability,
    ComplexSample,
    Finding,
    FindingOutcome,
    FindingProvenance,
    IntentObject,
    ProvenanceRecord,
    SolvedData,
    Variation,
)

GHZ = 1.0e9
Z0 = 50.0

# The four gates §1.1 fixes, in the order it lists them. Named here so a test can
# say "the complete set" without retyping, and so the assembler's inability to
# verify that completeness is testable as the documented gap it is.
FOUR_GATE_NAMES = ("solution_exists", "convergence", "freshness", "target_coverage")


def gate(
    name: str = "solution_exists",
    outcome: FindingOutcome = "pass",
    reason: str | None = None,
) -> Finding:
    """One gate result in the seven-field Finding schema, five-state outcome."""
    return Finding(
        finding_id=f"gate-{name}-{outcome}",
        source="gate",
        rule_id=f"gate.{name}",
        rule_version="1.0.0",
        rule_purpose=f"The {name} validity gate.",
        inspected=[f"solve_state.{name}"],
        observed_values={"outcome": outcome},
        calculation_ref=f"hfss_agent.gating.{name}:evaluate",
        reason_flagged=reason or f"The {name} gate returned {outcome}.",
        outcome=outcome,
        classification="judgment_call",
        severity="info",
        limitations_and_assumptions="Synthetic gate result for the W-7 tests.",
        applicability=Applicability(conditions={"has_setup": True}, held=True),
        provenance=finding_provenance_for(),
        template_text=f"[gate] {name}: {outcome}",
    )


def four_passing_gates() -> list[Finding]:
    """The complete set of four gates, all passing — the permitting case."""
    return [gate(name) for name in FOUR_GATE_NAMES]


def four_gates_with(name: str, outcome: FindingOutcome) -> list[Finding]:
    """The four gates with exactly one of them set to a non-passing outcome."""
    return [
        gate(each, outcome if each == name else "pass") for each in FOUR_GATE_NAMES
    ]


def provenance_for(
    project: str = "patch_antenna",
    design: str = "HFSSDesign1",
    reference_impedance: float = Z0,
    variation_hash: str = "sha256:deadbeefcafef00d",
    variation_values: dict[str, str] | None = None,
) -> ProvenanceRecord:
    """A complete ProvenanceRecord.

    ``reference_impedance`` and the variation fields are parameterised because
    they are the two things the assembler tests need to vary: Z0 is the only
    source of the impedance metric's scale, and the variation is what proves two
    variations produce independently stamped records.
    """
    return ProvenanceRecord(
        project=project,
        design=design,
        solution_type="DrivenModal",
        setup="Setup1",
        sweep="Sweep1",
        variation=Variation(
            values=variation_values or {"width": "2.0mm", "freq": "2.4GHz"},
            variation_hash=variation_hash,
        ),
        expression="dB(S(1,1))",
        reference_impedance=reference_impedance,
        solve_timestamp=datetime(2026, 7, 17, 9, 30, tzinfo=timezone.utc),
        freshness_status="fresh",
        snapshot_id="snap-001",
        contract_version=CONTRACT_VERSION,
        wrapper_version="0.2.0",
    )


def finding_provenance_for(
    project: str = "patch_antenna",
    design: str = "HFSSDesign1",
    variation_hash: str = "sha256:deadbeefcafef00d",
    variation_values: dict[str, str] | None = None,
) -> FindingProvenance:
    """A complete FindingProvenance, for the gate results above.

    SEPARATE FROM ``provenance_for`` RATHER THAN DERIVED FROM IT, and the two
    must not be folded together: this file needs BOTH shapes at once, because a
    gate Finding and a MetricRecord carry different provenance types (ADR-30).
    ``reference_impedance`` is absent here and is the reason the two cannot
    share — it is the one input ``provenance_for`` exists to vary, and a
    judgment has none.
    """
    return FindingProvenance(
        project=project,
        design=design,
        solution_type="DrivenModal",
        setup="Setup1",
        sweep="Sweep1",
        variation=Variation(
            values=variation_values or {"width": "2.0mm", "freq": "2.4GHz"},
            variation_hash=variation_hash,
        ),
        snapshot_id="snap-001",
        contract_version=CONTRACT_VERSION,
        wrapper_version="0.2.0",
    )


def solved(frequencies: list[float], s11: list[complex | float]) -> SolvedData:
    """SolvedData carrying one S(1,1) series aligned with ``frequencies``."""
    return SolvedData(
        frequencies=list(frequencies),
        s_parameters={
            "S(1,1)": [
                ComplexSample(real=complex(value).real, imag=complex(value).imag)
                for value in s11
            ]
        },
    )


def intent_at(target_hz: float) -> IntentObject:
    """A design intent whose only field the assembler reads is the frequency."""
    return IntentObject(
        target_frequency_hz=target_hz, threshold_type="s11", threshold_value=-10.0
    )


# --- the solved-data fixtures --------------------------------------------------

# dB: [0, -20, -40, -20, 0] at 1..5 GHz. Resonance -40 dB at 3 GHz; the -10 dB
# band runs 2..4 GHz, so its width is 2 GHz. The 3 GHz target lands exactly on
# the resonant sample, so the at-target metrics need no interpolation:
#   |G| = 0.01  ->  S11 = -40 dB
#   VSWR = (1 + 0.01) / (1 - 0.01) = 1.01 / 0.99
#   Z = 50 * (1 + 0.01) / (1 - 0.01) = 50 * 1.01 / 0.99  (purely real, X = 0)
RESONANT_AT_3GHZ = solved(
    [1 * GHZ, 2 * GHZ, 3 * GHZ, 4 * GHZ, 5 * GHZ], [1.0, 0.1, 0.01, 0.1, 1.0]
)
TARGET_3GHZ = 3 * GHZ

# A second variation: a different grid AND a different value for every metric, so
# no result of the first could be mistaken for a result of this one.
# dB: [0, -20, -60, -20] at 2, 4, 6, 8 GHz. Resonance -60 dB at 6 GHz, band
# 4..8 GHz (4 GHz wide).
RESONANT_AT_6GHZ = solved(
    [2 * GHZ, 4 * GHZ, 6 * GHZ, 8 * GHZ], [1.0, 0.1, 0.001, 0.1]
)
TARGET_6GHZ = 6 * GHZ

# Nothing reaches -10 dB: the deepest sample is -6.02 dB (|G| = 0.5), so there is
# no band to report and minus_10db_bandwidth returns NoMinus10dBBand.
NEVER_REACHES_10DB = solved([1 * GHZ, 2 * GHZ, 3 * GHZ], [0.7, 0.5, 0.7])

# |G| = 0 exactly at 2 GHz -- a perfect match. s11_min is -inf there, which is the
# true limiting value and is not representable in strict JSON.
PERFECT_MATCH = solved([1 * GHZ, 2 * GHZ, 3 * GHZ], [0.1, 0.0, 0.1])

TARGET_2GHZ = 2 * GHZ

# THE TWO |G| = 1 FIXTURES BELOW EXIST AS A PAIR, and the difference between them
# is the whole reason both are here: |G| = 1 makes VSWR diverge, but whether the
# IMPEDANCE also diverges depends on WHERE on the unit circle G sits.
#
# G = -1 exactly at 2 GHz -- an ideal SHORT. |G| = 1, so VSWR is +inf and has no
# record. But Z = 50 * (1 + -1) / (1 - -1) = 50 * 0 / 2 = 0+0j exactly, which is
# finite: a short is zero ohms, and both impedance records are emitted.
TOTAL_REFLECTION_SHORT = solved([1 * GHZ, 2 * GHZ, 3 * GHZ], [0.1, -1.0, 0.1])

# G = 1+0j exactly at 2 GHz -- an ideal OPEN. |G| = 1 again, so VSWR is +inf
# again, but here 1 - G is exactly zero: the complex impedance has no limit at
# all (which phase an infinity would carry depends on the direction of approach),
# so impedance_at_target RAISES and both its records are omitted for a DIFFERENT
# reason than VSWR's.
IDEAL_OPEN = solved([1 * GHZ, 2 * GHZ, 3 * GHZ], [0.1, 1.0 + 0j, 0.1])

# |G| = 1.5 > 1 at 2 GHz: not a VSWR at all (the expression yields a finite
# negative number) and non-physical for a passive one-port, yet a perfectly
# ordinary thing for a solver to return. Every other metric is still computable.
REFLECTION_ABOVE_UNITY = solved([1 * GHZ, 2 * GHZ, 3 * GHZ], [0.1, 1.5, 0.1])
