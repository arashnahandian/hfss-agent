"""Audit-log reader (W-4, Part 4): JSONL back to ``AuditRecord``, with
``AuditLogRange`` filtering.

The read-only MVP answers "what did you change?" by construction — nothing —
so the log carries the ENTIRE burden of "what did you do?", and a reader that
silently drops a record makes the log lie by looking complete.

TWO DEFECTS shaped the corrected policy here (ADR-19). The original Part 4
policy made a malformed NON-final line fatal, reasoning that it proved a
completed record was corrupted. That conflated POSITION IN THE FILE with
CAUSE: a crash mid-append leaves a torn stub, and the moment one more append
lands, the same benign crash artifact simply stops being final — so a single
crash permanently bricked ``get_audit_log`` until someone hand-edited JSONL.
Self-defeating for the file that answers "what did you do?". The defects:
(1) record MERGING — the stub had no trailing newline, so the next append
destroyed a successfully-audited record (fixed by the writer's newline
guard); (2) the FATAL interior arm, fixed here.

The corrected two-arm policy: BOTH arms return data, NEITHER is silent, and
they stay distinct in what they say:

  * a malformed FINAL line is the expected crash-mid-append artifact — "the
    last record was mid-write when something stopped". Benign: surfaced as
    ``torn_tail`` and a truncation notice in the response template.
  * a malformed INTERIOR line is real damage to the record stream — "record N
    is corrupt; treat this log as incomplete". Alarming: surfaced with its
    line number in ``corrupt_lines`` and an unmissable warning in the
    template. Loud but NON-FATAL, deliberately: the lie only happens on a
    SILENT skip. Refusing to return 89 valid records because record 41 is
    corrupt does not protect accountability, it eliminates it — failing
    closed in the wrong direction, since the consumer is a human reading
    history, not code about to act on the data.

A MISSING file is the honest first-class "no calls logged yet" state — an
empty result, not an error (the same stance as the intent store's missing
file -> ``intent=None``). An UNREADABLE file (permissions, I/O) is still a
typed ``BrokerFileError``: that is an access failure, not a corrupt line.

Range semantics: ``start``/``end`` bound ``timestamp`` inclusively; ``limit``
caps the MOST-RECENT records (§3) after the time filter. Records are written
aware-UTC; a NAIVE caller-supplied bound is read as UTC — contract gap 5,
pending amendment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import ValidationError

from hfss_agent.broker.files.errors import BrokerFileError
from hfss_agent.contract import AuditRecord
from hfss_agent.contract.tool_io import AuditLogRange


@dataclass(frozen=True)
class AuditReadResult:
    """What a read yields: the (filtered) surviving records, the benign
    torn-tail flag, and the alarming 1-indexed interior corrupt-line numbers
    — the response template must surface both notices distinctly."""

    records: tuple[AuditRecord, ...]
    torn_tail: bool
    corrupt_lines: tuple[int, ...]


def read_audit_records(
    path: str, log_range: AuditLogRange | None = None
) -> AuditReadResult:
    """Read and filter the audit log per the module-docstring policy: every
    well-formed record is returned; malformed lines are reported, never
    silently skipped, and never fatal."""
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        return AuditReadResult(records=(), torn_tail=False, corrupt_lines=())
    except OSError as exc:
        raise BrokerFileError(
            path,
            f"the audit log could not be read: {type(exc).__name__}: {exc}",
        ) from exc

    parsed: list[AuditRecord] = []
    torn_tail = False
    corrupt: list[int] = []
    for index, line in enumerate(lines):
        try:
            parsed.append(AuditRecord.model_validate_json(line))
        except ValidationError:
            if index == len(lines) - 1:
                # The expected crash-mid-append artifact: benign, surfaced.
                torn_tail = True
            else:
                # Real damage to the record stream: alarming, surfaced — and
                # the surviving records are still returned (ADR-19 fix 2).
                corrupt.append(index + 1)
    return AuditReadResult(
        records=_filtered(parsed, log_range),
        torn_tail=torn_tail,
        corrupt_lines=tuple(corrupt),
    )


def _as_utc(moment: datetime) -> datetime:
    """A naive caller-supplied bound is read as UTC (contract gap 5): records
    are written aware-UTC, and comparing naive against aware would raise."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _filtered(
    records: list[AuditRecord], log_range: AuditLogRange | None
) -> tuple[AuditRecord, ...]:
    if log_range is None:
        return tuple(records)
    kept = records
    if log_range.start is not None:
        start = _as_utc(log_range.start)
        kept = [record for record in kept if record.timestamp >= start]
    if log_range.end is not None:
        end = _as_utc(log_range.end)
        kept = [record for record in kept if record.timestamp <= end]
    if log_range.limit is not None:
        if log_range.limit < 0:
            # The contract does not constrain limit; a negative cap has no
            # honest meaning, so it is refused rather than guessed at.
            raise ValueError("AuditLogRange.limit must be non-negative")
        # "Cap on the most-recent records" (§3): keep the LAST limit entries.
        kept = kept[max(len(kept) - log_range.limit, 0) :] if log_range.limit else []
    return tuple(kept)
