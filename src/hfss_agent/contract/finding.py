"""Finding — the seven-field evidence superset (§2).

One schema serves the wrapper's TWO judgment sources: gate results and engine
rules. Native HFSS validation is deliberately NOT one of them (ADR-23). A
ValidateDesign message is not a Finding and cannot be made into one — we own no
rule id, rule version, calculation, or machine-checked applicability behind it,
so most of the fields below would have to be faked to carry it. Native output
travels as its own structural block (``tool_io.NativeValidationBlock``), and
``FindingSource`` no longer carries ``hfss_native``. §2 still describes one
schema for three sources and is being edited to match.

Because no native source exists, W-10's receipt gate is UNCONDITIONAL: a
finding missing any required field is rejected as malformed on receipt and
never displayed, with no source for which that check could be relaxed and no
call site that could forget to apply it. Pydantic's required-field validation
is exactly that gate, which is why the schema-rejection suite is load-bearing.
"""

from typing import Any

from hfss_agent.contract.common import (
    FindingClassification,
    FindingOutcome,
    FindingSource,
    StrictModel,
)
from hfss_agent.contract.provenance_record import ProvenanceRecord


class Applicability(StrictModel):
    """The machine-checked applicability conditions and whether they held (§2
    Finding — Honesty).

    Variation is not duplicated here: the finding's variation travels through
    its ``provenance`` (ProvenanceRecord.variation).
    """

    conditions: dict[str, Any]
    held: bool


class Finding(StrictModel):
    """A single finding from either of its two sources — a gate result or an
    engine rule (§2 Finding). ADR-23 removed the third, native source; see the
    module docstring for why a native message cannot be one of these.

    ``outcome`` (the five states) and ``classification`` (error/warning/
    judgment_call, field 6) are deliberately two distinct required fields — the
    five-state honesty and the coarse severity classification are different
    axes and must not collapse into one.
    """

    # Identity — required evidence group 1
    finding_id: str
    source: FindingSource
    rule_id: str
    rule_version: str  # field 5
    rule_purpose: str  # public one-liner

    # Evidence — fields 1-4
    inspected: list[str]  # field 1: snapshot elements consumed
    observed_values: dict[str, Any]  # field 2
    calculation_ref: str  # field 3: reference into the open formula code
    reason_flagged: str  # field 4

    # Judgment
    outcome: FindingOutcome
    classification: FindingClassification  # field 6, mapped onto the five states
    severity: str

    # Honesty
    limitations_and_assumptions: str  # field 7
    applicability: Applicability

    # Action — a proposal only; execution (if ever) flows through the broker's
    # risk tiers, never from a finding directly.
    suggested_action: str | None = None

    provenance: ProvenanceRecord
    template_text: str  # deterministic core text, complete without any LLM
