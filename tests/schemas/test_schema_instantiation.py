"""Each §2 schema instantiates with valid representative data.

Also asserts the DesignSnapshot round-trips through JSON, which is the concrete
proof of W-8's "plain JSON-serializable data only" claim — datetimes and complex
S (as real/imag) survive the trip.
"""

import importlib
import inspect
import pkgutil
import typing
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

import hfss_agent.contract as contract_package
from hfss_agent.contract import (
    CONTRACT_VERSION,
    AuditRecord,
    ComplexSample,
    DesignSnapshot,
    Environment,
    Finding,
    FindingProvenance,
    FreshnessEvidence,
    Inspection,
    InspectionProvenance,
    InspectionSection,
    IntentObject,
    MetricRecord,
    NativeValidation,
    NativeValidationProvenance,
    ProvenanceRecord,
    Selection,
    SolutionExists,
    SolvedData,
    SolveState,
    StrictModel,
    Variation,
)


def _contract_models() -> list[type[BaseModel]]:
    """Every pydantic model DEFINED under ``hfss_agent.contract``, tool_io
    included.

    Module equality on ``__module__`` is what makes it "defined here" rather than
    "visible here": every one of these types is re-exported from at least one
    ``__init__``, and counting a re-export would inflate any set derived from this
    list without changing what the contract actually declares.
    """
    models: dict[str, type[BaseModel]] = {}
    packages = [contract_package]
    for module_info in pkgutil.walk_packages(
        contract_package.__path__, contract_package.__name__ + "."
    ):
        packages.append(importlib.import_module(module_info.name))
    for module in packages:
        for value in vars(module).values():
            if (
                inspect.isclass(value)
                and issubclass(value, BaseModel)
                and value.__module__ == module.__name__
            ):
                models[f"{value.__module__}.{value.__name__}"] = value
    return list(models.values())


def _annotation_mentions(annotation: Any, target: type) -> bool:
    """True when ``target`` appears anywhere inside an annotation tree.

    Recurses through ``typing.get_args`` so a union arm, an ``Annotated`` payload,
    or a container element counts — a field typed ``ProvenanceRecord | None`` is
    still a carrier, and a set derived by identity alone would miss it.
    """
    if annotation is target:
        return True
    return any(_annotation_mentions(arg, target) for arg in typing.get_args(annotation))


def test_contract_version_literal_is_pinned() -> None:
    # Every other site imports CONTRACT_VERSION rather than restating the
    # literal, so a stray edit to the constant would flow through and pass every
    # other test silently. This one pin is what makes a change to the schema
    # version space loud — bumping it here is the deliberate, reviewed act.
    assert CONTRACT_VERSION == "snapshot-4.0.0"


def _snapshot(variation: Variation) -> DesignSnapshot:
    return DesignSnapshot(
        contract_version=CONTRACT_VERSION,
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
            # The bare project NAME (ADR-28). ``Selection`` no longer carries a
            # ``Project``; the path stays on ``SessionStatus.SelectionChain``.
            project="patch_antenna",
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
    # Exactly the thirteen fields, and NO OPTIONAL AMONG THEM. This pin arrives
    # with the removal of ``engine_version``/``rule_version`` at Step 2.6a, and it
    # replaces two assertions that they defaulted to None — which is the whole
    # defect: they defaulted to None forever, because no producer could fill
    # either. The three sibling provenance types have carried a pin like this
    # since they were split off; this one was the last without.
    #
    # RESTORING EITHER FIELD IS EXACTLY THE EDIT THIS CATCHES. Both look
    # "obviously missing" to anyone who meets ``FindingProvenance.engine_version``
    # one class down and does not read why it is honest there and was not here.
    assert set(ProvenanceRecord.model_fields) == {
        "project",
        "design",
        "solution_type",
        "setup",
        "sweep",
        "variation",
        "expression",
        "reference_impedance",
        "solve_timestamp",
        "freshness_status",
        "snapshot_id",
        "contract_version",
        "wrapper_version",
    }


def test_inspection_provenance_instantiates(
    inspection_provenance: InspectionProvenance,
) -> None:
    assert inspection_provenance.read_at.tzinfo is not None
    # Exactly the six fields — no solve, metric, or judgment slot exists to be
    # filled in later by something that never solved (ADR-20, gap 11). An AEDT
    # version is none of those three, so the closed set still holds.
    assert set(InspectionProvenance.model_fields) == {
        "project",
        "design",
        "read_at",
        "contract_version",
        "wrapper_version",
        "read_under_aedt_version",
    }


def test_native_validation_provenance_instantiates(
    native_validation_provenance: NativeValidationProvenance,
) -> None:
    assert native_validation_provenance.validated_at.tzinfo is not None
    # Exactly the six fields — mirroring the InspectionProvenance pin above and
    # for the same reason (ADR-23, ADR-20 dec. 6). A validation run has no solve
    # and no calculation of ours, so there must be no slot here for a later
    # change to fill with something that never solved or never computed. The pin
    # is what makes adding one a visible test diff rather than a quiet edit.
    assert set(NativeValidationProvenance.model_fields) == {
        "project",
        "design",
        "validated_at",
        "contract_version",
        "wrapper_version",
        "validated_under_aedt_version",
    }


def test_finding_provenance_instantiates(
    finding_provenance: FindingProvenance,
) -> None:
    # The optional defaults to absent rather than being required: a gate has no
    # engine behind it and must not have to name one.
    assert finding_provenance.engine_version is None
    # Exactly the ten fields. The pin mirrors the two above and carries the same
    # job, plus one this type needs more than they do: five fields were DROPPED
    # from ProvenanceRecord AS IT STOOD AT ADR-30 to build it (expression,
    # reference_impedance, solve_timestamp, freshness_status, rule_version) and
    # two more were deliberately not added (evaluated_at,
    # evaluated_under_aedt_version). Four of those five are still on
    # ProvenanceRecord today; ``rule_version`` is not, because Step 2.6a went on
    # to remove it there too once this type took its only producer. Each
    # is exactly the kind of field a later change would restore as "obviously
    # missing", and every one of them would re-introduce a claim a judgment
    # cannot earn. Restoring one is a visible diff on this line, not a quiet
    # edit one file over.
    #
    # THE ADDITION DIRECTION IS THE ONE THIS LINE OWNS, and a reader should not
    # assume a set-equality pin is the detector in both. A field REMOVED from
    # ``FindingProvenance`` never reaches this assertion: the fixture above
    # supplies every field, so ``extra="forbid"`` rejects it during fixture
    # setup and the test goes red as an ERROR before the pin body runs. Both
    # directions are caught — but by two different mechanisms, and only the
    # added-field one is this line.
    assert set(FindingProvenance.model_fields) == {
        "project",
        "design",
        "solution_type",
        "setup",
        "sweep",
        "variation",
        "snapshot_id",
        "contract_version",
        "wrapper_version",
        "engine_version",
    }


def test_inspection_provenance_rejects_naive_read_at() -> None:
    # A naive instant would silently read as local time; "when was this read"
    # must never be ambiguous by an offset.
    with pytest.raises(ValidationError):
        InspectionProvenance(
            project="patch_antenna",
            design="HFSSDesign1",
            read_at=datetime(2026, 7, 17, 9, 30),
            contract_version=CONTRACT_VERSION,
            wrapper_version="0.0.0",
            read_under_aedt_version="2026.1",
        )


def test_native_validation_provenance_rejects_naive_validated_at() -> None:
    # The sibling of the InspectionProvenance check above, and it was missing:
    # 2.2a pinned that validated_at IS aware on a well-formed record, but never
    # that a naive one is REJECTED. Same reasoning either way — a naive instant
    # would silently read as local time, and "when did the validator run" must
    # never be ambiguous by an offset.
    with pytest.raises(ValidationError):
        NativeValidationProvenance(
            project="patch_antenna",
            design="HFSSDesign1",
            validated_at=datetime(2026, 7, 17, 9, 30),
            contract_version=CONTRACT_VERSION,
            wrapper_version="0.0.0",
            validated_under_aedt_version="2026.1",
        )


# Every unordered pair of the four provenance types. Written out rather than
# generated from a registry, so adding a fifth type is a visible edit here
# instead of silently inheriting coverage that was never reviewed.
_PROVENANCE_TYPE_PAIRS = [
    (ProvenanceRecord, InspectionProvenance),
    (ProvenanceRecord, NativeValidationProvenance),
    (ProvenanceRecord, FindingProvenance),
    (InspectionProvenance, NativeValidationProvenance),
    (InspectionProvenance, FindingProvenance),
    (NativeValidationProvenance, FindingProvenance),
]


@pytest.mark.parametrize(
    ("left", "right"),
    _PROVENANCE_TYPE_PAIRS,
    ids=lambda pair: pair.__name__,
)
def test_the_four_provenance_types_share_no_base_class(
    left: type[StrictModel], right: type[StrictModel]
) -> None:
    """All four are independent types, pairwise (ADR-20 dec. Option B, ADR-23,
    ADR-30).

    Guards the decision itself: a later refactor that factors out a common
    parent — the natural-looking cleanup, and more tempting at four types than
    it was at two — would let a field added for solve provenance appear on a
    structural read, or an ``expression`` appear on a judgment, which is the
    exact dishonesty each of these types was split off to close.

    PAIRWISE RATHER THAN ONE NAMED PAIR, because a base class shared by any two
    of the four is the defect; the original form of this test checked only
    ``InspectionProvenance``/``ProvenanceRecord`` and would have passed while
    ``FindingProvenance`` inherited from either of the other two.
    """
    assert not issubclass(left, right)
    assert not issubclass(right, left)
    shared = set(left.__mro__) & set(right.__mro__)
    # StrictModel is contract-wide; anything narrower would be a shared base
    # specific to this pair.
    assert shared == {StrictModel, BaseModel, object}


def test_provenance_record_has_exactly_two_carriers() -> None:
    """``ProvenanceRecord`` is carried by ``MetricRecord`` and
    ``SolveHealthReport``, and by nothing else.

    PINS A CLAIM ALREADY WRITTEN IN PRODUCT CODE. ADR-30 left
    ``ProvenanceRecord.engine_version``/``rule_version`` with no producer, and the
    docstring's argument for removing them turns on this set being exactly these
    two: neither a metric nor a solve-health readout can have an engine behind it,
    because the engine seam is ``evaluate(DesignSnapshot) -> list[Finding]`` and
    nothing crossing it is either. A third carrier appearing would not break that
    reasoning quietly — it would break it invisibly, since the argument lives in a
    comment that no test reads.

    DERIVED, NOT LISTED, and the difference is not academic here. A textual search
    for ``ProvenanceRecord`` returns ``tool_io/inspection.py``, whose docstring
    says ``InspectionResult``'s provenance is an ``InspectionProvenance`` and NOT
    a ``ProvenanceRecord`` — a grep counts the sentence that denies it as though
    it asserted it. This walk reads ``model_fields`` instead, so only a real
    annotation counts, and it unwraps unions and containers so a
    ``ProvenanceRecord | None`` or a ``list[ProvenanceRecord]`` could not hide.
    """
    carriers = {
        f"{model.__name__}.{field_name}"
        for model in _contract_models()
        for field_name, field in model.model_fields.items()
        if _annotation_mentions(field.annotation, ProvenanceRecord)
    }
    assert carriers == {"MetricRecord.provenance", "SolveHealthReport.provenance"}

    # The same walk over the three sibling provenance types, as a control: it
    # proves the walk can SEE a carrier rather than returning a small set because
    # it is looking in the wrong place. It also pins that InspectionResult is a
    # carrier of InspectionProvenance — the one the earlier miscount put here.
    assert {
        f"{model.__name__}.{field_name}"
        for model in _contract_models()
        for field_name, field in model.model_fields.items()
        if _annotation_mentions(field.annotation, InspectionProvenance)
    } == {"InspectionResult.provenance"}


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
    # The two gap-8/9 additions are OPTIONAL: a record built without them is
    # valid and defaults to "inapplicable", so every pre-amendment on-disk log
    # line still loads.
    assert record.session_degraded is None


# --- AuditRecord both-or-neither: risk_tier is None IFF outcome is unknown ----


def _audit_record(**overrides: Any) -> AuditRecord:
    fields: dict[str, Any] = {
        "timestamp": datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc),
        "tool_name": "compute_metrics",
        "sanitized_arguments": {},
        "selection_state": {},
        "risk_tier": "safe",
        "outcome": "ok",
        "duration": 0.42,
    }
    fields.update(overrides)
    return AuditRecord(**fields)


def test_unknown_capability_outcome_accepts_a_null_tier() -> None:
    # The positive half of the gap-9 pair: this combination is the ONLY way to
    # record "a capability that isn't registered was requested", and it must
    # construct.
    record = _audit_record(risk_tier=None, outcome="unknown_capability")
    assert record.risk_tier is None
    assert record.outcome == "unknown_capability"


@pytest.mark.parametrize(
    "outcome", ["ok", "typed_error", "cannot_evaluate", "refused_by_gate"]
)
def test_null_tier_is_rejected_for_every_other_outcome(outcome: str) -> None:
    # DIRECTION 1: a registered capability always dispatches under a declared
    # tier. A null tier anywhere else would mean the log stopped recording
    # which guard set the call ran under — silently, on a call that really ran.
    with pytest.raises(ValidationError, match="unknown_capability"):
        _audit_record(risk_tier=None, outcome=outcome)


@pytest.mark.parametrize("tier", ["safe", "medium", "high"])
def test_unknown_capability_outcome_is_rejected_with_any_tier(tier: str) -> None:
    # DIRECTION 2: the fabrication guard. "safe" would be a false claim about
    # an unknown thing and "high" would pollute the high-tier refusal trail —
    # which is exactly why the None exists, so it must be mandatory here and
    # not merely permitted.
    with pytest.raises(ValidationError, match="requires risk_tier=None"):
        _audit_record(risk_tier=tier, outcome="unknown_capability")


def test_both_or_neither_is_enforced_on_deserialization_too() -> None:
    # The validator must guard the READ path, not just construction: a
    # hand-edited or corrupted log line carrying the forbidden pairing is
    # rejected rather than believed. (The reader's two-arm policy then reports
    # it as a corrupt line instead of raising — loud, never silent.)
    line = _audit_record(risk_tier=None, outcome="unknown_capability").model_dump_json()
    assert AuditRecord.model_validate_json(line).risk_tier is None

    forged = line.replace('"risk_tier":null', '"risk_tier":"safe"')
    assert forged != line  # the substitution really happened
    with pytest.raises(ValidationError):
        AuditRecord.model_validate_json(forged)
