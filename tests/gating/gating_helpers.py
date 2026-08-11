"""Shared helpers for the W-9 gating suite (Step 2.6b).

SNAPSHOTS ARE BUILT THROUGH ``assemble_snapshot``, NOT HAND-CONSTRUCTED, and that
is the point of this module. W-9 reads a ``DesignSnapshot``; building one by
calling ``DesignSnapshot(...)`` directly would let a test hand a gate a shape W-8
could never actually produce -- a ``Selection`` carrying a path, a snapshot with no
``snapshot_id``, an arm combination the assembler refuses. Driving the real
assembly path means every input a gate is tested against is one a caller could
genuinely hand it.

Uniquely named (not ``conftest``) and imported explicitly, following the session,
broker, inspect, metrics and snapshot suites' stated rationale: sibling
``conftest`` modules from different test dirs collide under pytest's rootdir
import mode. This is also why the snapshot suite's own ``snapshot_helpers`` is
NOT imported here -- ``tests/gating`` sorts before ``tests/snapshot``, so that
module is not yet on ``sys.path`` when this suite is collected, and relying on
collection order would be a test that passes for a reason unrelated to the code.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from hfss_agent.contract import (
    CONTRACT_VERSION,
    ComplexSample,
    DesignSnapshot,
    Environment,
    FreshnessEvidence,
    InspectionProvenance,
    InspectionSection,
    IntentObject,
    NativeValidation,
    NativeValidationProvenance,
    Project,
    SolutionExists,
    SolveDataUnavailable,
    SolvedData,
    SolveState,
    Variation,
)
from hfss_agent.contract.tool_io import (
    InspectionResult,
    NativeValidationBlock,
    SelectionChain,
)
from hfss_agent.snapshot import assemble_snapshot

PROJECT_NAME = "patch_antenna"
PROJECT_PATH = r"C:\Users\Owner\Documents\Ansoft\patch_antenna.aedt"
DESIGN = "HFSSDesign1"
SETUP = "Setup1"
SWEEP = "Sweep1"

ALL_SECTIONS = (
    "variables",
    "objects",
    "materials",
    "boundaries",
    "excitations_ports",
    "setups",
    "sweeps",
    "available_results",
)

def variation(
    values: dict[str, str] | None = None,
    variation_hash: str = "sha256:deadbeefcafef00d",
) -> Variation:
    return Variation(
        values=values if values is not None else {"w": "2mm"},
        variation_hash=variation_hash,
    )


def chain(**overrides: object) -> SelectionChain:
    """A complete seven-stage chain, with the project carrying its real path.

    The path is present on purpose: this hands the assembler exactly what a live
    session would, so W-8's drop is exercised rather than arranged away.
    """
    values: dict[str, object] = {
        "process_id": 12345,
        "project": Project(name=PROJECT_NAME, path=PROJECT_PATH),
        "design": DESIGN,
        "solution_type": "DrivenModal",
        "setup": SETUP,
        "sweep": SWEEP,
        "variation": variation(),
    }
    values.update(overrides)
    return SelectionChain(**values)  # type: ignore[arg-type]


def matching_entry(exists: bool = True) -> SolutionExists:
    """One solution-existence flag that MATCHES the default selection chain."""
    return SolutionExists(
        setup=SETUP, sweep=SWEEP, variation=variation(), exists=exists
    )


def solve_state(
    *,
    convergence_status: str = "converged",
    entries: list[SolutionExists] | None = None,
    pass_history: list[Any] | None = None,
    delta_s: list[float] | None = None,
    determinable: bool = False,
    signals: dict[str, Any] | None = None,
) -> SolveState:
    """A ``SolveState`` with the knobs the gate tests actually turn.

    ``determinable`` defaults to ``False`` -- the REAL adapter's unconditional
    value -- rather than to the fake's ``True``, so a test that wants the fake's
    shape has to ask for it explicitly.
    """
    return SolveState(
        solution_exists=[matching_entry()] if entries is None else entries,
        adaptive_pass_history=(
            [{"pass": 1, "delta_s": 0.05}, {"pass": 2, "delta_s": 0.004}]
            if pass_history is None
            else pass_history
        ),
        delta_s_progression=[0.05, 0.004] if delta_s is None else delta_s,
        convergence_status=convergence_status,  # type: ignore[arg-type]
        solve_timestamps={
            f"{SETUP}:{SWEEP}": datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)
        },
        solver_messages=["Adaptive passes converged at pass 2."],
        freshness_evidence=FreshnessEvidence(
            available_signals={} if signals is None else signals,
            determinable=determinable,
        ),
    )


def unavailable(reason: str) -> SolveDataUnavailable:
    return SolveDataUnavailable(
        reason=reason,  # type: ignore[arg-type]
        limitation=f"synthetic limitation for reason {reason}",
    )


def _inspection_result() -> InspectionResult:
    return InspectionResult(
        sections={  # type: ignore[arg-type]
            name: InspectionSection(data=[], read_status="ok")
            for name in ALL_SECTIONS
        },
        provenance=InspectionProvenance(
            project=PROJECT_NAME,
            design=DESIGN,
            read_at=datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc),
            contract_version=CONTRACT_VERSION,
            wrapper_version="0.0.0",
            read_under_aedt_version="2026.1",
        ),
        template_text="read-out",
    )


def _native_block() -> NativeValidationBlock:
    return NativeValidationBlock(
        validation=NativeValidation(raw_output=[]),
        provenance=NativeValidationProvenance(
            project=PROJECT_NAME,
            design=DESIGN,
            validated_at=datetime(2026, 8, 3, 9, 30, tzinfo=timezone.utc),
            contract_version=CONTRACT_VERSION,
            wrapper_version="0.0.0",
            validated_under_aedt_version="2026.1",
        ),
    )


def _environment() -> Environment:
    return Environment(
        aedt_version="2026.1",
        pyaedt_version="1.2.0",
        python_version="3.12.10",
        wrapper_version="0.0.0",
    )


def intent(target_frequency_hz: float = 2.4e9) -> IntentObject:
    """A design intent, for the target-coverage gate's fallback source.

    ``threshold_type``/``threshold_value`` are required by the schema and are
    deliberately NOT varied: evaluating a threshold is interpretation, which is
    Step 2.11's, and no gate reads either field. Only the frequency matters here.
    """
    return IntentObject(
        target_frequency_hz=target_frequency_hz,
        threshold_type="s11",
        threshold_value=-10.0,
    )


def swept(*frequencies: float) -> SolvedData:
    """Solved data over an arbitrary frequency list, for varying the swept range.

    The S-parameter series is filled to match length because ``SolvedData`` is
    aligned index-for-index; its values are irrelevant to every gate (only
    ``frequencies`` is read), so they are uniform rather than meaningful.
    """
    return SolvedData(
        frequencies=list(frequencies),
        s_parameters={
            "S(1,1)": [ComplexSample(real=-0.1, imag=0.0) for _ in frequencies]
        },
    )


def empty_solved_data() -> SolvedData:
    """A solved-data block that RAN and returned no samples.

    Distinct from ``unavailable(...)``: this is a present ``SolvedData`` whose
    ``frequencies`` list is empty, which the contract permits (no ``min_length``).
    It is the shape that separates "no sweep to test against" from "no solved data
    at all", and the two take different arms of ``DesignSnapshot.solved_data``.
    """
    return SolvedData(frequencies=[], s_parameters={})


def _solved_data() -> SolvedData:
    return SolvedData(
        frequencies=[2.3e9, 2.4e9, 2.5e9],
        s_parameters={
            "S(1,1)": [
                ComplexSample(real=-0.10, imag=0.02),
                ComplexSample(real=-0.50, imag=0.10),
                ComplexSample(real=-0.20, imag=0.05),
            ]
        },
    )


def snapshot(**overrides: object) -> DesignSnapshot:
    """One snapshot through the REAL W-8 entry point.

    Every gate test builds its input here, so a gate is never handed a shape the
    assembler could not have produced. ``solve_state`` and ``solved_data`` default
    to the solved case; a test overrides whichever it is about.
    """
    values: dict[str, object] = {
        "inspection": _inspection_result(),
        "native_validation": _native_block(),
        "solve_state": solve_state(),
        "solved_data": _solved_data(),
        "selection": chain(),
        "environment": _environment(),
    }
    values.update(overrides)
    return assemble_snapshot(**values)  # type: ignore[arg-type]


def round_tripped(original: DesignSnapshot) -> DesignSnapshot:
    """An EQUAL snapshot that is a genuinely separate object graph.

    Used by the determinism test for its second assertion. A ``model_copy`` would
    share sub-objects and a second ``snapshot()`` call would differ (``created_at``
    and ``snapshot_id`` are minted per call), so a JSON round-trip is the only
    construction that gives equal VALUES in an independent object -- which is
    exactly what "the findings depend on the data, not on identity" needs.
    """
    return DesignSnapshot.model_validate_json(original.model_dump_json())
