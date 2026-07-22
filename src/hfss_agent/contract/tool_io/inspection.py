"""Inspection tool I/O (§3): inspect_design."""

from typing import Annotated

from pydantic import Discriminator, Tag

from hfss_agent.contract.common import StrictModel
from hfss_agent.contract.design_snapshot import InspectionSection
from hfss_agent.contract.provenance_record import InspectionProvenance
from hfss_agent.contract.tool_io.common import (
    CannotEvaluate,
    InspectionSectionName,
    SelectionRefused,
    result_kind,
)


class InspectionResult(StrictModel):
    """inspect_design response (§3, W-5): the structured read-out, each section
    with read_status, all with provenance.

    Not DesignSnapshot.Inspection: that schema requires all eight sections (it
    is the snapshot's complete read-out — verified: every field there is
    required, no default). inspect_design accepts an optional ``sections``
    subset and must return only what was asked for, so this holds a dict keyed
    by section name over the reused InspectionSection building block — and adds
    the provenance §3 requires ("all with provenance"), which Inspection does
    not carry. The Literal key type means only real section names appear.

    That provenance is an InspectionProvenance, not a ProvenanceRecord: this
    read performs no solve, so it cannot honestly fill a record built for
    computed values (ADR-20, Option B, gap 11).
    """

    sections: dict[InspectionSectionName, InspectionSection]
    provenance: InspectionProvenance
    template_text: str


class InspectDesignRequest(StrictModel):
    """Optional subset; None (the default) means the full eight-section read-out."""

    sections: list[InspectionSectionName] | None = None


# Routed by the CALLABLE ``result_kind`` discriminator, like the other two
# session result unions (see result_kind's docstring): InspectionResult is a
# shared success shape and must NOT grow an ``outcome`` field, so success stays
# untagged. inspect's gates can refuse for any of the three remedies — no session,
# and (via _require_project_and_design) an incomplete selection; the ordering tag
# is carried too so all three session unions route one identical tag set.
InspectDesignResult = Annotated[
    Annotated[InspectionResult, Tag("success")]
    | Annotated[CannotEvaluate, Tag("cannot_evaluate")]
    | Annotated[SelectionRefused, Tag("refused_no_session")]
    | Annotated[SelectionRefused, Tag("refused_selection_order")]
    | Annotated[SelectionRefused, Tag("refused_incomplete_selection")],
    Discriminator(result_kind),
]
