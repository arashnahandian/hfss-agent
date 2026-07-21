"""Each §2 schema instantiates with valid representative data.

Also asserts the DesignSnapshot round-trips through JSON, which is the concrete
proof of W-8's "plain JSON-serializable data only" claim — datetimes and complex
S (as real/imag) survive the trip.
"""

from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from hfss_agent.contract import (
    AuditRecord,
    ComplexSample,
    DesignSnapshot,
    Environment,
    Finding,
    FreshnessEvidence,
    Inspection,
    InspectionProvenance,
    InspectionSection,
    IntentObject,
    MetricRecord,
    NativeValidation,
    Project,
    ProvenanceRecord,
    Selection,
    SolutionExists,
    SolvedData,
    SolveState,
    StrictModel,
    Variation,
)


def _snapshot(variation: Variation) -> DesignSnapshot:
    return DesignSnapshot(
        contract_version="snapshot-1.0.0",
        created_at=datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc),
        snapshot_id="snap-001",
        environment=Environment(
            aedt_version="2026.1",
            pyaedt_version="1.2.0",
            python_version="3.12.4",
            wrapper_version="0.0.0",
        ),
        selection=Selection(
            process_id=12345,
            project=Project(name="patch_antenna", path=r"C:\proj\patch.aedt"),
            design="HFSSDesign1",
            solution_type="DrivenModal",
            setup="Setup1",
            sweep="Sweep1",
            variation=variation,
        ),
        inspection=Inspection(
            variables=InspectionSection(data={"width": "2.0mm"}, read_status="ok"),
            objects=InspectionSection(data=["Patch", "Ground"], read_status="ok"),
            materials=InspectionSection(data=["copper", "FR4"], read_status="ok"),
            boundaries=InspectionSection(data=["rad1"], read_status="ok"),
            excitations_ports=InspectionSection(data=["1"], read_status="ok"),
            setups=InspectionSection(data=["Setup1"], read_status="ok"),
            sweeps=InspectionSection(data=["Sweep1"], read_status="ok"),
            available_results=InspectionSection(
                data=None,
                read_status="not_readable",
                limitation="PyAEDT get_solution_data returned None for the sweep.",
            ),
        ),
        native_validation=NativeValidation(
            raw_output=["Design validation completed with 0 errors, 0 warnings."],
        ),
        solve_state=SolveState(
            solution_exists=[
                SolutionExists(
                    setup="Setup1",
                    sweep="Sweep1",
                    variation=variation,
                    exists=True,
                ),
            ],
            adaptive_pass_history=[
                {"pass": 1, "delta_s": 0.05},
                {"pass": 2, "delta_s": 0.008},
            ],
            delta_s_progression=[0.05, 0.008],
            convergence_status="converged",
            solve_timestamps={
                "Setup1:Sweep1": datetime(2026, 7, 17, 9, 30, tzinfo=timezone.utc)
            },
            solver_messages=["Adaptive passes converged at pass 2."],
            freshness_evidence=FreshnessEvidence(
                available_signals={"design_modified_since_solve": False},
                determinable=True,
            ),
        ),
        solved_data=SolvedData(
            frequencies=[2.3e9, 2.4e9, 2.5e9],
            s_parameters={
                "S(1,1)": [
                    ComplexSample(real=-0.10, imag=0.02),
                    ComplexSample(real=-0.30, imag=0.05),
                    ComplexSample(real=-0.12, imag=0.01),
                ],
            },
        ),
        intent=IntentObject(
            target_frequency_hz=2.4e9,
            threshold_type="s11",
            threshold_value=-10.0,
        ),
    )


def test_design_snapshot_instantiates_and_json_round_trips(
    variation: Variation,
) -> None:
    snapshot = _snapshot(variation)

    assert snapshot.selection.variation.variation_hash == variation.variation_hash
    assert snapshot.inspection.available_results.read_status == "not_readable"
    assert snapshot.solve_state.solution_exists[0].exists is True

    # W-8: the snapshot is plain, JSON-serializable data only.
    dumped = snapshot.model_dump(mode="json")
    assert isinstance(dumped, dict)
    reloaded = DesignSnapshot.model_validate(dumped)
    assert reloaded == snapshot


def test_finding_instantiates(valid_finding_kwargs: dict[str, Any]) -> None:
    finding = Finding(**valid_finding_kwargs)
    # outcome and classification are distinct fields, both populated.
    assert finding.outcome == "pass"
    assert finding.classification == "judgment_call"
    assert finding.suggested_action is None


def test_provenance_record_instantiates(provenance: ProvenanceRecord) -> None:
    assert provenance.variation.values["freq"] == "2.4GHz"
    assert provenance.engine_version is None
    assert provenance.rule_version is None


def test_inspection_provenance_instantiates(
    inspection_provenance: InspectionProvenance,
) -> None:
    assert inspection_provenance.read_at.tzinfo is not None
    # Exactly the five fields — no solve, metric, or judgment slot exists to be
    # filled in later by something that never solved (ADR-20, gap 11).
    assert set(InspectionProvenance.model_fields) == {
        "project",
        "design",
        "read_at",
        "contract_version",
        "wrapper_version",
    }


def test_inspection_provenance_rejects_naive_read_at() -> None:
    # A naive instant would silently read as local time; "when was this read"
    # must never be ambiguous by an offset.
    with pytest.raises(ValidationError):
        InspectionProvenance(
            project="patch_antenna",
            design="HFSSDesign1",
            read_at=datetime(2026, 7, 17, 9, 30),
            contract_version="snapshot-1.0.0",
            wrapper_version="0.0.0",
        )


def test_inspection_provenance_shares_no_base_with_provenance_record() -> None:
    """The two are independent types (ADR-20 chose Option B over a shared base).

    Guards the decision itself: a later refactor that factors out a common
    parent — the natural-looking cleanup — would let a field added for solve
    provenance appear on a structural read, which is the exact dishonesty this
    gap closed.
    """
    assert not issubclass(InspectionProvenance, ProvenanceRecord)
    assert not issubclass(ProvenanceRecord, InspectionProvenance)
    shared = set(InspectionProvenance.__mro__) & set(ProvenanceRecord.__mro__)
    # StrictModel is contract-wide; anything narrower would be a shared base
    # specific to these two.
    assert shared == {StrictModel, BaseModel, object}


def test_metric_record_instantiates(provenance: ProvenanceRecord) -> None:
    metric = MetricRecord(
        metric_name="s11_min",
        value=-18.2,
        units="dB",
        formula_ref="hfss_agent.metrics.sparams:s11_min",
        gate_status_at_computation="all_gates_passed",
        provenance=provenance,
    )
    assert metric.value == -18.2
    # Variation reaches the metric via its provenance, not a duplicate field.
    assert metric.provenance.variation.variation_hash.startswith("sha256:")


def test_intent_object_instantiates() -> None:
    intent = IntentObject(
        target_frequency_hz=2.4e9,
        threshold_type="vswr",
        threshold_value=2.0,
    )
    assert intent.threshold_type == "vswr"


def test_audit_record_instantiates() -> None:
    record = AuditRecord(
        timestamp=datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc),
        tool_name="compute_metrics",
        sanitized_arguments={"intent": None},
        selection_state={"design": "HFSSDesign1", "setup": "Setup1"},
        risk_tier="safe",
        outcome="ok",
        duration=0.42,
        snapshot_id="snap-001",
    )
    assert record.risk_tier == "safe"
    assert record.outcome == "ok"
