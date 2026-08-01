"""Tool I/O schema tests (§3): the 17 tools' request/response contracts.

Proves the load-bearing structural guarantees:
  * ComputeMetricsResult — "metrics *and* failing gates" and "neither populated"
    are both unconstructible (the "no numbers on gate failure" promise, by the
    type rather than by convention);
  * ExportResult — its arms (written / refused / failed / cannot_evaluate) are
    mutually exclusive and routed by ``outcome``, including each of the three
    refusal remedies;
  * every new tool_io schema constructs from representative valid data;
  * the adapter-backed result unions route a CannotEvaluate payload to
    CannotEvaluate and a success payload to the success type;
  * the four unions that route a session gate's refusal go through the CALLABLE
    ``result_kind`` discriminator — every arm, plus an unknown outcome rejected
    — while their success types stay untagged (no ``outcome`` field, unchanged
    wire format), which is the reason the discriminator is callable at all;
  * ValidationReport serializes its native block BEFORE its findings, which is
    what makes "native first" a guarantee this repo holds rather than one
    borrowed from pydantic's field ordering;
  * importing ``contract.tool_io`` pulls in no ``pyaedt`` (purity holds — ADR-3).

Reuses the shared conftest fixtures (``variation``, ``provenance``,
``valid_finding_kwargs``) so the §2 sub-records are built one way across suites.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from hfss_agent.contract import (
    AuditRecord,
    Finding,
    FreshnessEvidence,
    InspectionProvenance,
    InspectionSection,
    IntentObject,
    MetricRecord,
    NativeValidation,
    NativeValidationProvenance,
    Project,
    ProvenanceRecord,
    SolutionExists,
    SolveState,
    Variation,
)
from hfss_agent.contract.tool_io import (
    AedtProcess,
    AedtProcessList,
    AttachRequest,
    AttachResult,
    AuditLog,
    AuditLogRange,
    CannotEvaluate,
    CheckSolutionValidityRequest,
    ComponentCheck,
    ComputeMetricsRequest,
    ComputeMetricsResult,
    DesignIntentState,
    ExportDiagnosticsBundleRequest,
    ExportFailed,
    ExportRefused,
    ExportResult,
    ExportResultsRequest,
    ExportWritten,
    GetAuditLogRequest,
    InspectDesignRequest,
    InspectDesignResult,
    InspectionResult,
    ListSelectionOptionsRequest,
    ListSelectionOptionsResult,
    MetricsComputed,
    MetricsRefused,
    NativeValidationBlock,
    PreflightEnvironment,
    PreflightReport,
    SelectionChain,
    SelectionOption,
    SelectionOptions,
    SelectionRefused,
    SelectRequest,
    SelectResult,
    SessionStatus,
    SolutionValidityReport,
    SolveHealthReport,
    ValidateSetupRequest,
    ValidateSetupResult,
    ValidationReport,
)

# Adapters over the discriminated / smart-mode unions so raw-dict routing can be
# exercised (not just direct arm construction).
_COMPUTE_METRICS = TypeAdapter(ComputeMetricsResult)
_EXPORT = TypeAdapter(ExportResult)
_ATTACH = TypeAdapter(AttachResult)
_INSPECT = TypeAdapter(InspectDesignResult)
_SELECT = TypeAdapter(SelectResult)
_LIST_OPTIONS = TypeAdapter(ListSelectionOptionsResult)
_VALIDATE_SETUP = TypeAdapter(ValidateSetupResult)


# --- shared instances --------------------------------------------------------


@pytest.fixture
def finding(valid_finding_kwargs: dict[str, Any]) -> Finding:
    return Finding(**valid_finding_kwargs)


@pytest.fixture
def metric(provenance: ProvenanceRecord) -> MetricRecord:
    return MetricRecord(
        metric_name="s11_min",
        value=-18.2,
        units="dB",
        formula_ref="hfss_agent.metrics.sparams:s11_min",
        gate_status_at_computation="all_gates_passed",
        provenance=provenance,
    )


@pytest.fixture
def solve_state(variation: Variation) -> SolveState:
    return SolveState(
        solution_exists=[
            SolutionExists(
                setup="Setup1", sweep="Sweep1", variation=variation, exists=True
            )
        ],
        adaptive_pass_history=[{"pass": 1, "delta_s": 0.02}],
        delta_s_progression=[0.02],
        convergence_status="converged",
        solve_timestamps={
            "Setup1:Sweep1": datetime(2026, 7, 17, 9, 30, tzinfo=timezone.utc)
        },
        solver_messages=["Adaptive passes converged at pass 1."],
        freshness_evidence=FreshnessEvidence(
            available_signals={"design_modified_since_solve": False},
            determinable=True,
        ),
    )


_CANNOT_EVALUATE_DICT = {
    "outcome": "cannot_evaluate",
    "reason": "The adapter read failed.",
    "limitation": "PyAEDT get_solution_data returned None for the sweep.",
    "template_text": "[cannot_evaluate] get_solution_data returned None",
}


# --- ComputeMetricsResult: the core-promise guarantees -----------------------


def test_metrics_computed_arm_validates(metric: MetricRecord) -> None:
    result = MetricsComputed(metrics=[metric], template_text="[metrics] s11_min")
    assert result.outcome == "metrics_computed"
    assert _COMPUTE_METRICS.validate_python(result.model_dump()) == result


def test_metrics_refused_arm_validates(finding: Finding) -> None:
    result = MetricsRefused(
        failing_gates=[finding], template_text="[refused] gate failed"
    )
    assert result.outcome == "gates_failed"
    assert _COMPUTE_METRICS.validate_python(result.model_dump()) == result


def test_compute_metrics_cannot_evaluate_arm_validates() -> None:
    result = _COMPUTE_METRICS.validate_python(_CANNOT_EVALUATE_DICT)
    assert isinstance(result, CannotEvaluate)


def test_metrics_computed_cannot_also_hold_failing_gates(
    metric: MetricRecord, finding: Finding
) -> None:
    # Both-arms-populated is unconstructible at the class level: MetricsComputed
    # has no failing_gates field and forbids extras.
    with pytest.raises(ValidationError):
        MetricsComputed(metrics=[metric], failing_gates=[finding], template_text="x")


def test_metrics_refused_cannot_also_hold_metrics(
    metric: MetricRecord, finding: Finding
) -> None:
    with pytest.raises(ValidationError):
        MetricsRefused(failing_gates=[finding], metrics=[metric], template_text="x")


def test_union_rejects_both_payloads_in_one_dict(
    metric: MetricRecord, finding: Finding
) -> None:
    # Routed by outcome to MetricsComputed, whose extra="forbid" rejects the
    # smuggled failing_gates — so "refused numbers" cannot slip through the union.
    with pytest.raises(ValidationError):
        _COMPUTE_METRICS.validate_python(
            {
                "outcome": "metrics_computed",
                "metrics": [metric.model_dump()],
                "failing_gates": [finding.model_dump()],
                "template_text": "x",
            }
        )


def test_metrics_computed_requires_metrics() -> None:
    # Neither-populated is unconstructible: a metrics_computed result with no
    # metrics is a missing required field.
    with pytest.raises(ValidationError):
        MetricsComputed(template_text="x")


def test_metrics_refused_requires_failing_gates() -> None:
    with pytest.raises(ValidationError):
        MetricsRefused(template_text="x")


def test_compute_metrics_union_rejects_unknown_outcome() -> None:
    with pytest.raises(ValidationError):
        _COMPUTE_METRICS.validate_python({"outcome": "bogus", "template_text": "x"})


# --- ExportResult: four mutually exclusive arms ------------------------------


def test_export_written_arm_routes() -> None:
    written = _EXPORT.validate_python(
        {
            "outcome": "written",
            "path": "out.s2p",
            "bytes_written": 2048,
            "template_text": "[export] wrote out.s2p",
        }
    )
    assert isinstance(written, ExportWritten)


@pytest.mark.parametrize(
    "outcome",
    ["refused_existing_path", "refused_invalid_path", "refused_network_path"],
)
def test_export_refused_arm_routes_every_remedy(outcome: str) -> None:
    # All three refusal remedies are the SAME arm, kept apart only by the tag —
    # so a caller can branch on the tag without parsing the prose reason.
    refused = _EXPORT.validate_python(
        {
            "outcome": outcome,
            "path": "out.s2p",
            "reason": "refusal detail lives here, not in the tag",
            "template_text": "[export] refused out.s2p",
        }
    )
    assert isinstance(refused, ExportRefused)
    assert refused.outcome == outcome


def test_export_refused_requires_an_outcome() -> None:
    # No default: a refusal must state WHICH remedy applies (gap 5), rather
    # than silently inheriting "existing path" and inviting a bad retry.
    with pytest.raises(ValidationError):
        ExportRefused(path="out.s2p", reason="r", template_text="x")  # type: ignore[call-arg]


@pytest.mark.parametrize("orphaned_temp", ["out.s2p.tmp-a1b2", None])
def test_export_failed_arm_routes_with_and_without_orphaned_temp(
    orphaned_temp: str | None,
) -> None:
    # A write that broke MID-operation, with and without a temp left behind.
    failed = _EXPORT.validate_python(
        {
            "outcome": "write_failed",
            "path": "out.s2p",
            "reason": "no space left on device",
            "orphaned_temp": orphaned_temp,
            "template_text": "[export] write failed for out.s2p",
        }
    )
    assert isinstance(failed, ExportFailed)
    assert failed.orphaned_temp == orphaned_temp


def test_export_failed_orphaned_temp_defaults_to_none() -> None:
    # Omitting it means "nothing was left behind" — never "unknown".
    failed = _EXPORT.validate_python(
        {
            "outcome": "write_failed",
            "path": "out.s2p",
            "reason": "permission denied mid-write",
            "template_text": "[export] write failed for out.s2p",
        }
    )
    assert isinstance(failed, ExportFailed)
    assert failed.orphaned_temp is None


def test_export_cannot_evaluate_arm_routes() -> None:
    # export_* covers the failed-adapter-read case as its own arm — a PyAEDT
    # limitation, never conflated with a refusal or a broken write.
    cannot = _EXPORT.validate_python(_CANNOT_EVALUATE_DICT)
    assert isinstance(cannot, CannotEvaluate)


def test_export_written_rejects_refused_only_field() -> None:
    # Cross-arm contamination is rejected: 'reason' belongs to the refused arm.
    with pytest.raises(ValidationError):
        _EXPORT.validate_python(
            {
                "outcome": "written",
                "path": "out.s2p",
                "bytes_written": 1,
                "reason": "should not be here",
                "template_text": "x",
            }
        )


def test_export_written_requires_bytes_written() -> None:
    with pytest.raises(ValidationError):
        _EXPORT.validate_python(
            {"outcome": "written", "path": "out.s2p", "template_text": "x"}
        )


def test_export_rejects_unknown_outcome() -> None:
    with pytest.raises(ValidationError):
        _EXPORT.validate_python(
            {"outcome": "deleted", "path": "out.s2p", "template_text": "x"}
        )


# --- session result unions: the callable-discriminator routes ----------------
# SelectResult / ListSelectionOptionsResult / InspectDesignResult /
# ValidateSetupResult route via the CALLABLE ``result_kind`` discriminator, not
# a declared Field(discriminator="outcome"), precisely so their success types
# keep their untagged wire format. These tests pin both halves of that bargain:
# the success types stay untagged, and every tagged arm still routes exactly.

_SELECTION_REFUSAL_OUTCOMES = [
    "refused_no_session",
    "refused_selection_order",
    "refused_incomplete_selection",
]


def _refusal_dict(outcome: str) -> dict[str, str]:
    return {
        "outcome": outcome,
        "reason": "no usable session",
        "limitation": "attach to a running process first. PyAEDT was not reached.",
        "template_text": "Cannot proceed: attach to a running process first.",
    }


@pytest.fixture
def session_status(variation: Variation) -> SessionStatus:
    return SessionStatus(
        connection_health="connected",
        suspect=False,
        selection=SelectionChain(process_id=4321, variation=variation),
        template_text="[session] connected",
    )


@pytest.fixture
def selection_options() -> SelectionOptions:
    return SelectionOptions(
        stage="design",
        options=[SelectionOption(value="HFSSDesign1", display="HFSSDesign1")],
        template_text="[options] design",
    )


@pytest.fixture
def inspection_result(
    inspection_provenance: InspectionProvenance,
) -> InspectionResult:
    return InspectionResult(
        sections={"variables": InspectionSection(data={"w": "2mm"}, read_status="ok")},
        provenance=inspection_provenance,
        template_text="[inspect] variables",
    )


@pytest.fixture
def native_validation_block(
    native_validation: NativeValidation,
    native_validation_provenance: NativeValidationProvenance,
) -> NativeValidationBlock:
    return NativeValidationBlock(
        validation=native_validation, provenance=native_validation_provenance
    )


@pytest.fixture
def validation_report(
    finding: Finding, native_validation_block: NativeValidationBlock
) -> ValidationReport:
    return ValidationReport(
        native=native_validation_block,
        findings=[finding],
        engine_status="absent",
        template_text="[validate]",
    )


def test_session_success_types_carry_no_outcome_field(
    session_status: SessionStatus,
    selection_options: SelectionOptions,
    inspection_result: InspectionResult,
    validation_report: ValidationReport,
) -> None:
    """The reason the discriminator is callable at all (gap 3).

    These success types are the on-the-wire shape of the tools that produce
    them, and the first is shared across roughly six unions
    (attach/select/get_session_status). A declared
    ``Field(discriminator="outcome")`` would have forced an ``outcome`` field
    onto every one of them, changing that wire format for every consumer just to
    tag a refusal. If this test ever fails, the success payloads have been
    tagged and the wire format has silently changed.
    """
    for model in (
        session_status,
        selection_options,
        inspection_result,
        validation_report,
    ):
        assert "outcome" not in type(model).model_fields
        assert "outcome" not in model.model_dump()


@pytest.mark.parametrize(
    ("union_name", "success_fixture", "success_type"),
    [
        ("_SELECT", "session_status", SessionStatus),
        ("_LIST_OPTIONS", "selection_options", SelectionOptions),
        ("_INSPECT", "inspection_result", InspectionResult),
        # ValidateSetupResult had ZERO routing coverage before ADR-23 — it was a
        # bare union no test ever exercised. Routing it here is the hole being
        # closed, not a formality.
        ("_VALIDATE_SETUP", "validation_report", ValidationReport),
    ],
)
def test_session_union_routes_every_arm_and_rejects_an_unknown_outcome(
    union_name: str,
    success_fixture: str,
    success_type: type,
    request: pytest.FixtureRequest,
) -> None:
    """ALL routes for one union, in one place: untagged success, cannot_evaluate,
    each of the three refusal remedies, and the unknown-outcome rejection."""
    adapter: TypeAdapter[Any] = globals()[union_name]
    success = request.getfixturevalue(success_fixture)

    # Untagged payload -> the success arm (absence of "outcome" IS the signal).
    assert isinstance(adapter.validate_python(success.model_dump()), success_type)
    # An adapter-reported PyAEDT failure keeps its own arm.
    assert isinstance(
        adapter.validate_python(_CANNOT_EVALUATE_DICT), CannotEvaluate
    )
    # Each refusal remedy routes to SelectionRefused and KEEPS its tag, so a
    # caller can branch on the tag alone without parsing the prose.
    for outcome in _SELECTION_REFUSAL_OUTCOMES:
        refused = adapter.validate_python(_refusal_dict(outcome))
        assert isinstance(refused, SelectionRefused)
        assert refused.outcome == outcome
    # An outcome the discriminator does not know must RAISE, never quietly land
    # on whichever arm happens to validate.
    with pytest.raises(ValidationError):
        adapter.validate_python({"outcome": "bogus", "template_text": "x"})


@pytest.mark.parametrize("union_name", ["_SELECT", "_ATTACH", "_LIST_OPTIONS"])
@pytest.mark.parametrize("lost_cause", ["crash", "disconnect", "unverifiable"])
def test_lost_cause_does_not_change_session_status_union_routing(
    union_name: str, lost_cause: str
) -> None:
    """gap 2 must not disturb gap 3's routing.

    ``lost_cause`` is an optional, defaulted, NON-``outcome`` field, and
    ``result_kind`` routes on the ABSENCE of an ``outcome`` key — so a
    SessionStatus that carries a cause is still an untagged success payload.
    _LIST_OPTIONS is included because a SessionStatus must NOT become routable on
    a union that does not list it, whatever fields it grows.
    """
    lost = SessionStatus(
        connection_health="disconnected",
        suspect=False,
        lost_cause=lost_cause,
        selection=SelectionChain(),
        template_text="[session] lost",
    )
    assert "outcome" not in lost.model_dump()
    if union_name == "_LIST_OPTIONS":
        with pytest.raises(ValidationError):
            _LIST_OPTIONS.validate_python(lost.model_dump())
        return
    routed = globals()[union_name].validate_python(lost.model_dump())
    assert isinstance(routed, SessionStatus)
    assert routed.lost_cause == lost_cause


def test_session_status_lost_cause_defaults_to_none_and_rejects_unknown() -> None:
    # Omitted means "not a lost session" — never "unknown cause".
    connected = SessionStatus(
        connection_health="connected",
        suspect=False,
        selection=SelectionChain(process_id=1),
        template_text="[session] connected",
    )
    assert connected.lost_cause is None
    # A cause outside the three recovery actions cannot be smuggled in.
    with pytest.raises(ValidationError):
        SessionStatus(
            connection_health="disconnected",
            suspect=False,
            lost_cause="timeout",  # type: ignore[arg-type]
            selection=SelectionChain(),
            template_text="x",
        )


@pytest.mark.parametrize("outcome", _SELECTION_REFUSAL_OUTCOMES)
def test_selection_refused_arm_routes_every_remedy(outcome: str) -> None:
    refused = _SELECT.validate_python(_refusal_dict(outcome))
    assert isinstance(refused, SelectionRefused)
    assert refused.outcome == outcome


def test_selection_refused_requires_an_outcome() -> None:
    # No default, for ExportRefused's reason: a refusal must state WHICH remedy
    # applies rather than silently inheriting one that cannot fix the problem.
    with pytest.raises(ValidationError):
        SelectionRefused(reason="r", limitation="l", template_text="x")  # type: ignore[call-arg]


def test_selection_refused_is_not_a_cannot_evaluate() -> None:
    # The whole point of gap 3: a session gate that never reached PyAEDT is a
    # distinct type from "PyAEDT could not evaluate this".
    refused = _SELECT.validate_python(_refusal_dict("refused_no_session"))
    assert not isinstance(refused, CannotEvaluate)


def test_attach_result_routes_success_and_cannot_evaluate(
    session_status: SessionStatus,
) -> None:
    assert isinstance(
        _ATTACH.validate_python(session_status.model_dump()), SessionStatus
    )
    assert isinstance(_ATTACH.validate_python(_CANNOT_EVALUATE_DICT), CannotEvaluate)


def test_attach_result_has_no_refusal_arm() -> None:
    """attach deliberately carries NO SelectionRefused arm.

    ``Session.attach`` runs no session gate — it IS the operation that
    establishes a session, and it takes no selection stage — so no producer can
    emit a refusal here. Advertising an arm nothing can inhabit would be its own
    small dishonesty, so the union rejects one.
    """
    with pytest.raises(ValidationError):
        _ATTACH.validate_python(_refusal_dict("refused_no_session"))


def test_inspection_result_rejects_unknown_section_key(
    inspection_provenance: InspectionProvenance,
) -> None:
    # The Literal-typed dict key means only real section names are accepted.
    with pytest.raises(ValidationError):
        InspectionResult(
            sections={"not_a_section": InspectionSection(data=None, read_status="ok")},
            provenance=inspection_provenance,
            template_text="x",
        )


def test_inspection_result_rejects_provenance_record(
    provenance: ProvenanceRecord,
) -> None:
    """A structural read may not borrow solve provenance (ADR-20, gap 11).

    ProvenanceRecord's extra solve fields are rejected by ``extra="forbid"``, so
    the swap is enforced by the schema rather than by reviewer vigilance.
    """
    with pytest.raises(ValidationError):
        InspectionResult(
            sections={},
            provenance=provenance.model_dump(),
            template_text="x",
        )


# --- every new schema constructs from representative valid data --------------


def test_preflight_and_process_schemas_construct() -> None:
    # The ATTACHED shape: all four versions known, and the AEDT one attributed
    # to the session it was read from. The pre-attach shape is exercised
    # separately below, because it is the one the §2 Environment could not hold.
    env = PreflightEnvironment(
        aedt_version="2026.1",
        aedt_version_source="attached_session",
        pyaedt_version="1.2.0",
        python_version="3.12.4",
        wrapper_version="0.0.0",
    )
    report = PreflightReport(
        environment=env,
        checks=[
            ComponentCheck(
                component="pyaedt",
                detected="1.2.0",
                required=">=1.2,<1.3",
                status="ok",
                detail="Supported.",
            ),
            ComponentCheck(
                component="license",
                detected=None,
                required="valid AEDT license",
                status="unavailable",
                detail="No license server reachable.",
            ),
        ],
        support_matrix_ref="docs/support-matrix.md",
        overall="incompatible",
        template_text="[preflight] 1 incompatibility",
    )
    assert report.overall == "incompatible"

    processes = AedtProcessList(
        processes=[
            AedtProcess(
                process_id=4321,
                grpc_port=50051,
            )
        ],
        template_text="[processes] 1 running",
    )
    assert processes.processes[0].process_id == 4321


# --- PreflightEnvironment: the pre-attach shape and its one invariant --------
#
# WHY THIS TYPE EXISTS AT ALL, restated once here so a reader of the tests does
# not have to find the schema to know what is being protected: preflight runs
# BEFORE any attach, preflight_environment has no cannot_evaluate arm and no
# refusal arm, and the §2 Environment requires four versions only an attached
# session can supply. Without a parallel type the honest pre-attach report was
# unconstructible. The first test below IS that state; the rest guard the one
# invariant the type adds.


def test_preflight_environment_allows_absent_aedt_and_pyaedt() -> None:
    """The pre-attach state on a machine with no AEDT and no ``live`` extra.

    This is not an edge case, it is the ordinary Journey 1.0 starting point and
    it is also public CI's own configuration — ``uv sync`` runs without the
    ``live`` extra on both OS legs, so ``pyaedt_version`` genuinely has no value
    there. A required field would make this report unconstructible in the very
    environment it exists to describe.
    """
    environment = PreflightEnvironment(
        python_version="3.12.10", wrapper_version="0.3.0"
    )
    assert environment.aedt_version is None
    assert environment.aedt_version_source is None
    assert environment.pyaedt_version is None
    # The two that are never absent stay required: omitting either is an error,
    # not a defaulted None. Asserted so a future edit cannot quietly give them
    # defaults and turn "always determinable" into "usually populated".
    with pytest.raises(ValidationError):
        PreflightEnvironment(wrapper_version="0.3.0")
    with pytest.raises(ValidationError):
        PreflightEnvironment(python_version="3.12.10")


def test_preflight_environment_rejects_a_version_without_a_source() -> None:
    # An unattributed version claim: the consumer cannot tell whether this is
    # the version of the process we are attached to or a guess about which
    # process an attach might bind to.
    with pytest.raises(ValidationError) as caught:
        PreflightEnvironment(
            aedt_version="2026.1",
            python_version="3.12.10",
            wrapper_version="0.3.0",
        )
    assert "must both be present or both be absent" in str(caught.value)


def test_preflight_environment_rejects_a_source_without_a_version() -> None:
    # The mirror case, tested separately rather than parametrized: a one-sided
    # validator would pass one of these two and fail the other, and a single
    # combined test could not say which half broke.
    with pytest.raises(ValidationError) as caught:
        PreflightEnvironment(
            aedt_version_source="installed_scan",
            python_version="3.12.10",
            wrapper_version="0.3.0",
        )
    assert "must both be present or both be absent" in str(caught.value)


@pytest.mark.parametrize("source", ["attached_session", "installed_scan"])
def test_preflight_environment_accepts_both_legal_sources(source: str) -> None:
    # The positive control for the two tests above. Without it they would still
    # pass against a validator that rejected everything.
    environment = PreflightEnvironment(
        aedt_version="2026.1",
        aedt_version_source=source,  # type: ignore[arg-type]
        python_version="3.12.10",
        wrapper_version="0.3.0",
    )
    assert environment.aedt_version_source == source


def test_preflight_environment_rejects_an_unknown_source() -> None:
    # The Literal is what keeps the provenance a closed vocabulary. A third
    # source would be a new KIND of claim about where a version came from, and
    # it must not be introducible by a producer typo — "scan" reads plausible
    # and would mean nothing to a consumer branching on the two real values.
    with pytest.raises(ValidationError):
        PreflightEnvironment(
            aedt_version="2026.1",
            aedt_version_source="scan",  # type: ignore[arg-type]
            python_version="3.12.10",
            wrapper_version="0.3.0",
        )


def test_session_and_selection_schemas_construct(variation: Variation) -> None:
    status = SessionStatus(
        connection_health="connected",
        suspect=True,
        selection=SelectionChain(
            process_id=4321,
            project=Project(name="patch_antenna", path=r"C:\proj\patch.aedt"),
            design="HFSSDesign1",
        ),
        template_text="[session] suspect",
    )
    assert status.suspect is True
    # A freshly-attached chain: only process_id set, everything downstream None.
    assert SelectionChain(process_id=4321).design is None

    name_options = SelectionOptions(
        stage="design",
        options=[SelectionOption(value="HFSSDesign1", display="HFSSDesign1")],
        template_text="[options] design",
    )
    variation_options = SelectionOptions(
        stage="variation",
        options=[SelectionOption(value=variation.variation_hash, variation=variation)],
        template_text="[options] variation",
    )
    assert name_options.stage == "design"
    assert variation_options.options[0].variation == variation


def test_validation_and_verified_result_schemas_construct(
    finding: Finding,
    metric: MetricRecord,
    solve_state: SolveState,
    provenance: ProvenanceRecord,
    validation_report: ValidationReport,
) -> None:
    assert validation_report.engine_status == "absent"
    # ADR-23's whole point, and untestable before it: native output lives in
    # its own structural block, attributed by NativeValidation's own literal.
    assert validation_report.native.validation.source == "hfss_native"
    assert validation_report.native.validation.raw_output
    # ...and `findings` is NOT where it lives. Every entry there is a real
    # Finding from one of the two sources the wrapper owns a judgment for, so
    # the seven-field evidence gate applies to all of them without exception.
    assert validation_report.findings == [finding]
    assert all(
        entry.source in ("gate", "engine_rule") for entry in validation_report.findings
    )
    assert SolutionValidityReport(gates=[finding], template_text="[gates]").gates == [
        finding
    ]
    assert (
        SolveHealthReport(
            solve_state=solve_state, provenance=provenance, template_text="[health]"
        ).solve_state.convergence_status
        == "converged"
    )


def test_validation_report_serializes_native_before_findings(
    validation_report: ValidationReport,
) -> None:
    """"Native first" is a guarantee this repo holds ONLY because of this test.

    ``ValidationReport`` declares ``native`` ahead of ``findings`` so that spec
    Point 2's "native always presented first" is a property of the emitted
    artifact rather than a sort every producer must remember to apply. But that
    only works because PYDANTIC serializes in field-declaration order — an
    implementation property of a dependency, not a promise this project owns.

    A future pydantic upgrade could reorder keys silently. The structural
    guarantee would evaporate, the docstrings asserting it would quietly become
    false, and every other test in this suite would stay green, because none of
    them look at key order. This test is what converts a borrowed property into
    one we hold: if it fails, the ordering claim is no longer true and the
    wording that states it has to change with it.

    Both serialization paths are asserted rather than one inferred from the
    other: pydantic emits python-mode and JSON separately, so agreement between
    them is a fact to check, not a given.
    """
    keys = list(validation_report.model_dump().keys())
    assert keys[0] == "native"
    assert keys.index("native") < keys.index("findings")

    json_keys = list(json.loads(validation_report.model_dump_json()).keys())
    assert json_keys[0] == "native"
    assert json_keys.index("native") < json_keys.index("findings")


def test_record_schemas_construct() -> None:
    intent = IntentObject(
        target_frequency_hz=2.4e9, threshold_type="s11", threshold_value=-10.0
    )
    state = DesignIntentState(intent=intent, template_text="[intent] set")
    assert state.intent == intent
    # The "not set" state is first-class, not an error.
    assert DesignIntentState(template_text="[intent] not set").intent is None

    log = AuditLog(
        records=[
            AuditRecord(
                timestamp=datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc),
                tool_name="compute_metrics",
                sanitized_arguments={"intent": None},
                selection_state={"design": "HFSSDesign1"},
                risk_tier="safe",
                outcome="ok",
                duration=0.42,
            )
        ],
        template_text="[audit] 1 record",
    )
    assert log.records[0].tool_name == "compute_metrics"


def test_request_schemas_construct() -> None:
    assert AttachRequest(process_id=4321).process_id == 4321
    assert ListSelectionOptionsRequest(stage="setup").stage == "setup"
    assert SelectRequest(stage="design", choice="HFSSDesign1").choice == "HFSSDesign1"
    # None default = full read-out; an explicit subset is also accepted.
    assert InspectDesignRequest().sections is None
    assert InspectDesignRequest(sections=["variables", "objects"]).sections == [
        "variables",
        "objects",
    ]
    assert ValidateSetupRequest().include_supplemental is True
    validity_req = CheckSolutionValidityRequest(target_frequency=2.4e9)
    assert validity_req.target_frequency == 2.4e9
    assert ComputeMetricsRequest().intent is None
    assert (
        ComputeMetricsRequest(
            intent=IntentObject(
                target_frequency_hz=2.4e9, threshold_type="vswr", threshold_value=2.0
            )
        ).intent.threshold_type
        == "vswr"
    )
    assert ExportResultsRequest(format="touchstone", path="out.s2p").overwrite is False
    assert GetAuditLogRequest().range is None
    assert GetAuditLogRequest(range=AuditLogRange(limit=100)).range.limit == 100
    assert ExportDiagnosticsBundleRequest(path="bundle.zip").overwrite is False


def test_extra_fields_are_forbidden_on_a_tool_io_schema() -> None:
    # StrictModel (extra="forbid") holds for the tool_io schemas too.
    with pytest.raises(ValidationError):
        AttachRequest(process_id=4321, unexpected="x")


# --- purity: importing contract.tool_io pulls in no pyaedt (ADR-3) -----------


def test_tool_io_import_pulls_in_no_pyaedt() -> None:
    # Fresh interpreter so no other test's imports can mask a leak.
    code = (
        "import sys\n"
        "import hfss_agent.contract.tool_io  # noqa: F401\n"
        "leaked = sorted(m for m in sys.modules "
        "if m == 'pyaedt' or m.startswith('pyaedt.'))\n"
        "assert not leaked, leaked\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
