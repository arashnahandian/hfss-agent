"""DesignSnapshot — the versioned wrapper->engine contract artifact (W-8).

Assembled by the snapshot module and handed to the (optional) closed engine.
Plain JSON-serializable data only — never live handles, sessions, paths, or
callables (W-8). The structure below follows System Design §2 field for field;
it is the public, auditable statement of exactly what the engine ever sees.
"""

from datetime import datetime
from typing import Any, Literal

from hfss_agent.contract.common import (
    ConvergenceStatus,
    ReadStatus,
    StrictModel,
    UntrustedStr,
    Variation,
)
from hfss_agent.contract.intent_object import IntentObject


class Environment(StrictModel):
    """Identity/environment block (§2 DesignSnapshot.environment)."""

    aedt_version: str
    pyaedt_version: str
    python_version: str
    wrapper_version: str


class Project(StrictModel):
    """The selected project — name plus path (§2 selection: 'project (name+path)').

    ``name`` is an HFSS-sourced string and therefore untrusted; ``path`` is
    filesystem data the wrapper itself resolves.
    """

    name: UntrustedStr
    path: str


class Selection(StrictModel):
    """The explicit selection chain captured in the snapshot (§2 selection).

    ``variation`` originates here — the one explicitly user-selected variation
    the Tier 1 UX computes for (§2; no silent "nominal"). This is one of only
    two standalone homes §2 gives the variation key (the other is
    ProvenanceRecord); everywhere else it travels via provenance.
    """

    process_id: int
    project: Project
    design: UntrustedStr
    solution_type: str
    setup: str
    sweep: str
    variation: Variation


class InspectionSection(StrictModel):
    """One inspection section (§2 inspection).

    Every section carries the same shape: its ``data``, a ``read_status``, and —
    when ``not_readable`` — the exact PyAEDT limitation named in ``limitation``.
    Where PyAEDT cannot read something, that is stated here rather than papered
    over.
    """

    data: Any
    read_status: ReadStatus
    limitation: str | None = None


class Inspection(StrictModel):
    """The full structured read-out (§2 inspection).

    Each of the eight sections carries the {data, read_status, limitation?}
    shape consistently, so a partially-readable design is represented honestly
    section by section rather than failing whole.
    """

    variables: InspectionSection
    objects: InspectionSection
    materials: InspectionSection
    boundaries: InspectionSection
    excitations_ports: InspectionSection
    setups: InspectionSection
    sweeps: InspectionSection
    available_results: InspectionSection


class NativeValidation(StrictModel):
    """Raw HFSS ValidateDesign output, attributed (§2 native_validation).

    The messages are untrusted HFSS-sourced strings; ``source`` is fixed so the
    passthrough is always attributable to HFSS itself and structurally separable
    from supplemental findings (spec Point 2).
    """

    raw_output: list[UntrustedStr]
    source: Literal["hfss_native"] = "hfss_native"


class FreshnessEvidence(StrictModel):
    """Freshness signals plus an explicit determinability flag (§2, ADR-4).

    ``determinable`` is what lets the freshness gate return
    "insufficient_evidence" honestly instead of guessing when PyAEDT does not
    expose enough to decide whether the design/variables/setup changed since the
    solve (§1.1 W-9). It is deliberately not collapsed into a plain freshness
    boolean.
    """

    available_signals: dict[str, Any]
    determinable: bool


class SolutionExists(StrictModel):
    """Whether a solution exists for one specific setup/sweep/variation
    combination (§2 solve_state: "solution-exists flags per
    setup/sweep/variation").

    Keyed per combination, not a single design-wide flag, because the first
    validity gate asks about the exact combination the user selected — the
    design as a whole having *some* solution is not the question.
    """

    setup: str
    sweep: str
    variation: Variation
    exists: bool


class SolveState(StrictModel):
    """Solve-state block (§2 solve_state).

    Carries enough convergence and freshness evidence for the gating module to
    decide validity without touching HFSS, and already holds the signals the
    Tier 2.1 failed-solve autopsy will extend (§7) — no field here is
    S-parameter-metric-specific.
    """

    solution_exists: list[SolutionExists]
    adaptive_pass_history: list[Any]
    delta_s_progression: list[float]
    convergence_status: ConvergenceStatus  # converged / stopped (§2)
    solve_timestamps: dict[str, datetime]
    solver_messages: list[UntrustedStr]  # surfaced as untrusted strings (§6.6)
    freshness_evidence: FreshnessEvidence


class ComplexSample(StrictModel):
    """One complex S-parameter value as JSON-serializable real/imag parts.

    Python ``complex`` is not JSON-serializable and the snapshot is plain data
    only (W-8), so complex S is carried as explicit ``real`` + ``imag``.
    """

    real: float
    imag: float


class SolvedData(StrictModel):
    """Raw S-parameter series scoped to the selection (§2 solved_data).

    These are the inputs W-7's open formulas consume. ``s_parameters`` maps each
    S-parameter name (e.g. "S(1,1)") to a complex series aligned index-for-index
    with ``frequencies``.
    """

    frequencies: list[float]
    s_parameters: dict[str, list[ComplexSample]]


class DesignSnapshot(StrictModel):
    """The versioned design snapshot (W-8) — ``contract_version`` carries the
    semver-tagged schema version (``common.CONTRACT_VERSION``).

    See System Design §2. ``intent`` is the only optional top-level block: a
    snapshot is valid whether or not the user has set a design intent.
    """

    contract_version: str
    created_at: datetime
    snapshot_id: str
    environment: Environment
    selection: Selection
    inspection: Inspection
    native_validation: NativeValidation
    solve_state: SolveState
    solved_data: SolvedData
    intent: IntentObject | None = None
