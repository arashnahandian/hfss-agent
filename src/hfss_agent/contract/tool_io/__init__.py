"""Tool I/O schemas for the 17 MCP tools (§3), grouped the way §3 groups them.

Import-clean like the rest of ``contract`` (ADR-3): importing this subpackage
must not pull in ``pyaedt`` or anything I/O-capable. Requests, responses,
response unions, and the shared result shapes for every tool live here.

Response-shape conventions:
  * every top-level tool response carries ``template_text`` — §3's deterministic
    core text, complete without any LLM;
  * the adapter-backed tools return ``<Result> | CannotEvaluate``; the
    broker-owned record tools do not (see intent_records);
  * the session tools that can be refused BEFORE reaching PyAEDT (select,
    list_selection_options, inspect_design) carry a ``SelectionRefused`` arm as
    well, routed by the callable ``result_kind`` discriminator so their shared
    success types keep their untagged wire format;
  * compute_metrics and export_* return discriminated unions whose wrong states
    are structurally unconstructible.
"""

from hfss_agent.contract.tool_io.common import (
    CannotEvaluate,
    EngineStatus,
    ExportFailed,
    ExportFormat,
    ExportRefused,
    ExportResult,
    ExportWritten,
    InspectionSectionName,
    SelectionRefused,
    SelectionStage,
    result_kind,
)
from hfss_agent.contract.tool_io.inspection import (
    InspectDesignRequest,
    InspectDesignResult,
    InspectionResult,
)
from hfss_agent.contract.tool_io.intent_records import (
    AuditLog,
    AuditLogRange,
    DesignIntentState,
    ExportDiagnosticsBundleRequest,
    GetAuditLogRequest,
)
from hfss_agent.contract.tool_io.preflight_session import (
    AedtProcess,
    AedtProcessList,
    AttachRequest,
    AttachResult,
    ComponentCheck,
    ListSelectionOptionsRequest,
    ListSelectionOptionsResult,
    PreflightReport,
    SelectionChain,
    SelectionOption,
    SelectionOptions,
    SelectRequest,
    SelectResult,
    SessionStatus,
)
from hfss_agent.contract.tool_io.validation import (
    ValidateSetupRequest,
    ValidateSetupResult,
    ValidationReport,
)
from hfss_agent.contract.tool_io.verified_results import (
    CheckSolutionValidityRequest,
    CheckSolutionValidityResult,
    ComputeMetricsRequest,
    ComputeMetricsResult,
    ExportResultsRequest,
    MetricsComputed,
    MetricsRefused,
    SolutionValidityReport,
    SolveHealthReport,
    SolveHealthResult,
)

__all__ = [
    # Cross-cutting shared shapes and §3 enumerations
    "CannotEvaluate",
    "EngineStatus",
    "ExportFailed",
    "ExportFormat",
    "ExportRefused",
    "ExportResult",
    "ExportWritten",
    "InspectionSectionName",
    "SelectionRefused",
    "SelectionStage",
    "result_kind",
    # Preflight & session
    "AedtProcess",
    "AedtProcessList",
    "AttachRequest",
    "AttachResult",
    "ComponentCheck",
    "ListSelectionOptionsRequest",
    "ListSelectionOptionsResult",
    "PreflightReport",
    "SelectRequest",
    "SelectResult",
    "SelectionChain",
    "SelectionOption",
    "SelectionOptions",
    "SessionStatus",
    # Inspection
    "InspectDesignRequest",
    "InspectDesignResult",
    "InspectionResult",
    # Validation
    "ValidateSetupRequest",
    "ValidateSetupResult",
    "ValidationReport",
    # Verified results
    "CheckSolutionValidityRequest",
    "CheckSolutionValidityResult",
    "ComputeMetricsRequest",
    "ComputeMetricsResult",
    "ExportResultsRequest",
    "MetricsComputed",
    "MetricsRefused",
    "SolutionValidityReport",
    "SolveHealthReport",
    "SolveHealthResult",
    # Intent & records
    "AuditLog",
    "AuditLogRange",
    "DesignIntentState",
    "ExportDiagnosticsBundleRequest",
    "GetAuditLogRequest",
]
