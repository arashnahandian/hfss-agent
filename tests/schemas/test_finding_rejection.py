"""Finding rejects instantiation when any required field is missing.

W-10 rejects evidence-incomplete findings as protocol errors and never displays
them; here we prove Pydantic's required-field validation is that gate. All 16 of
Finding's required fields — the seven §2 evidence groups plus provenance and
template_text — are dropped individually and must raise. suggested_action, the
one optional field, is exempt.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from hfss_agent.contract import Finding

# All 16 required fields of Finding. The first fourteen are §2's seven evidence
# groups flattened; provenance and template_text are required too (no default,
# no `?` in §2) though they sit outside the evidence superset. suggested_action
# is excluded — it is the one genuinely optional field.
REQUIRED_FIELDS = [
    # Group 1 — Identity
    "finding_id",
    "source",
    "rule_id",
    "rule_version",
    "rule_purpose",
    # Group 2 — inspected (field 1)
    "inspected",
    # Group 3 — observed_values (field 2)
    "observed_values",
    # Group 4 — calculation_ref (field 3)
    "calculation_ref",
    # Group 5 — reason_flagged (field 4)
    "reason_flagged",
    # Group 6 — Judgment
    "outcome",
    "classification",
    "severity",
    # Group 7 — Honesty
    "limitations_and_assumptions",
    "applicability",
    # Required, but outside the seven-field evidence superset
    "provenance",
    "template_text",
]


def test_finding_accepts_complete_evidence(
    valid_finding_kwargs: dict[str, Any],
) -> None:
    # Baseline: the complete keyword set constructs without error.
    Finding(**valid_finding_kwargs)


@pytest.mark.parametrize("missing_field", REQUIRED_FIELDS)
def test_finding_rejects_missing_required_field(
    valid_finding_kwargs: dict[str, Any], missing_field: str
) -> None:
    kwargs = dict(valid_finding_kwargs)
    del kwargs[missing_field]

    with pytest.raises(ValidationError) as excinfo:
        Finding(**kwargs)

    # The rejection names the field that was missing, not some unrelated one.
    assert missing_field in str(excinfo.value)


def test_finding_rejects_hfss_native_source_so_no_engine_finding_can_claim_it(
    valid_finding_kwargs: dict[str, Any],
) -> None:
    """A native HFSS message can never enter this schema, at the type level.

    WHAT THIS PROTECTS. The engine returns ``list[Finding]`` across the
    wrapper->engine seam, and W-10's job is to reject any entry missing one of
    the sixteen required fields. Had ``FindingSource`` kept ``hfss_native``,
    those fields could have been argued optional "for native findings" — and
    then any engine finding wearing that label would walk straight through the
    evidence gate. That is the laundering hole ADR-23 closed by REMOVING the
    member rather than by adding a conditional the gate could forget to apply.

    So this is not a spelling test. It is the proof that the hole is shut by
    the type system: with no such member, there is no source for which the
    seven-field requirement could be relaxed, and W-10's gate stays
    unconditional. Native validation travels as ``NativeValidationBlock``
    instead, whose own ``source`` literal carries the attribution.

    If this test ever fails, the member is back and the gate is conditional
    again.
    """
    kwargs = dict(valid_finding_kwargs)
    kwargs["source"] = "hfss_native"

    with pytest.raises(ValidationError) as excinfo:
        Finding(**kwargs)

    assert "source" in str(excinfo.value)


def test_finding_allows_missing_optional_suggested_action(
    valid_finding_kwargs: dict[str, Any],
) -> None:
    # suggested_action is absent from valid_finding_kwargs; construction still
    # succeeds and the field defaults to None (proposal-only, so optional).
    finding = Finding(**valid_finding_kwargs)
    assert finding.suggested_action is None
