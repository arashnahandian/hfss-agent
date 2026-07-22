"""AuditRecord — one append-only audit-log entry (§2).

Written only by the broker, one JSONL line per broker dispatch attempt —
including a dispatch of an unregistered capability name (gap 9, amended). In
the read-only MVP "what did you change" is answered by construction — nothing
— so this record's job is to answer "what did you do" precisely.
"""

from datetime import datetime
from typing import Any

from pydantic import model_validator

from hfss_agent.contract.common import AuditOutcome, RiskTier, StrictModel


class AuditRecord(StrictModel):
    """One audit-log entry (§2 AuditRecord).

    ``sanitized_arguments`` and ``selection_state`` are already sanitized by the
    broker before they land here; the schema carries them, it does not sanitize.
    ``snapshot_id`` is present only when the call emitted a snapshot.

    ``risk_tier`` is ``None`` for exactly one thing: a dispatch of a name the
    registry does not hold, which has no tier to state and must not be given a
    fabricated one ("safe" would be a false claim about an unknown thing;
    "high" would pollute the high-tier refusal trail). That case is paired with
    ``outcome="unknown_capability"`` and enforced BOTH ways below.

    ``session_degraded`` answers one question and only that one: *did this call
    worsen the session?* It is a DELTA over the health rank
    (clean < suspect < lost) taken before and after the handler, not a reading
    of the post-state alone — a plain post-state boolean would miss a
    SUSPECT -> LOST transition, since both ends read "degraded". ``None`` means
    inapplicable: no handler ran (a tier refusal, an unregistered name), so
    there was nothing that could have worsened it. A call that RUNS against an
    already-lost session and is refused reports ``False``, which is the honest
    answer to "did this call worsen it" — that the op met a dead session is
    already on the record as its ``refused_by_gate`` outcome, and this field
    does not double-report it.
    """

    timestamp: datetime
    tool_name: str
    sanitized_arguments: dict[str, Any]
    selection_state: dict[str, Any]
    risk_tier: RiskTier | None
    outcome: AuditOutcome
    duration: float
    snapshot_id: str | None = None
    session_degraded: bool | None = None

    @model_validator(mode="after")
    def _tier_absent_iff_capability_unknown(self) -> "AuditRecord":
        """BOTH-OR-NEITHER, enforced in both directions (gap 9).

        Either half alone would let the log misstate what happened, so neither
        is optional:

          * ``risk_tier=None`` with any other outcome would mean a REGISTERED
            capability was dispatched and its tier went unrecorded — the log
            would no longer say what guard set the call ran under.
          * ``outcome="unknown_capability"`` with a tier would mean the log
            invented a tier for a capability that has none, which is exactly
            the fabrication the None was introduced to avoid.

        A ``ValueError`` here surfaces as a pydantic ``ValidationError``, so a
        record violating this never reaches the log AND a corrupted on-disk
        line carrying the violation is caught by the reader rather than
        silently believed.
        """
        unknown = self.outcome == "unknown_capability"
        if unknown and self.risk_tier is not None:
            raise ValueError(
                "AuditRecord.outcome 'unknown_capability' requires "
                f"risk_tier=None; got {self.risk_tier!r}. An unregistered "
                "capability has no tier, and stating one would be a fabricated "
                "claim about an unknown thing."
            )
        if not unknown and self.risk_tier is None:
            raise ValueError(
                "AuditRecord.risk_tier=None is permitted only with "
                f"outcome='unknown_capability'; got {self.outcome!r}. A "
                "registered capability always dispatches under a declared "
                "tier, and the log must record which."
            )
        return self
