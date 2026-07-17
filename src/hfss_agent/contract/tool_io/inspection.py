"""Inspection tool I/O (§3): inspect_design."""

from hfss_agent.contract.common import StrictModel
from hfss_agent.contract.design_snapshot import InspectionSection
from hfss_agent.contract.provenance_record import ProvenanceRecord
from hfss_agent.contract.tool_io.common import CannotEvaluate, InspectionSectionName


class InspectionResult(StrictModel):
    """inspect_design response (§3, W-5): the structured read-out, each section
    with read_status, all with provenance.

    Not DesignSnapshot.Inspection: that schema requires all eight sections (it
    is the snapshot's complete read-out — verified: every field there is
    required, no default). inspect_design accepts an optional ``sections``
    subset and must return only what was asked for, so this holds a dict keyed
    by section name over the reused InspectionSection building block — and adds
    the ProvenanceRecord §3 requires ("all with provenance"), which Inspection
    does not carry. The Literal key type means only real section names appear.
    """

    sections: dict[InspectionSectionName, InspectionSection]
    provenance: ProvenanceRecord
    template_text: str


class InspectDesignRequest(StrictModel):
    """Optional subset; None (the default) means the full eight-section read-out."""

    sections: list[InspectionSectionName] | None = None


InspectDesignResult = InspectionResult | CannotEvaluate
