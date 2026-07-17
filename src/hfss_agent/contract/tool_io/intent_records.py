"""Intent & records tool I/O (§3): set/get/clear_design_intent, get_audit_log,
export_diagnostics_bundle.

These are broker-owned tools. set/get/clear_design_intent and get_audit_log
never reach PyAEDT — the intent JSON and the audit log are broker-owned files —
so, unlike the adapter-backed tools, their responses have NO CannotEvaluate arm:
a broker file error is a typed *file* error, not a PyAEDT cannot_evaluate, and
offering the arm would misattribute the failure. export_diagnostics_bundle is
the one exception here: it is an export tool that gathers adapter-sourced
diagnostics, so it returns the shared ExportResult whose third arm IS
CannotEvaluate.
"""

from datetime import datetime

from hfss_agent.contract.audit_record import AuditRecord
from hfss_agent.contract.common import StrictModel
from hfss_agent.contract.intent_object import IntentObject

# set_design_intent takes an IntentObject directly as its request (reused as-is,
# no wrapper). set / get / clear all return DesignIntentState.


class DesignIntentState(StrictModel):
    """Current persisted design-intent state (§3 set/get/clear_design_intent).

    Reuses IntentObject, wrapping it as Optional so "not set" is a first-class
    value, not an error: a get before any set, and the state after a clear, both
    carry ``intent=None`` honestly.
    """

    intent: IntentObject | None = None
    template_text: str


class AuditLog(StrictModel):
    """get_audit_log response (§3): the append-only audit records. Thin named
    container over reused AuditRecord."""

    records: list[AuditRecord]
    template_text: str


class AuditLogRange(StrictModel):
    """Optional filter for get_audit_log (§3 "range?"): a time window and/or a
    cap on the most-recent records. All optional; None everywhere means the
    whole log."""

    start: datetime | None = None
    end: datetime | None = None
    limit: int | None = None


class GetAuditLogRequest(StrictModel):
    range: AuditLogRange | None = None


class ExportDiagnosticsBundleRequest(StrictModel):
    path: str
    overwrite: bool = False
