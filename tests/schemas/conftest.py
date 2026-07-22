"""Shared fixtures for the contract-schema tests.

Representative-but-minimal valid instances of the shared sub-records, plus a
complete valid keyword set for ``Finding`` that the rejection suite drops fields
from one at a time.
"""

from datetime import datetime, timezone
from typing import Any

import pytest

from hfss_agent.contract import (
    Applicability,
    InspectionProvenance,
    ProvenanceRecord,
    Variation,
)


@pytest.fixture
def variation() -> Variation:
    return Variation(
        values={"width": "2.0mm", "freq": "2.4GHz"},
        variation_hash="sha256:deadbeefcafef00d",
    )


@pytest.fixture
def provenance(variation: Variation) -> ProvenanceRecord:
    return ProvenanceRecord(
        project="patch_antenna",
        design="HFSSDesign1",
        solution_type="DrivenModal",
        setup="Setup1",
        sweep="Sweep1",
        variation=variation,
        expression="dB(S(1,1))",
        reference_impedance=50.0,
        solve_timestamp=datetime(2026, 7, 17, 9, 30, tzinfo=timezone.utc),
        freshness_status="fresh",
        snapshot_id="snap-001",
        contract_version="snapshot-1.0.0",
        wrapper_version="0.0.0",
        # engine_version / rule_version deliberately omitted: a gate finding has
        # neither, and they are optional.
    )


@pytest.fixture
def inspection_provenance() -> InspectionProvenance:
    """Provenance for a structural read — no solve fields, by construction."""
    return InspectionProvenance(
        project="patch_antenna",
        design="HFSSDesign1",
        read_at=datetime(2026, 7, 17, 9, 30, tzinfo=timezone.utc),
        contract_version="snapshot-1.0.0",
        wrapper_version="0.0.0",
        read_under_aedt_version="2026.1",
    )


@pytest.fixture
def valid_finding_kwargs(provenance: ProvenanceRecord) -> dict[str, Any]:
    """A complete, valid Finding keyword set.

    ``suggested_action`` is intentionally absent (it is the one optional field),
    so every key present here is required and safe for the rejection suite to
    drop.
    """
    return {
        "finding_id": "find-001",
        "source": "gate",
        "rule_id": "gate.solution_exists",
        "rule_version": "1.0.0",
        "rule_purpose": "Confirms a solution exists for the selected "
        "setup/sweep/variation.",
        "inspected": ["solve_state.solution_exists"],
        "observed_values": {"exists": True},
        "calculation_ref": "hfss_agent.gating.solution_exists:evaluate",
        "reason_flagged": "A solution exists for the selected combination.",
        "outcome": "pass",
        "classification": "judgment_call",
        "severity": "info",
        "limitations_and_assumptions": "Assumes PyAEDT reported solution "
        "presence accurately for the selection.",
        "applicability": Applicability(conditions={"has_setup": True}, held=True),
        "provenance": provenance,
        "template_text": "[gate] solution_exists: pass",
    }
