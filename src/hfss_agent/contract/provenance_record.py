"""Provenance schemas.

``ProvenanceRecord`` — attached to every metric and finding (§2, spec Point 4).
``InspectionProvenance`` — the structural-read counterpart, for tool results
that were produced without a solve behind them.
"""

from datetime import datetime

from pydantic import AwareDatetime

from hfss_agent.contract.common import StrictModel, UntrustedStr, Variation


class ProvenanceRecord(StrictModel):
    """Full provenance for a computed value or finding (§2 ProvenanceRecord).

    Carries the ``variation`` key so every metric and finding is
    self-describing for the exact variation it was produced under — no need to
    reach back into the snapshot to know which point in the design space a
    value belongs to.

    ``engine_version`` and ``rule_version`` are optional: native-validation and
    gate provenance, and metric provenance, have no engine or supplemental rule
    behind them, so those slots are legitimately empty there.
    """

    project: UntrustedStr
    design: UntrustedStr
    solution_type: str
    setup: str
    sweep: str
    variation: Variation
    expression: str
    reference_impedance: float
    solve_timestamp: datetime
    freshness_status: str
    snapshot_id: str
    contract_version: str
    wrapper_version: str
    engine_version: str | None = None
    rule_version: str | None = None


class InspectionProvenance(StrictModel):
    """Honest provenance for a structural design read (ADR-20, Option B, gap 11).

    A structural read performs no solve, so there is no setup, sweep, variation,
    expression, reference impedance, solve timestamp, freshness status, or
    engine/rule version to report — and no computed value or judgment for them
    to stand behind. Filling a ProvenanceRecord for such a read would mean
    inventing those fields or leaving them empty-but-declared; either way the
    record would assert more than the read actually knows. This type carries no
    solve, metric, or judgment field by construction, so it cannot make a claim
    it has not earned.

    It deliberately shares no base class with ProvenanceRecord (Option B chose a
    separate type over widening ProvenanceRecord, and no mixin was introduced
    between them). The two are independent: their kinship is only the identical
    ``project``/``design`` field names and types, and nothing may come to depend
    on them staying aligned. A future field on one is not a field on the other.
    """

    project: UntrustedStr
    design: UntrustedStr
    # The UTC instant W-5 performed the atomic inspection read. AwareDatetime,
    # not datetime: a naive value is rejected rather than silently read as local
    # time, so "when was this read" is never ambiguous by an offset.
    read_at: AwareDatetime
    contract_version: str
    wrapper_version: str
    # The AEDT version of the attached process, read at attach time. "Read
    # under" is the honest framing: a process's AEDT version cannot change
    # without a new process, and every re-attach re-reads it — so this states
    # the version the read happened under, not the version the design was
    # authored in (which is not readable on a read-only path). Plain str, not
    # UntrustedStr: it is solver-reported via the attached Desktop, not sourced
    # from the HFSS design, matching Environment.aedt_version's precedent. The
    # value is supplied by the W-5 assembler, like contract_version.
    read_under_aedt_version: str
