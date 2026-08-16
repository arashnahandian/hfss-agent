"""Shared fixtures for the W-10 receipt suite (Step 2.7, Part 1).

ACCEPTED-PATH INPUTS COME FROM THE REAL PIPELINE. ``accepted_gate_findings()``
drives ``assemble_snapshot`` and then ``evaluate_gates``, both imported from
``src``, so every finding the gate is asked to accept is one a caller could
genuinely hand it. No ``Finding`` is hand-built anywhere on that path -- a
hand-built one would prove the gate accepts a fixture, which is a different and
much weaker claim.

MALFORMED FIXTURES ARE HAND-BUILT, AND ONLY THERE. Below the accepted path, the
objects are constructed by ``model_construct``, by subclassing, or as plain
Python values, because in those tests the malformed object IS the subject rather
than a shortcut to one. The catalogue mirrors the ten input shapes this step's
Probe 4 measured, so the suite tests the shapes that were observed rather than
the ones that were imagined.

WHY THIS DUPLICATES A LITTLE OF ``tests/gating/gating_helpers``, stated because
the duplication is deliberate and a reader will otherwise read it as sloppiness.
``tests/findings`` sorts BEFORE ``tests/gating``, and the suite has no
``__init__.py``, so ``gating_helpers`` is not yet on ``sys.path`` when this module
is imported at collection time -- the same constraint ``gating_helpers`` itself
records about ``snapshot_helpers``. Importing it would make this suite pass or
fail on collection order, which is worse than a short builder. What is NOT
duplicated is anything from ``src``: the assembler, the gates and every contract
type are imported directly, so only the fixture VALUES live here.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone

from hfss_agent.contract import (
    CONTRACT_VERSION,
    Applicability,
    ComplexSample,
    DesignSnapshot,
    Environment,
    Finding,
    FindingProvenance,
    FreshnessEvidence,
    InspectionProvenance,
    InspectionSection,
    NativeValidation,
    NativeValidationProvenance,
    Project,
    SolutionExists,
    SolvedData,
    SolveState,
    Variation,
)
from hfss_agent.contract.tool_io import (
    InspectionResult,
    NativeValidationBlock,
    SelectionChain,
)
from hfss_agent.gating import evaluate_gates
from hfss_agent.snapshot import assemble_snapshot

PROJECT_NAME = "patch_antenna"
PROJECT_PATH = r"C:\Users\Owner\Documents\Ansoft\patch_antenna.aedt"
DESIGN = "HFSSDesign1"
SETUP = "Setup1"
SWEEP = "Sweep1"
TARGET_HZ = 2.4e9

_SECTIONS = (
    "variables",
    "objects",
    "materials",
    "boundaries",
    "excitations_ports",
    "setups",
    "sweeps",
    "available_results",
)


def _variation() -> Variation:
    return Variation(values={"w": "2mm"}, variation_hash="sha256:deadbeefcafef00d")


def _selection() -> SelectionChain:
    """A complete chain carrying the project's real path, so W-8's path drop is
    exercised rather than arranged away."""
    return SelectionChain(
        process_id=12345,
        project=Project(name=PROJECT_NAME, path=PROJECT_PATH),
        design=DESIGN,
        solution_type="DrivenModal",
        setup=SETUP,
        sweep=SWEEP,
        variation=_variation(),
    )


def _solve_state() -> SolveState:
    return SolveState(
        solution_exists=[
            SolutionExists(
                setup=SETUP, sweep=SWEEP, variation=_variation(), exists=True
            )
        ],
        adaptive_pass_history=[
            {"pass": 1, "delta_s": 0.05},
            {"pass": 2, "delta_s": 0.004},
        ],
        delta_s_progression=[0.05, 0.004],
        convergence_status="converged",
        solve_timestamps={
            f"{SETUP}:{SWEEP}": datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)
        },
        solver_messages=["Adaptive passes converged at pass 2."],
        # The REAL adapter's unconditional value, not the fake's, so the freshness
        # gate takes the arm every live design takes.
        freshness_evidence=FreshnessEvidence(available_signals={}, determinable=False),
    )


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


def _inspection() -> InspectionResult:
    return InspectionResult(
        sections={  # type: ignore[arg-type]
            name: InspectionSection(data=[], read_status="ok") for name in _SECTIONS
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


def _native() -> NativeValidationBlock:
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


def snapshot() -> DesignSnapshot:
    """One snapshot through the REAL W-8 entry point."""
    return assemble_snapshot(
        inspection=_inspection(),
        native_validation=_native(),
        solve_state=_solve_state(),
        solved_data=_solved_data(),
        selection=_selection(),
        environment=Environment(
            aedt_version="2026.1",
            pyaedt_version="1.2.0",
            python_version="3.12.10",
            wrapper_version="0.0.0",
        ),
    )


def accepted_gate_findings() -> list[Finding]:
    """The four real gate findings, through the real assembler and real gates."""
    return evaluate_gates(snapshot(), TARGET_HZ)


# --- engine-shaped findings: valid in every field, built here because no engine
# --- exists to produce one. These are the CONTROL for the malformed fixtures:
# --- they must be accepted, or a rejection test proves nothing about rejection.


def _provenance() -> FindingProvenance:
    return FindingProvenance(
        project=PROJECT_NAME,
        design=DESIGN,
        solution_type="DrivenModal",
        setup=SETUP,
        sweep=SWEEP,
        variation=_variation(),
        snapshot_id="snap-engine-fixture",
        contract_version=CONTRACT_VERSION,
        wrapper_version="0.0.0",
        engine_version="e-1.0.0",
    )


def engine_finding_kwargs(**overrides: object) -> dict[str, object]:
    """The complete keyword set for a well-formed engine finding."""
    values: dict[str, object] = {
        "finding_id": "engine-rule-001",
        "source": "engine_rule",
        "rule_id": "engine.port_impedance",
        "rule_version": "1.0.0",
        "rule_purpose": "Checks the port reference impedance against the intent.",
        "inspected": ["inspection.excitations_ports"],
        "observed_values": {"port_count": 1},
        "calculation_ref": "engine.rules.port_impedance:evaluate",
        "reason_flagged": "The port reference impedance matches the intent.",
        "outcome": "pass",
        "classification": "judgment_call",
        "severity": "info",
        "limitations_and_assumptions": "Reads the snapshot only.",
        "applicability": Applicability(conditions={"has_ports": True}, held=True),
        "provenance": _provenance(),
        "template_text": "[engine] port_impedance: pass.",
    }
    values.update(overrides)
    return values


def engine_finding(**overrides: object) -> Finding:
    return Finding(**engine_finding_kwargs(**overrides))  # type: ignore[arg-type]


# --- the malformed catalogue, mirroring Probe 4's ten measured shapes ---------


class MethodOnlySubclass(Finding):
    """A subclass adding ONLY a method: identical fields, extra behaviour.

    The shape ``isinstance`` waves through. Its ``model_dump()`` is byte-identical
    to a plain ``Finding``'s, so the receipt gate NORMALIZES it rather than
    refusing it -- and the method must not survive that.
    """

    def render(self) -> str:
        return "SIDE EFFECT: engine-controlled code ran inside the wrapper"


class FieldAddingSubclass(Finding):
    """A subclass declaring an extra field, which ``extra="forbid"`` refuses."""

    confidence: float = 0.99


class ForeignFinding:
    """Not a ``Finding`` at all, and not a pydantic model either."""

    def __init__(self, finding_id: str = "foreign-1") -> None:
        self.finding_id = finding_id


class RaisingAccessor:
    """An object whose ``finding_id`` access raises something other than
    ``AttributeError``.

    ``getattr(x, name, default)`` returns the default ONLY for ``AttributeError``,
    so this propagates through a naive accessor. Measured in Probe 4's follow-up,
    not imagined.
    """

    @property
    def finding_id(self) -> str:
        raise RuntimeError("an engine object refused to be inspected")


class _HostileMapping(Mapping):
    """A mapping that reduces fine as an object and explodes when READ.

    Not imagined: this is what makes ``Finding.model_validate`` raise a
    non-``ValidationError``, which is the only way to reach the receipt gate's
    second stage-specific refusal.
    """

    def __getitem__(self, key: object) -> object:
        raise RuntimeError("an engine payload refused to be read")

    def __iter__(self):  # type: ignore[no-untyped-def]
        raise RuntimeError("an engine payload refused to be iterated")

    def __len__(self) -> int:
        return 1


class DumpsButDoesNotValidate(Finding):
    """``model_dump()`` SUCCEEDS; validating what it returned raises.

    The shape that proved a single guard over both stages could report something
    false -- the object reduces cleanly, so any detail claiming it "could not be
    reduced to plain data" is a lie about it.
    """

    def model_dump(self, **kwargs: object) -> Mapping:  # type: ignore[override]
        return _HostileMapping()


class RaisesWhileDumping(Finding):
    """``model_dump()`` itself raises: a failure at the FIRST stage.

    The companion to the class above. Together they are the only way to show the
    two stage-specific details are attached to the stages they name.
    """

    def model_dump(self, **kwargs: object) -> dict[str, object]:  # type: ignore[override]
        raise RuntimeError("an engine override raised while reducing")


def ghost(**fields: object) -> Finding:
    """A ``Finding`` built by ``model_construct``: validation bypassed entirely.

    Passes ``isinstance(x, Finding)`` with required fields simply ABSENT --
    reading one raises ``AttributeError``. This is the shape a separately built
    wheel produces, and the reason a required-field check against a constructed
    object cannot fire.
    """
    return Finding.model_construct(**fields)


# The nine non-Finding / malformed inputs, keyed by the Probe 4 label they came
# from, so a failure names the measured shape rather than a fixture number.
NOT_A_FINDING_SHAPES: dict[str, object] = {
    "a plain dict carrying an id": {"finding_id": "dict-id", "severity": "info"},
    "a plain dict with no id": {"severity": "info"},
    "a bare string": "not a finding at all",
    "None": None,
    "a foreign object": ForeignFinding(),
    "an object whose accessor raises": RaisingAccessor(),
    "an int": 12345,
}

SCHEMA_INVALID_SHAPES: dict[str, object] = {
    "ghost: only finding_id": ghost(finding_id="ghost-known-id"),
    "ghost: only severity": ghost(severity="info"),
    "ghost: nothing set": ghost(),
    "ghost: finding_id is not a string": ghost(finding_id=12345),
    "ghost: finding_id is None": ghost(finding_id=None),
    "ghost: nested ghost provenance": ghost(
        finding_id="nested-ghost", provenance=FindingProvenance.model_construct()
    ),
    "ghost: wrong types throughout": ghost(
        finding_id=12345, inspected="not-a-list", provenance="nope"
    ),
}
