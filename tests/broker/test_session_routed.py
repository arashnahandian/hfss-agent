"""The five session-routed capabilities dispatched end-to-end over the
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
from hfss_agent.contract.tool_io import CannotEvaluate, SelectionOptions, SessionStatus


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


def test_selection_order_refusal_flows_through_as_cannot_evaluate() -> None:
    # Session-owned order enforcement (ADR-18 decision 4) surfaces through
    # dispatch untouched: selecting with no attached session is a typed
    # refusal, audited cannot_evaluate.
    broker, sink, _session, _fake = session_broker()
    result = broker.dispatch("select", {"stage": "project", "choice": "p"})

    assert isinstance(result, CannotEvaluate)
    assert sink.records[-1].outcome == "cannot_evaluate"


def test_select_adapter_fault_audits_ok_with_degraded_status() -> None:
    # A scripted adapter timeout during select: the session goes SUSPECT and
    # select returns a normal SessionStatus (suspect=True). The audit outcome
    # is "ok" — the documented gap-8 fidelity limit (plan §10, pending
    # contract amendment), pinned here so a future fix is a visible diff.
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


def test_inspect_design_selection_gap_flows_through_as_cannot_evaluate() -> None:
    # Freshly attached, nothing selected: the session's honest selection-gap
    # refusal surfaces through dispatch and audits cannot_evaluate — NOT ok, and
    # NOT a fabricated PyAEDT failure.
    broker, sink, _session, _fake = session_broker()
    broker.dispatch("attach", {"process_id": DEFAULT_PID})
    result = broker.dispatch("inspect_design", {})

    assert isinstance(result, CannotEvaluate)
    assert "pyaedt" not in result.limitation.lower()
    assert sink.records[-1].tool_name == "inspect_design"
    assert sink.records[-1].outcome == "cannot_evaluate"
