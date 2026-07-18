"""FakeAdapter scenario config (W-3): per-test canned data + per-op fault injection.

Not a contract schema — test-support configuration owned by the adapter. Two
independent axes so every downstream module (session, inspect, gating, metrics,
…) can get exactly the data shape it needs:

  * canned-data fields — one per read operation, each a valid default a test
    overrides only where it cares (a stale ``SolveState``, an unreadable
    inspection section, hostile-shaped strings, a gate-failing solve). These are
    DATA SHAPES, not faults.
  * ``behavior`` — a per-operation override map (absent key = return canned data)
    that injects a fault, a hang, or an unexpected raise, independently per op.

Per-*call-sequence* scripting (call 1 hangs, call 2 recovers) is a deliberate
later extension for the session module's reconnect tests, not built here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from hfss_agent.adapter.results import AdapterOutcome
from hfss_agent.contract import (
    ComplexSample,
    Environment,
    FreshnessEvidence,
    InspectionSection,
    NativeValidation,
    SolutionExists,
    SolvedData,
    SolveState,
    Variation,
)
from hfss_agent.contract.tool_io import (
    InspectionSectionName,
    SelectionOption,
    SelectionStage,
)


@dataclass(frozen=True)
class OpBehavior:
    """What the fake does for one operation (default: return the canned data).

    At most one injection mode is meaningful at a time; they are checked in the
    order raises -> hang -> fault.
    """

    fault: AdapterOutcome | None = None  # return this outcome (crash/disconnect/…)
    hang: bool = False  # block until the watchdog abandons the call
    raises: Exception | None = None  # raise this, to prove the watchdog's catch-all


def _default_variation() -> Variation:
    return Variation(
        values={"width": "2.0mm"}, variation_hash="sha256:defaultvariation"
    )


def _default_environment() -> Environment:
    return Environment(
        aedt_version="2026.1",
        pyaedt_version="1.2.0",
        python_version="3.12.4",
        wrapper_version="0.0.0",
    )


def _default_options() -> dict[SelectionStage, list[SelectionOption]]:
    variation = _default_variation()
    return {
        "project": [SelectionOption(value="patch_antenna", display="patch_antenna")],
        "design": [SelectionOption(value="HFSSDesign1", display="HFSSDesign1")],
        "setup": [SelectionOption(value="Setup1", display="Setup1")],
        "sweep": [SelectionOption(value="Sweep1", display="Sweep1")],
        "variation": [
            SelectionOption(value=variation.variation_hash, variation=variation)
        ],
    }


def _default_inspection() -> dict[InspectionSectionName, InspectionSection]:
    return {
        "variables": InspectionSection(
            data={"width": "2.0mm", "height": "1.6mm"}, read_status="ok"
        ),
        "objects": InspectionSection(
            data=["Patch", "Substrate", "GroundPlane"], read_status="ok"
        ),
        "materials": InspectionSection(
            data={"FR4_epoxy": {"permittivity": "4.4"}}, read_status="ok"
        ),
        "boundaries": InspectionSection(data=["Rad1"], read_status="ok"),
        "excitations_ports": InspectionSection(data=["1"], read_status="ok"),
        "setups": InspectionSection(data=["Setup1"], read_status="ok"),
        "sweeps": InspectionSection(data={"Setup1": ["Sweep1"]}, read_status="ok"),
        "available_results": InspectionSection(
            data=["S Parameter Plot 1"], read_status="ok"
        ),
    }


def _default_native_validation() -> NativeValidation:
    return NativeValidation(
        raw_output=["Design validation completed. 0 errors, 0 warnings."]
    )


def _default_solve_state() -> SolveState:
    return SolveState(
        solution_exists=[
            SolutionExists(
                setup="Setup1",
                sweep="Sweep1",
                variation=_default_variation(),
                exists=True,
            )
        ],
        adaptive_pass_history=[
            {"pass": 1, "delta_s": 0.05},
            {"pass": 2, "delta_s": 0.02},
        ],
        delta_s_progression=[0.05, 0.02],
        convergence_status="converged",
        solve_timestamps={
            "Setup1:Sweep1": datetime(2026, 7, 17, 9, 30, tzinfo=timezone.utc)
        },
        solver_messages=["Adaptive passes converged at pass 2."],
        freshness_evidence=FreshnessEvidence(
            available_signals={"design_modified_since_solve": False},
            determinable=True,
        ),
    )


def _default_solved_data() -> SolvedData:
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


@dataclass
class Scenario:
    """One test's canned data plus per-operation behavior overrides."""

    environment: Environment = field(default_factory=_default_environment)
    options: dict[SelectionStage, list[SelectionOption]] = field(
        default_factory=_default_options
    )
    solution_type: str = "DrivenModal"  # returned in the chain at the design stage
    project_path: str = r"C:\proj\patch_antenna.aedt"
    inspection: dict[InspectionSectionName, InspectionSection] = field(
        default_factory=_default_inspection
    )
    native_validation: NativeValidation = field(
        default_factory=_default_native_validation
    )
    solve_state: SolveState = field(default_factory=_default_solve_state)
    solved_data: SolvedData = field(default_factory=_default_solved_data)
    behavior: dict[str, OpBehavior] = field(default_factory=dict)
