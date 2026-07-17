"""ProvenanceRecord — attached to every metric and finding (§2, spec Point 4)."""

from datetime import datetime

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
