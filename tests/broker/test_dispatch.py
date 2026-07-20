"""Dispatch-pipeline mechanics against synthetic capabilities (Part 2).

Each property is isolated with spy handlers here; the same pipeline is proven
end-to-end against the real ``Session`` + ``FakeAdapter`` in
``test_session_routed.py`` (including the capture-before proof via ``select``,
the capability that changes the chain).
"""

from __future__ import annotations

from datetime import timezone

import pytest
from broker_helpers import (
    HandlerSpy,
    RaisingSink,
    RecordingSink,
    make_broker,
    spec_for,
)

from hfss_agent.broker import (
    AuditFailure,
    DispatchRefused,
    UnknownCapability,
    classify_outcome,
)
from hfss_agent.contract.tool_io import CannotEvaluate, ExportRefused, MetricsRefused

# A control character the sanitizer strips (ESC — an ANSI-injection vector).
_HOSTILE = "name\x1b[31m"
_CLEAN = "name[31m"


def test_each_dispatch_appends_exactly_one_record() -> None:
    spy = HandlerSpy()
    broker, sink = make_broker((spec_for(spy),))
    broker.dispatch("synthetic")
    broker.dispatch("synthetic")
    assert isinstance(sink, RecordingSink)
    assert len(sink.records) == 2


def test_record_fields_are_sourced_per_the_plan_table() -> None:
    spy = HandlerSpy()
    broker, sink = make_broker((spec_for(spy),))
    result = broker.dispatch("synthetic", {"process_id": 7, "label": "plain"})

    assert result == "spy-result"
    assert isinstance(sink, RecordingSink)
    (record,) = sink.records
    assert record.tool_name == "synthetic"
    assert record.risk_tier == "safe"
    assert record.outcome == "ok"
    assert record.sanitized_arguments == {"process_id": 7, "label": "plain"}
    # Timestamp is timezone-aware UTC, captured at dispatch start.
    assert record.timestamp.tzinfo is not None
    assert record.timestamp.utcoffset() == timezone.utc.utcoffset(None)
    # Duration is handler wall-clock in seconds — a float, never negative.
    assert isinstance(record.duration, float)
    assert record.duration >= 0.0
    # No Part 2 capability emits a snapshot.
    assert record.snapshot_id is None
    # DETACHED session: the honest empty-chain value on every field.
    assert all(value is None for value in record.selection_state.values())


def test_handler_receives_raw_args_while_audit_stores_sanitized() -> None:
    # Sanitization applies to what the LOG renders, never to what the
    # capability computes on — silently rewriting an argument would make the
    # executed call differ from the requested one.
    spy = HandlerSpy()
    broker, sink = make_broker((spec_for(spy),))
    broker.dispatch("synthetic", {"choice": _HOSTILE})

    assert spy.calls == [{"choice": _HOSTILE}]
    assert isinstance(sink, RecordingSink)
    assert sink.records[0].sanitized_arguments == {"choice": _CLEAN}


def test_unknown_capability_is_typed_and_not_audited() -> None:
    broker, sink = make_broker(())
    result = broker.dispatch("no_such_capability", {"x": 1})

    assert isinstance(result, UnknownCapability)
    assert result.name == "no_such_capability"
    # Not audited: AuditRecord.risk_tier is required and an unregistered name
    # has no tier to audit under (module docstring point 1).
    assert isinstance(sink, RecordingSink)
    assert sink.records == []


def test_unknown_capability_name_is_sanitized() -> None:
    broker, _sink = make_broker(())
    result = broker.dispatch(_HOSTILE)
    assert isinstance(result, UnknownCapability)
    assert result.name == _CLEAN


# --- outcome classifier: the full table, through dispatch and directly -------


def _cannot_evaluate() -> CannotEvaluate:
    return CannotEvaluate(
        reason="r", limitation="lim", template_text="Cannot evaluate via PyAEDT: lim"
    )


def _export_refused() -> ExportRefused:
    return ExportRefused(
        path="C:/out.s2p", reason="path exists", template_text="Refused: path exists."
    )


def _metrics_refused() -> MetricsRefused:
    return MetricsRefused(failing_gates=[], template_text="Gates failed.")


@pytest.mark.parametrize(
    ("returned", "expected_outcome"),
    [
        (_cannot_evaluate(), "cannot_evaluate"),
        (_export_refused(), "refused_by_gate"),
        (_metrics_refused(), "refused_by_gate"),
        ("any plain value", "ok"),
    ],
)
def test_dispatch_audits_the_classified_outcome(
    returned: object, expected_outcome: str
) -> None:
    spy = HandlerSpy(result=returned)
    broker, sink = make_broker((spec_for(spy),))
    result = broker.dispatch("synthetic")

    assert result is returned  # the classified value is still returned as-is
    assert isinstance(sink, RecordingSink)
    assert sink.records[0].outcome == expected_outcome


def test_classifier_is_total_including_broker_domain_backstop() -> None:
    assert classify_outcome(_cannot_evaluate()) == "cannot_evaluate"
    assert classify_outcome(_export_refused()) == "refused_by_gate"
    assert classify_outcome(_metrics_refused()) == "refused_by_gate"
    refusal = DispatchRefused(capability="c", tier="medium", reason="denied")
    assert classify_outcome(refusal) == "refused_by_gate"
    # Broker-domain failures normally surface as exceptions (audited
    # typed_error on the exception path); the value backstop stays total.
    unknown = UnknownCapability(name="nope")
    assert classify_outcome(unknown) == "typed_error"
    assert classify_outcome(None) == "ok"
    assert classify_outcome(object()) == "ok"


# --- exception and sink-failure paths ----------------------------------------


def test_handler_exception_is_audited_typed_error_and_surfaced() -> None:
    spy = HandlerSpy(raises=RuntimeError("boom"))
    broker, sink = make_broker((spec_for(spy),))

    with pytest.raises(RuntimeError, match="boom"):
        broker.dispatch("synthetic")

    assert isinstance(sink, RecordingSink)
    (record,) = sink.records
    assert record.outcome == "typed_error"
    assert record.tool_name == "synthetic"
    assert record.duration >= 0.0


def test_sink_failure_withholds_result_and_returns_loud_audit_failure() -> None:
    spy = HandlerSpy(result="payload")
    broker, _sink = make_broker((spec_for(spy),), sink=RaisingSink())
    result = broker.dispatch("synthetic")

    # The handler DID run — the failure is misreported to no one.
    assert spy.calls == [{}]
    assert isinstance(result, AuditFailure)
    assert result.capability == "synthetic"
    assert result.unaudited_outcome == "ok"
    assert "OSError" in result.detail
    assert "could not be written" in result.notice
    assert "withheld" in result.notice


def test_sink_failure_after_handler_exception_swallows_neither() -> None:
    # Corner case: handler raised AND the audit append raised. The sink error
    # propagates with the handler error chained as __context__ — both visible,
    # neither swallowed.
    spy = HandlerSpy(raises=ValueError("handler failure"))
    broker, _sink = make_broker((spec_for(spy),), sink=RaisingSink())

    with pytest.raises(OSError, match="simulated audit sink failure") as excinfo:
        broker.dispatch("synthetic")
    assert isinstance(excinfo.value.__context__, ValueError)
