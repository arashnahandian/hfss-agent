"""Shared helpers for the W-8 snapshot suite (Step 2.5b).

EVERY INPUT IS CONSTRUCTED DIRECTLY, with no ``FakeAdapter``, no ``Session`` and
no ``Broker`` anywhere in this suite — and that is a property of W-8 rather than
a shortcut. The inspect, validate_native and metrics suites all drive a real
``Broker`` because their assemblers dispatch through one; W-8 dispatches through
nothing and imports only ``contract``, so the honest test of it is a test over
constructed data. Wiring a broker in here would exercise a path W-8 does not
have.

Uniquely named (not ``conftest``) and imported explicitly, following the session,
broker, inspect and metrics suites' stated rationale: sibling ``conftest`` modules
from different test dirs collide under pytest's rootdir import mode.
"""

from __future__ import annotations

from datetime import datetime, timezone

from hfss_agent.contract import (
    ComplexSample,
    Environment,
    InspectionProvenance,
    InspectionSection,
    NativeValidation,
    NativeValidationProvenance,
    Project,
    SolveDataUnavailable,
    SolvedData,
    Variation,
)
from hfss_agent.contract.tool_io import (
    InspectionResult,
    NativeValidationBlock,
    SelectionChain,
)

# The default AEDT project location, spelled the way it actually appears on a
# Windows machine rather than as a sanitised stand-in like ``C:\proj\p.aedt``.
# This is the shape that leaks an account name, and it is what the path-drop
# control plants — the same constant, and the same reasoning, as
# ``tests/schemas/test_selection_carries_no_path.py``.
PROJECT_PATH = r"C:\Users\Owner\Documents\Ansoft\patch_antenna.aedt"
PROJECT_NAME = "patch_antenna"
DESIGN = "HFSSDesign1"

# The eight section names, spelled out here so the suite checks the assembler
# against an independently written list rather than against the same
# ``Inspection.model_fields`` the assembler derives from.
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

# The seven stages, likewise written out independently of ``Selection``.
ALL_STAGES = (
    "process_id",
    "project",
    "design",
    "solution_type",
    "setup",
    "sweep",
    "variation",
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
    """A COMPLETE seven-stage chain, with the project carrying its real path.

    The path is present on purpose: this helper's job is to hand the assembler
    exactly what a live session would, so the drop is exercised rather than
    arranged away by a fixture that never had a path to begin with.
    """
    values: dict[str, object] = {
        "process_id": 12345,
        "project": Project(name=PROJECT_NAME, path=PROJECT_PATH),
        "design": DESIGN,
        "solution_type": "DrivenModal",
        "setup": "Setup1",
        "sweep": "Sweep1",
        "variation": variation(),
    }
    values.update(overrides)
    return SelectionChain(**values)  # type: ignore[arg-type]


def sections(names: tuple[str, ...] = ALL_SECTIONS) -> dict[str, InspectionSection]:
    return {name: InspectionSection(data=[], read_status="ok") for name in names}


def inspection_result(
    names: tuple[str, ...] = ALL_SECTIONS,
) -> InspectionResult:
    return InspectionResult(
        sections=sections(names),  # type: ignore[arg-type]
        provenance=InspectionProvenance(
            project=PROJECT_NAME,
            design=DESIGN,
            read_at=datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc),
            contract_version="snapshot-3.0.0",
            wrapper_version="0.0.0",
            read_under_aedt_version="2026.1",
        ),
        template_text="read-out",
    )


def native_block(raw_output: list[str] | None = None) -> NativeValidationBlock:
    return NativeValidationBlock(
        validation=NativeValidation(raw_output=raw_output or []),
        provenance=NativeValidationProvenance(
            project=PROJECT_NAME,
            design=DESIGN,
            validated_at=datetime(2026, 8, 3, 9, 30, tzinfo=timezone.utc),
            contract_version="snapshot-3.0.0",
            wrapper_version="0.0.0",
            validated_under_aedt_version="2026.1",
        ),
    )


def environment() -> Environment:
    return Environment(
        aedt_version="2026.1",
        pyaedt_version="1.2.0",
        python_version="3.12.10",
        wrapper_version="0.0.0",
    )


def solved_data() -> SolvedData:
    return SolvedData(
        frequencies=[2.4e9],
        s_parameters={"S(1,1)": [ComplexSample(real=-0.1, imag=0.02)]},
    )


def unavailable(reason: str = "no_solution") -> SolveDataUnavailable:
    return SolveDataUnavailable(
        reason=reason,  # type: ignore[arg-type]
        limitation="no solved S-parameter data is available for Setup1 : Sweep1",
    )


def inputs(**overrides: object) -> dict[str, object]:
    """The complete happy-path keyword set, for tests that vary one input.

    Returned as kwargs rather than as a built snapshot so a test can replace a
    single argument and still exercise the real entry point.
    """
    values: dict[str, object] = {
        "inspection": inspection_result(),
        "native_validation": native_block(),
        "solve_state": unavailable("not_exposed_by_pyaedt"),
        "solved_data": solved_data(),
        "selection": chain(),
        "environment": environment(),
    }
    values.update(overrides)
    return values
