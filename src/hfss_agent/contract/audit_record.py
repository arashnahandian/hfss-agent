"""AuditRecord — one append-only audit-log entry (§2).

Written only by the broker, one JSONL line per tool call. In the read-only MVP
"what did you change" is answered by construction — nothing — so this record's
job is to answer "what did you do" precisely.
"""

from datetime import datetime
from typing import Any

from hfss_agent.contract.common import AuditOutcome, RiskTier, StrictModel


class AuditRecord(StrictModel):
    """One audit-log entry (§2 AuditRecord).

    ``sanitized_arguments`` and ``selection_state`` are already sanitized by the
    broker before they land here; the schema carries them, it does not sanitize.
    ``snapshot_id`` is present only when the call emitted a snapshot.
    """

    timestamp: datetime
    tool_name: str
    sanitized_arguments: dict[str, Any]
    selection_state: dict[str, Any]
    risk_tier: RiskTier
    outcome: AuditOutcome
    duration: float
    snapshot_id: str | None = None
