"""The MCP application object (W-1, Step 2.8): tools registered onto ``MCPServer``.

SCAFFOLDING ONLY -- the charter's phrase, and this module is where it is easiest
to violate. Every handler below is the same three lines and no more:

    1. build the contract request type from the arguments (it validates),
    2. call exactly ONE thing below this layer,
    3. return what it returned.

NOTHING ELSE IS PERMITTED HERE, and the rule is worth stating as a prohibition
rather than a style note. A handler must not branch on a result, build a string
from one, iterate findings, or substitute a default for a value a module
declined to produce. Every one of those is a decision about what to report, and
every module below owns its own decisions and has tests pinning them. A decision
taken here would be a SECOND answer to a question already answered, in the one
layer with no domain tests behind it.

WHERE THAT RULE BIT, AND WHAT IT TOLD US. ``validate_setup`` cannot be
registered under it: composing its ``ValidationReport`` needs a branch on which
union arm W-6 returned plus three judgments that ``findings/render.py`` and
``validate_native/assembler.py`` both assign to Step 3.3. That is the boundary
working -- the tool defers rather than the rule bending. See ``tool_surface``.

REQUEST TYPES ARE CONSTRUCTED, NOT JUST ANNOTATED. The SDK already derives an
input schema from each handler's signature, so building e.g. ``AttachRequest``
looks redundant. It is not: it makes the contract LOAD-BEARING rather than
decorative. Field names, Literal domains and ``extra="forbid"`` are then
enforced by the schema the contract owns, and a contract rename breaks these
handlers loudly instead of leaving the tool surface quietly describing a shape
the contract no longer has.

TWO HANDLERS NEED A VALUE NO TOOL ARGUMENT CARRIES -- ``preflight_environment``
needs the machine probes and ``export_diagnostics_bundle`` needs the registered
tool names. Both are CLOSED OVER from the composition rather than derived here.
Deriving either would be this layer deciding something: which probes count, or
what the tool surface is. Passing them through keeps the decision where it was
already made -- at composition -- and keeps the handler a call and a return.

THE SAME RULE APPLIES TO THE HANDSHAKE VERSION, and it took a second reader to
notice. This module briefly carried its own ``importlib.metadata`` lookup for
the server version -- a value ``preflight.probes`` already owns. The two agreed
on a healthy install and diverged on every failure: different placeholders for
a missing distribution, ``None`` where the probe gives a string, and an
UNCAUGHT EXCEPTION -- a server that would not start -- where the probe returns
the placeholder. The version now comes from ``REAL_PROBES`` like everything
else about the environment.

EVERY TOOL IS WRAPPED IN ``serialized`` and every tool has a row in
``tool_surface`` declaring its risk tier. Two reflection tests enforce both, with
no exemption list on either.

A WIRE-SHAPE ASYMMETRY THE RETURN ANNOTATIONS DO NOT REVEAL, recorded because it
is invisible from this file and will trip the next person who asserts against a
tool's output. The SDK derives each tool's structured content from its return
annotation, and it treats a UNION return differently from a single model:

    attach              -> AttachResult (a union)  -> {"result": {...}}
    get_session_status  -> SessionStatus (a model) -> {"connection_health": ..., ...}

So roughly half this surface nests its payload under ``result`` and half is flat,
purely according to whether the contract type is a union. That is the SDK's
behaviour, not a choice made here, and absorbing it is correct -- inventing a
uniform envelope would mean this layer reshaping a response, which is exactly
what it must not do. But a test (or a consumer) reading ``structured_content``
has to handle both shapes, and nothing in the signatures below says so.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from hfss_agent.contract import IntentObject, ThresholdType
from hfss_agent.contract.tool_io import (
    AttachRequest,
    AttachResult,
    AuditLog,
    AuditLogRange,
    DesignIntentState,
    ExportDiagnosticsBundleRequest,
    ExportResult,
    GetAuditLogRequest,
    InspectDesignRequest,
    InspectDesignResult,
    InspectionSectionName,
    ListSelectionOptionsRequest,
    ListSelectionOptionsResult,
    PreflightReport,
    SelectionStage,
    SelectRequest,
    SelectResult,
    SessionStatus,
)
from hfss_agent.inspect import inspect_design as assemble_inspection
from hfss_agent.preflight import REAL_PROBES
from hfss_agent.preflight import export_diagnostics_bundle as assemble_bundle
from hfss_agent.preflight import preflight_environment as assemble_preflight
from hfss_agent.server.adapter_selection import FAKE
from hfss_agent.server.composition import Composition
from hfss_agent.server.serialization import serialized
from hfss_agent.server.tool_surface import TOOL_SURFACE

_SERVER_NAME = "hfss-agent"

# Appended to the server name when the simulated backend is in use. Short,
# because a client renders the name in constrained places, and upper-case
# because it is the only part of the name a human is meant to notice.
_FAKE_NAME_SUFFIX = " (SIMULATED)"

# Handed to the client at initialize. THIS IS A DISCLOSURE, NOT A GUARD, and the
# wording is careful about the difference for a reason.
#
# A disclosure tells the host something true and hopes it is surfaced. It cannot
# enforce anything: the host may render `instructions`, summarise it, or ignore
# it entirely, and nothing downstream is changed by its presence. In particular
# -- and this is the sentence that must not be softened -- the VALUES this
# server returns while simulated are NOT marked, NOT flagged, and NOT
# distinguishable from live ones by any field of any response.
_FAKE_INSTRUCTIONS = (
    "SIMULATED DATA. This server was started with --adapter fake and is NOT "
    "connected to Ansys HFSS. Every value it returns -- versions, project and "
    "design names, validation messages, solve state, S-parameters, metrics -- "
    "is canned test data invented by this package. None of it was measured from "
    "any design.\n\n"
    "Do not report any value from this server as a measurement, a simulation "
    "result, or a property of a real design, and do not use it to answer a "
    "question about real hardware.\n\n"
    "This notice is the ONLY indication that the data is simulated. Individual "
    "responses carry no marker: their fields, provenance stamps and environment "
    "versions are indistinguishable from a live session's. If this notice is "
    "not carried forward into the conversation, nothing later will reveal it."
)

# The live counterpart. Deliberately does NOT claim the data is verified or
# correct -- it states what the connection is, and nothing more.
_LIVE_INSTRUCTIONS = (
    "Read-only, attach-only access to a running Ansys HFSS (AEDT) session on "
    "this machine. Values are read from that session or computed by this "
    "package's open, referenceable formulas; where something cannot be read or "
    "evaluated, the response says so rather than estimating."
)


def _describe(name: str) -> str:
    """The registered description for ``name``, from its ``tool_surface`` row.

    Read from the table rather than written at the registration site so the
    description a client sees and the summary the accounting table carries
    cannot drift. A name with no row is a programming error and says so.
    """
    for binding in TOOL_SURFACE:
        if binding.name == name:
            return binding.summary
    raise KeyError(
        f"no tool_surface row for {name!r}; every registered tool must be "
        "accounted for there (ADR-33)."
    )


def build_app(composition: Composition, *, adapter_kind: str) -> MCPServer:
    """The configured ``MCPServer``, with no transport started.

    Args:
        composition: the wired object graph. Taken explicitly rather than built
            here, so a test can stand the app up against a ``FakeAdapter``
            composition without touching the default data directory.
        adapter_kind: ``LIVE`` or ``FAKE`` -- which backend ``composition`` was
            built over. KEYWORD-ONLY AND UNDEFAULTED, because a default would
            mean a caller could omit it and get the live wording over a fake
            adapter, which is the one combination that must be impossible to
            reach by accident.

    Building the app performs no I/O and no adapter round trip.
    """
    simulated = adapter_kind == FAKE
    server = MCPServer(
        name=_SERVER_NAME + (_FAKE_NAME_SUFFIX if simulated else ""),
        # READ THROUGH THE PROBE, not by a local ``importlib.metadata``
        # call. W-11 already owns "what version is this package" and keeps
        # a three-state read behind it, so a damaged or version-less
        # ``.dist-info`` yields the established ``0.0.0`` placeholder
        # instead of ``None`` or an exception that would take the whole
        # server down at startup. A second reader here was measured to do
        # both, and to disagree with the ``wrapper_version`` that
        # ``preflight_environment`` reports in the same session.
        version=REAL_PROBES.wrapper_version(),
        instructions=_FAKE_INSTRUCTIONS if simulated else _LIVE_INSTRUCTIONS,
    )
    broker = composition.broker

    # --- preflight ------------------------------------------------------------

    @server.tool(
        name="preflight_environment",
        description=_describe("preflight_environment"),
    )
    @serialized
    def preflight_environment() -> PreflightReport:
        # REAL_PROBES is closed over, not chosen here: which reads count as the
        # machine's environment is preflight's decision, already made.
        return assemble_preflight(REAL_PROBES, broker)

    # --- session lifecycle ----------------------------------------------------

    @server.tool(name="attach", description=_describe("attach"))
    @serialized
    def attach(process_id: int) -> AttachResult:
        request = AttachRequest(process_id=process_id)
        return broker.dispatch("attach", {"process_id": request.process_id})

    @server.tool(
        name="list_selection_options", description=_describe("list_selection_options")
    )
    @serialized
    def list_selection_options(stage: SelectionStage) -> ListSelectionOptionsResult:
        request = ListSelectionOptionsRequest(stage=stage)
        return broker.dispatch("list_selection_options", {"stage": request.stage})

    @server.tool(name="select", description=_describe("select"))
    @serialized
    def select(stage: SelectionStage, choice: str) -> SelectResult:
        request = SelectRequest(stage=stage, choice=choice)
        return broker.dispatch(
            "select", {"stage": request.stage, "choice": request.choice}
        )

    @server.tool(name="get_session_status", description=_describe("get_session_status"))
    @serialized
    def get_session_status() -> SessionStatus:
        return broker.dispatch("get_session_status", {})

    # --- inspection -----------------------------------------------------------

    @server.tool(name="inspect_design", description=_describe("inspect_design"))
    @serialized
    def inspect_design(
        sections: list[InspectionSectionName] | None = None,
    ) -> InspectDesignResult:
        request = InspectDesignRequest(sections=sections)
        # The W-5 ASSEMBLER, not the capability of the same name -- see
        # tool_surface for why one spelling means three things.
        return assemble_inspection(broker, request.sections)

    # --- design intent --------------------------------------------------------

    @server.tool(name="set_design_intent", description=_describe("set_design_intent"))
    @serialized
    def set_design_intent(
        target_frequency_hz: float,
        threshold_type: ThresholdType,
        threshold_value: float,
    ) -> DesignIntentState:
        # ANNOTATED WITH THE CONTRACT'S OWN LITERAL, not a bare ``str``. The SDK
        # derives each tool's input schema from these annotations, so this is
        # what puts {"enum": ["s11", "vswr"]} in front of the caller BEFORE they
        # call. Measured: with ``str`` here the schema carried no enum and
        # threshold_type="bogus" reached the handler, failing only as a pydantic
        # error after dispatch -- a worse experience for the same rejection.
        #
        # §3 reuses IntentObject as the request as-is, so this IS the request
        # type; constructing it stays the enforcement, with the annotation as
        # the advertisement.
        request = IntentObject(
            target_frequency_hz=target_frequency_hz,
            threshold_type=threshold_type,
            threshold_value=threshold_value,
        )
        return broker.dispatch(
            "set_design_intent",
            {
                "target_frequency_hz": request.target_frequency_hz,
                "threshold_type": request.threshold_type,
                "threshold_value": request.threshold_value,
            },
        )

    @server.tool(name="get_design_intent", description=_describe("get_design_intent"))
    @serialized
    def get_design_intent() -> DesignIntentState:
        return broker.dispatch("get_design_intent", {})

    @server.tool(
        name="clear_design_intent", description=_describe("clear_design_intent")
    )
    @serialized
    def clear_design_intent() -> DesignIntentState:
        return broker.dispatch("clear_design_intent", {})

    # --- records --------------------------------------------------------------

    @server.tool(name="get_audit_log", description=_describe("get_audit_log"))
    @serialized
    def get_audit_log(range: AuditLogRange | None = None) -> AuditLog:  # noqa: A002
        # The field is literally named "range" (§3 GetAuditLogRequest), so the
        # dispatch kwarg must carry that name.
        request = GetAuditLogRequest(range=range)
        return broker.dispatch("get_audit_log", {"range": request.range})

    @server.tool(
        name="export_diagnostics_bundle",
        description=_describe("export_diagnostics_bundle"),
    )
    @serialized
    def export_diagnostics_bundle(path: str, overwrite: bool = False) -> ExportResult:
        request = ExportDiagnosticsBundleRequest(path=path, overwrite=overwrite)
        # known_tool_names comes from the composition that BUILT the registry --
        # closed over, not derived here. W-11 documents it as "supplied by the
        # site that BUILT the registry"; deriving it here would be this layer
        # deciding what the tool surface is.
        return assemble_bundle(
            request.path,
            REAL_PROBES,
            composition.known_tool_names(),
            broker,
            overwrite=request.overwrite,
        )

    return server


__all__ = ["build_app"]
