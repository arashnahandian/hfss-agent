"""W-12 · contract — public Pydantic schemas (import-clean subpackage).

Importing this subpackage must never pull in ``pyaedt`` or anything I/O-capable;
the purity test in CI is load-bearing (ADR-3). The engine and ``gating`` depend
on it without tripping the import audit.

The six data-model schemas of System Design §2 live here, one file per schema,
with shared primitives (the ``Variation`` key and §2's enumerated value sets) in
``common``.
"""

from hfss_agent.contract.audit_record import AuditRecord
from hfss_agent.contract.common import (
    CONTRACT_VERSION,
    AuditOutcome,
    ConvergenceStatus,
    FindingClassification,
    FindingOutcome,
    FindingSource,
    NativeValidationUnavailableReason,
    ReadStatus,
    RiskTier,
    SolveDataUnavailableReason,
    StrictModel,
    ThresholdType,
    UntrustedStr,
    Variation,
)
from hfss_agent.contract.design_snapshot import (
    ComplexSample,
    DesignSnapshot,
    Environment,
    FreshnessEvidence,
    Inspection,
    InspectionSection,
    NativeValidation,
    NativeValidationUnavailable,
    Project,
    Selection,
    SolutionExists,
    SolveDataUnavailable,
    SolvedData,
    SolveState,
)
from hfss_agent.contract.finding import Applicability, Finding
from hfss_agent.contract.intent_object import IntentObject
from hfss_agent.contract.metric_record import MetricRecord
from hfss_agent.contract.provenance_record import (
    InspectionProvenance,
    NativeValidationProvenance,
    ProvenanceRecord,
)

__all__ = [
    # Six §2 schemas
    "DesignSnapshot",
    "Finding",
    "ProvenanceRecord",
    "MetricRecord",
    "IntentObject",
    "AuditRecord",
    # Shared primitives and §2 enumerations
    "CONTRACT_VERSION",
    "Variation",
    "StrictModel",
    "UntrustedStr",
    "ReadStatus",
    "ConvergenceStatus",
    "FindingSource",
    "FindingOutcome",
    "FindingClassification",
    "ThresholdType",
    "RiskTier",
    "AuditOutcome",
    "SolveDataUnavailableReason",
    "NativeValidationUnavailableReason",
    # DesignSnapshot sub-models
    "Environment",
    "Project",
    "Selection",
    "Inspection",
    "InspectionSection",
    "NativeValidation",
    "FreshnessEvidence",
    "SolutionExists",
    "SolveState",
    "ComplexSample",
    "SolvedData",
    # Absence arms: why a snapshot carries no solve data / no native validation
    # (ADR-28). Two independent types, never a shared vocabulary.
    "SolveDataUnavailable",
    "NativeValidationUnavailable",
    # Finding sub-model
    "Applicability",
    # Provenance for a structural read, which has no solve behind it (ADR-20)
    "InspectionProvenance",
    # Provenance for a native validation run, which has neither a solve nor a
    # calculation of ours behind it (ADR-23)
    "NativeValidationProvenance",
]
