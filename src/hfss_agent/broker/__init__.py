"""W-4 · broker — the capability broker (the load-bearing wall).

Sole gateway for every capability: routes all adapter calls, owns the action
allowlist and the three-tier risk taxonomy (safe/medium/high), performs ALL file
I/O for both units, and writes the append-only JSONL audit log. The engine is
never handed the broker or anything it guards.
"""

from hfss_agent.broker.audit import AuditLogWriter
from hfss_agent.broker.broker import (
    AuditFailure,
    AuditSink,
    Broker,
    BrokerOutcome,
    DispatchRefused,
    UnknownCapability,
    audit_capabilities,
    classify_outcome,
    intent_capabilities,
    session_routed_specs,
)
from hfss_agent.broker.confirmation import (
    ConfirmationRequest,
    Confirmer,
    RefuseAllConfirmer,
)
from hfss_agent.broker.files import BrokerFileError, IntentStore
from hfss_agent.broker.registry import CapabilityRegistry, CapabilitySpec

__all__ = [
    # dispatch core
    "Broker",
    "AuditSink",
    "classify_outcome",
    "session_routed_specs",
    "intent_capabilities",
    "audit_capabilities",
    # audit persistence
    "AuditLogWriter",
    # broker-domain outcomes
    "BrokerOutcome",
    "UnknownCapability",
    "DispatchRefused",
    "AuditFailure",
    # registry
    "CapabilityRegistry",
    "CapabilitySpec",
    # confirmation
    "ConfirmationRequest",
    "Confirmer",
    "RefuseAllConfirmer",
    # file surface
    "BrokerFileError",
    "IntentStore",
]
