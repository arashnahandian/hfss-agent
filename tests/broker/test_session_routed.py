"""The six session-routed capabilities dispatched end-to-end over the
``FakeAdapter`` — the pipeline proven against the real ``Session``, not only
synthetic handlers (approved plan §2/§13). Includes the capture-before proof
(``select``, the capability that changes the chain) and adapter-fault paths.

Faults are injected via scenario scripting, never real sleeps (the session
suite's determinism convention): a scripted ``fault=AdapterTimeout(...)``
makes the fake RETURN a timeout outcome directly.
"""

from __future__ import annotations

from broker_helpers import DEFAULT_PID, FULL_CHAIN, session_broker

from hfss_agent.adapter import AdapterTimeout
from hfss_agent.adapter.fake import OpBehavior, Scenario
from hfss_agent.broker import session_routed_specs
from hfss_agent.contract import NativeValidation
from hfss_agent.contract.tool_io import (
    CannotEvaluate,
    SelectionOptions,
    SelectionRefused,
    SessionStatus,
)


def test_attach_dispatches_and_audits_the_preattach_state() -> None:
    broker, sink, _session, _fake = session_broker()
    result = broker.dispatch("attach", {"process_id": DEFAULT_PID})

    assert isinstance(result, SessionStatus)
    assert result.connection_health == "connected"
    assert result.selection.process_id == DEFAULT_PID
    (record,) = sink.records
    assert record.tool_name == "attach"
    assert record.risk_tier == "safe"
    assert record.outcome == "ok"
    # Capture-before: the record carries the DETACHED (empty) chain the call
    # ran under, not the attached chain it produced.
    assert all(value is None for value in record.selection_state.values())


def test_select_audits_capture_before_not_capture_after() -> None:
    # THE capture-before proof: select changes the chain; its audit record
    # must show the chain as it stood when the call started.
    broker, sink, _session, _fake = session_broker()
    broker.dispatch("attach", {"process_id": DEFAULT_PID})
    result = broker.dispatch(
        "select", {"stage": "project", "choice": "patch_antenna"}
    )

    assert isinstance(result, SessionStatus)
    assert result.selection.project is not None
    assert result.selection.project.name == "patch_antenna"
    select_record = sink.records[-1]
    assert select_record.tool_name == "select"
    assert select_record.selection_state["process_id"] == DEFAULT_PID
    assert select_record.selection_state["project"] is None  # pre-call state
    assert select_record.sanitized_arguments == {
        "stage": "project",
        "choice": "patch_antenna",
    }


def test_full_chain_drive_through_dispatch() -> None:
    broker, sink, _session, _fake = session_broker()
    broker.dispatch("attach", {"process_id": DEFAULT_PID})
    for stage, choice in FULL_CHAIN:
        outcome = broker.dispatch("select", {"stage": stage, "choice": choice})
        assert isinstance(outcome, SessionStatus), (stage, outcome)

    status = broker.dispatch("get_session_status")
    assert isinstance(status, SessionStatus)
    assert status.selection.variation is not None
    # One audit record per call, in dispatch order.
    assert [record.tool_name for record in sink.records] == [
        "attach",
        *["select"] * len(FULL_CHAIN),
        "get_session_status",
    ]
    assert all(record.outcome == "ok" for record in sink.records)


def test_list_selection_options_dispatches_and_audits() -> None:
    broker, sink, _session, _fake = session_broker()
    broker.dispatch("attach", {"process_id": DEFAULT_PID})
    result = broker.dispatch("list_selection_options", {"stage": "project"})

    assert isinstance(result, SelectionOptions)
    assert "patch_antenna" in [option.value for option in result.options]
    assert sink.records[-1].tool_name == "list_selection_options"
    assert sink.records[-1].outcome == "ok"


def test_get_session_status_on_detached_session_is_a_pure_audited_read() -> None:
    broker, sink, _session, _fake = session_broker()
    result = broker.dispatch("get_session_status")

    assert isinstance(result, SessionStatus)
    assert result.connection_health == "disconnected"
    (record,) = sink.records
    assert record.outcome == "ok"
    assert all(value is None for value in record.selection_state.values())


def test_no_session_refusal_flows_through_as_a_gate_refusal() -> None:
    # A session-owned gate (ADR-18 decision 4) surfaces through dispatch
    # untouched: selecting with no attached session is refused by the
    # no-usable-session gate — a typed SelectionRefused — and the audit log calls
    # it a refusal, not cannot_evaluate, which would record a PyAEDT failure that
    # never happened.
    broker, sink, _session, _fake = session_broker()
    result = broker.dispatch("select", {"stage": "project", "choice": "p"})

    assert isinstance(result, SelectionRefused)
    assert result.outcome == "refused_no_session"
    assert sink.records[-1].outcome == "refused_by_gate"


def test_select_adapter_fault_audits_ok_with_degraded_status() -> None:
    # A scripted adapter timeout during select: the session goes SUSPECT and
    # select returns a normal SessionStatus (suspect=True), so the audit
    # outcome is still "ok" — the response shape genuinely IS a normal one and
    # the outcome field keeps its meaning.
    #
    # What the gap-8 amendment changed is that "ok" is no longer the WHOLE
    # record: session_degraded now separates a clean select from one that
    # damaged the session, which used to be indistinguishable in the log.
    # Both halves are pinned here — the unchanged outcome and the new signal.
    scenario = Scenario(
        behavior={
            "select": OpBehavior(
                fault=AdapterTimeout(operation="select", limit_seconds=1.0)
            )
        }
    )
    broker, sink, _session, _fake = session_broker(scenario)
    broker.dispatch("attach", {"process_id": DEFAULT_PID})
    result = broker.dispatch(
        "select", {"stage": "project", "choice": "patch_antenna"}
    )

    assert isinstance(result, SessionStatus)
    assert result.suspect is True
    assert sink.records[-1].tool_name == "select"
    assert sink.records[-1].outcome == "ok"
    # ATTACHED (rank 0) -> SUSPECT (rank 1): THIS call worsened the session.
    assert sink.records[-1].session_degraded is True
    # The attach that preceded it ran clean, so it must NOT be tarred by the
    # later fault — the field is a per-call delta, not a sticky session flag.
    assert sink.records[0].tool_name == "attach"
    assert sink.records[0].session_degraded is False


def test_a_call_on_an_already_degraded_session_is_not_reported_as_worsening() -> None:
    """The gap-8 delta's defining case: session_degraded answers "did THIS call
    worsen the session", not "is the session bad".

    After the select above leaves the session SUSPECT, a get_session_status
    (a pure read that neither re-verifies nor touches the adapter) finds it
    SUSPECT and leaves it SUSPECT — rank 1 -> 1. Reporting True there would
    blame this call for damage it did not do, and would make every subsequent
    call look like a fresh degradation. A plain boolean read of the post-state
    would do exactly that; the rank delta is why it does not.
    """
    scenario = Scenario(
        behavior={
            "select": OpBehavior(
                fault=AdapterTimeout(operation="select", limit_seconds=1.0)
            )
        }
    )
    broker, sink, _session, _fake = session_broker(scenario)
    broker.dispatch("attach", {"process_id": DEFAULT_PID})
    broker.dispatch("select", {"stage": "project", "choice": "patch_antenna"})
    assert sink.records[-1].session_degraded is True  # the call that DID it

    status = broker.dispatch("get_session_status")
    assert isinstance(status, SessionStatus)
    assert status.suspect is True  # the session is still degraded...
    assert sink.records[-1].tool_name == "get_session_status"
    assert sink.records[-1].session_degraded is False  # ...but this call is innocent


def test_list_options_adapter_fault_audits_cannot_evaluate() -> None:
    # The same fault through list_selection_options HAS no status arm, so the
    # session returns a typed CannotEvaluate — and the classifier audits it as
    # such: an end-to-end fault -> cannot_evaluate flow through the pipeline.
    scenario = Scenario(
        behavior={
            "list_options": OpBehavior(
                fault=AdapterTimeout(operation="list_options", limit_seconds=1.0)
            )
        }
    )
    broker, sink, _session, _fake = session_broker(scenario)
    broker.dispatch("attach", {"process_id": DEFAULT_PID})
    result = broker.dispatch("list_selection_options", {"stage": "project"})

    assert isinstance(result, CannotEvaluate)
    assert sink.records[-1].tool_name == "list_selection_options"
    assert sink.records[-1].outcome == "cannot_evaluate"


def test_inspect_design_dispatches_to_session_inspect_and_audits_safe() -> None:
    # inspect_design routes to session.inspect and returns the RAW section dict
    # (no InspectionResult assembly at this layer), audited safe-tier / ok.
    broker, sink, _session, _fake = session_broker()
    broker.dispatch("attach", {"process_id": DEFAULT_PID})
    broker.dispatch("select", {"stage": "project", "choice": "patch_antenna"})
    broker.dispatch("select", {"stage": "design", "choice": "HFSSDesign1"})
    result = broker.dispatch("inspect_design", {})

    assert isinstance(result, dict)
    assert "variables" in result and "available_results" in result
    record = sink.records[-1]
    assert record.tool_name == "inspect_design"
    assert record.risk_tier == "safe"
    assert record.outcome == "ok"


def test_inspect_design_selection_gap_flows_through_as_a_gate_refusal() -> None:
    # Freshly attached, nothing selected: the session's honest selection-gap
    # refusal surfaces through dispatch and audits refused_by_gate — NOT ok, and
    # NOT a fabricated PyAEDT failure.
    broker, sink, _session, _fake = session_broker()
    broker.dispatch("attach", {"process_id": DEFAULT_PID})
    result = broker.dispatch("inspect_design", {})

    assert isinstance(result, SelectionRefused)
    assert result.outcome == "refused_incomplete_selection"
    assert "pyaedt" not in result.limitation.lower()
    assert sink.records[-1].tool_name == "inspect_design"
    assert sink.records[-1].outcome == "refused_by_gate"


def test_validate_native_dispatches_to_the_session_method_and_audits_safe() -> None:
    # validate_native routes to session.validate_native and returns the RAW
    # NativeValidation (no block, no provenance at this layer), audited
    # safe-tier / ok. The tool the MCP surface will expose is validate_setup,
    # assembled by W-6 on top of THIS capability — the two names differ on
    # purpose, so W-6 gets no inspect_design-style collision to disambiguate.
    broker, sink, _session, _fake = session_broker()
    broker.dispatch("attach", {"process_id": DEFAULT_PID})
    broker.dispatch("select", {"stage": "project", "choice": "patch_antenna"})
    broker.dispatch("select", {"stage": "design", "choice": "HFSSDesign1"})
    result = broker.dispatch("validate_native", {})

    assert isinstance(result, NativeValidation)
    assert result.source == "hfss_native"
    assert result.raw_output == ["Design validation completed. 0 errors, 0 warnings."]
    record = sink.records[-1]
    assert record.tool_name == "validate_native"
    assert record.risk_tier == "safe"
    assert record.outcome == "ok"


def test_validate_native_selection_gap_flows_through_as_a_gate_refusal() -> None:
    # Freshly attached, nothing selected: the session's honest selection-gap
    # refusal surfaces through dispatch and audits refused_by_gate — NOT ok, and
    # NOT a fabricated PyAEDT failure. The message must also name the operation
    # it actually blocked, which is what makes it actionable.
    broker, sink, _session, _fake = session_broker()
    broker.dispatch("attach", {"process_id": DEFAULT_PID})
    result = broker.dispatch("validate_native", {})

    assert isinstance(result, SelectionRefused)
    assert result.outcome == "refused_incomplete_selection"
    assert "pyaedt" not in result.limitation.lower()
    assert "inspect" not in result.limitation.lower()
    assert sink.records[-1].tool_name == "validate_native"
    assert sink.records[-1].outcome == "refused_by_gate"


def test_validate_native_is_registered_safe_and_bound_to_the_session_method() -> None:
    # Thin delegation (ADR-18 decision 4): the handler IS the bound session
    # method, so selection gates and fault-to-lifecycle reconciliation stay the
    # session's alone and the broker adds only the pipeline.
    #
    # The safe-tier guarantee itself lives in tests/prohibited_ops/
    # test_tier_surface.py, which ITERATES the production registry and so covered
    # this capability the moment it was registered. This assertion is the local,
    # readable statement of the same fact — not the proof of record.
    _broker, _sink, session, _fake = session_broker()
    specs = session_routed_specs(session)
    spec = next(spec for spec in specs if spec.name == "validate_native")
    assert spec.tier == "safe"
    assert spec.handler == session.validate_native
