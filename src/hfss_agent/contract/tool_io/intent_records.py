"""Intent & records tool I/O (§3): set/get/clear_design_intent, get_audit_log,
export_diagnostics_bundle.

These are broker-owned tools. set/get/clear_design_intent and get_audit_log
never reach PyAEDT — the intent JSON and the audit log are broker-owned files —
so, unlike the adapter-backed tools, their responses have NO CannotEvaluate arm:
a broker file error is a typed *file* error, not a PyAEDT cannot_evaluate, and
offering the arm would misattribute the failure. export_diagnostics_bundle is
the one exception here: it is an export tool that gathers adapter-sourced
diagnostics, so it returns the shared ExportResult, one of whose FOUR arms is
CannotEvaluate.

Those four arms are ExportWritten, ExportRefused, ExportFailed and
CannotEvaluate. This paragraph said "three-armed" and named CannotEvaluate as
"the third arm" until Step 2.4a corrected it: ExportFailed was added by the
first contract amendment and two docstrings were not updated with it. The count
matters here rather than being pedantry — the missing arm is precisely the one
distinguishing a write REFUSED before the disk was touched from one that BROKE
mid-operation and may have left an orphaned temp behind, and a reader who
believes there are three arms will not look for that distinction.
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
    container over reused AuditRecord, plus the two completeness flags.

    ``torn_tail`` and ``corrupt_lines`` (gap 10, amended) make INCOMPLETENESS
    machine-readable. The reader has always computed both — the response simply
    discarded them, leaving prose in ``template_text`` as the only carrier, so a
    programmatic consumer had to string-match a warning to learn the log is not
    whole. They COMPLEMENT the prose rather than replace it: the two conditions
    mean very different things and the template still says so in words.

      * ``torn_tail`` — the final line was still mid-write when something
        stopped (typically a crash). Benign and expected; that partial entry is
        unreadable and not included.
      * ``corrupt_lines`` — 1-indexed line numbers of malformed INTERIOR lines.
        Alarming: real damage to the record stream. A non-empty tuple means the
        surviving records are returned but completeness cannot be vouched for.

    Both default to the "log is whole" values, so a reader that ignores them
    behaves exactly as before.
    """

    records: list[AuditRecord]
    template_text: str
    torn_tail: bool = False
    corrupt_lines: tuple[int, ...] = ()


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
