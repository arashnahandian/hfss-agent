"""Preflight & session tool I/O (§3): preflight_environment, list_aedt_processes,
attach, list_selection_options, select, get_session_status.

preflight_environment and list_aedt_processes do not reach PyAEDT through the
adapter the way the session tools do, so — per the cannot_evaluate narrowing
logged for this step — their responses have no CannotEvaluate arm:
incompatibilities and an empty process list are ordinary data in the report,
not a cannot_evaluate. attach / select / get_session_status share one
SessionStatus schema.
"""

from typing import Literal

from hfss_agent.contract.common import StrictModel, UntrustedStr, Variation
from hfss_agent.contract.design_snapshot import Environment, Project
from hfss_agent.contract.tool_io.common import CannotEvaluate, SelectionStage

# --- preflight_environment ---------------------------------------------------


class ComponentCheck(StrictModel):
    """One component checked against the published support matrix (W-11).

    ``detected`` is None when the component is not present/detectable (e.g. no
    AEDT install found); the verdict then lives in ``status``.
    """

    component: str  # e.g. "aedt", "pyaedt", "python", "grpc", "license"
    detected: str | None
    required: str  # support-matrix requirement, in plain language
    status: Literal["ok", "incompatible", "unavailable"]
    detail: str


class PreflightReport(StrictModel):
    """Journey 1.0 environment health vs. the published support matrix (§3, W-11).

    Genuinely new — no §2 schema expresses a compatibility verdict — but it
    reuses ``Environment`` for the version-identity block rather than restating
    those four fields.
    """

    environment: Environment
    checks: list[ComponentCheck]
    support_matrix_ref: str
    overall: Literal["ok", "incompatible"]
    template_text: str


# --- list_aedt_processes -----------------------------------------------------


class AedtProcess(StrictModel):
    """One running AEDT process discovered by W-2 (§3)."""

    process_id: int
    aedt_version: str
    grpc_port: int | None = None
    open_projects: list[UntrustedStr]  # HFSS-sourced names → untrusted


class AedtProcessList(StrictModel):
    """The running-AEDT-process listing (§3). New: no §2 schema describes a
    process (Selection carries only a bare ``process_id`` int)."""

    processes: list[AedtProcess]
    template_text: str


# --- attach / select / get_session_status (one shared status schema) ---------


class SelectionChain(StrictModel):
    """The selection chain as a *partial* state (§3 "selection chain").

    Cannot reuse DesignSnapshot.Selection: that schema requires every stage (a
    complete, solved selection). The chain is built stage by stage and reset
    downstream on any change (W-2), so every stage here is optional — a
    freshly-attached session has only ``process_id``. Reuses Project and
    Variation for the two stages that carry structured data.
    """

    process_id: int | None = None
    project: Project | None = None
    design: UntrustedStr | None = None
    solution_type: str | None = None
    setup: str | None = None
    sweep: str | None = None
    variation: Variation | None = None


class SessionStatus(StrictModel):
    """Session health + selection chain + suspect flag (§3): the shared response
    of attach, select, and get_session_status.

    ``suspect`` is the §6.7 flag raised after an abandoned stuck call. It is a
    distinct boolean (not folded into ``connection_health``) because §3 lists it
    separately and it drives distinct behaviour — the next op forces
    reconnect-and-verify.
    """

    connection_health: Literal["connected", "disconnected"]
    suspect: bool
    selection: SelectionChain
    template_text: str


# --- list_selection_options --------------------------------------------------


class SelectionOption(StrictModel):
    """One choice for the next unselected stage (§3).

    ``value`` is the token passed back to select(); ``display`` is the
    HFSS-sourced label (untrusted) for name-bearing stages; ``variation`` is
    populated only for the variation stage, reusing the Variation key.
    """

    value: str
    display: UntrustedStr | None = None
    variation: Variation | None = None


class SelectionOptions(StrictModel):
    """Options for the next unselected stage (§3). New: the §2 schemas have no
    "choices for a stage" concept."""

    stage: SelectionStage
    options: list[SelectionOption]
    template_text: str


# --- requests ----------------------------------------------------------------


class AttachRequest(StrictModel):
    process_id: int


class ListSelectionOptionsRequest(StrictModel):
    stage: SelectionStage


class SelectRequest(StrictModel):
    stage: SelectionStage
    choice: str


# --- response unions ---------------------------------------------------------
# preflight_environment -> PreflightReport and list_aedt_processes ->
# AedtProcessList have NO CannotEvaluate arm (see module docstring).
AttachResult = SessionStatus | CannotEvaluate
ListSelectionOptionsResult = SelectionOptions | CannotEvaluate
SelectResult = SessionStatus | CannotEvaluate
