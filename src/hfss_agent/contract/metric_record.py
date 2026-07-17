"""MetricRecord — one deterministic S-parameter metric with provenance (§2)."""

from hfss_agent.contract.common import StrictModel
from hfss_agent.contract.provenance_record import ProvenanceRecord


class MetricRecord(StrictModel):
    """A single Tier 1 metric value (§2 MetricRecord).

    ``formula_ref`` points into W-7's open, individually referenceable formula
    code (the Axis F evidence requirement's field 3); this is the mechanism
    that keeps every metric traceable to an open formula rather than an opaque
    number. ``gate_status_at_computation`` records that the validity gates had
    passed when the value was computed — metrics never exist without it (W-7
    refuses to run before gates pass).

    Variation is not duplicated here: it travels with the value through
    ``provenance`` (ProvenanceRecord.variation), the single standalone home
    §2 gives it besides the snapshot's selection.
    """

    metric_name: str
    value: float
    units: str
    formula_ref: str
    gate_status_at_computation: str
    provenance: ProvenanceRecord
