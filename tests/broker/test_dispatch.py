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
from pydantic import ValidationError

from hfss_agent.broker import (
    AuditFailure,
    DispatchRefused,
    UnknownCapability,
    classify_outcome,
)
from hfss_agent.broker.broker import BrokerOutcome
from hfss_agent.contract.tool_io import (
    CannotEvaluate,
    ExportRefused,
    MetricsRefused,
    SelectionRefused,
)

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


def test_exactly_one_record_holds_for_the_unregistered_path_too() -> None:
    # Gap 9 closed the one path that appended ZERO records, so "exactly one
    # record per dispatch ATTEMPT" is now universal rather than a rule with an
    # unstated exception. Mixed here on purpose: registered and unregistered
    # dispatches must contribute one record each, in call order.
    spy = HandlerSpy()
    broker, sink = make_broker((spec_for(spy),))
    broker.dispatch("synthetic")
    broker.dispatch("no_such_capability")
    broker.dispatch("synthetic")

    assert isinstance(sink, RecordingSink)
    assert [record.tool_name for record in sink.records] == [
        "synthetic",
        "no_such_capability",
        "synthetic",
    ]


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
    # The handler RAN, so session_degraded is applicable — and False: a spy
    # handler touches no session, so nothing worsened. Note DETACHED ranks
    # clean, not degraded: "no session" is not a damaged one.
    assert record.session_degraded is False
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


def test_unknown_capability_is_typed_and_audited_without_a_tier() -> None:
    # INVERTED by the gap-9 amendment. This path used to append ZERO records
    # because AuditRecord.risk_tier was required and an unregistered name has
    # no honest tier to state. risk_tier is now optional for exactly this case,
    # so the attempt is on the record — which matters because an
    # unregistered-name dispatch is what a bypass attempt or a wiring bug looks
    # like.
    broker, sink = make_broker(())
    result = broker.dispatch("no_such_capability", {"x": 1})

    assert isinstance(result, UnknownCapability)
    assert result.name == "no_such_capability"
    assert isinstance(sink, RecordingSink)
    (record,) = sink.records
    assert record.tool_name == "no_such_capability"
    assert record.risk_tier is None  # never fabricated
    assert record.outcome == "unknown_capability"
    assert record.sanitized_arguments == {"x": 1}
    # No handler ran, so neither timing nor a health delta is applicable.
    assert record.duration == 0.0
    assert record.session_degraded is None


def test_unknown_capability_name_is_sanitized() -> None:
    broker, sink = make_broker(())
    result = broker.dispatch(_HOSTILE)
    assert isinstance(result, UnknownCapability)
    assert result.name == _CLEAN
    # The log is a rendering surface too: the attempted name lands there
    # sanitized, not raw, so a hostile name cannot inject through the audit
    # trail either.
    assert isinstance(sink, RecordingSink)
    assert sink.records[0].tool_name == _CLEAN


def test_registered_handler_returning_unknown_capability_fails_loud() -> None:
    """INTENDED behaviour, pinned deliberately rather than softened.

    A REGISTERED handler that returns ``UnknownCapability`` is a wiring bug:
    the name resolved, so the record carries a real tier, while the classifier
    reads the returned value as ``unknown_capability`` — the one pairing the
    both-or-neither validator forbids. The record therefore cannot be built and
    the dispatch raises at construction.

    Failing loud here is the point. Degrading this to ``typed_error`` would let
    a broken handler quietly produce a well-formed record whose tier and
    outcome disagree about whether a capability was registered at all, which is
    exactly the ambiguity the validator exists to prevent. End-to-end cover for
    what the classifier pin and the schema validator pins each prove one half
    of.
    """
    spy = HandlerSpy(result=UnknownCapability(name="nope"))
    broker, sink = make_broker((spec_for(spy),))

    with pytest.raises(ValidationError, match="requires risk_tier=None"):
        broker.dispatch("synthetic")

    # It raises BEFORE the sink is reached, so no misleading record is written.
    assert isinstance(sink, RecordingSink)
    assert sink.records == []


def test_unknown_capability_sink_failure_still_fails_closed() -> None:
    # The new audit path inherits the fail-closed stance rather than quietly
    # bypassing it: if the unregistered-name record cannot be written, the
    # typed UnknownCapability is WITHHELD and a loud AuditFailure returned.
    broker, _sink = make_broker((), sink=RaisingSink())
    result = broker.dispatch("no_such_capability")

    assert isinstance(result, AuditFailure)
    assert result.capability == "no_such_capability"
    assert result.unaudited_outcome == "unknown_capability"
    assert "not registered" in result.notice
    assert "withheld" in result.notice


# --- outcome classifier: the full table, through dispatch and directly -------


def _cannot_evaluate() -> CannotEvaluate:
    return CannotEvaluate(
        reason="r", limitation="lim", template_text="Cannot evaluate via PyAEDT: lim"
    )


def _export_refused() -> ExportRefused:
    return ExportRefused(
        outcome="refused_existing_path",
        path="C:/out.s2p",
        reason="path exists",
        template_text="Refused: path exists.",
    )


def _metrics_refused() -> MetricsRefused:
    return MetricsRefused(failing_gates=[], template_text="Gates failed.")


def _selection_refused(outcome: str = "refused_no_session") -> SelectionRefused:
    return SelectionRefused(
        outcome=outcome,
        reason="no usable session",
        limitation="attach first. PyAEDT was not reached.",
        template_text="Cannot proceed: attach first.",
    )


@pytest.mark.parametrize(
    ("returned", "expected_outcome"),
    [
        (_cannot_evaluate(), "cannot_evaluate"),
        (_export_refused(), "refused_by_gate"),
        (_metrics_refused(), "refused_by_gate"),
        (_selection_refused(), "refused_by_gate"),
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
    assert classify_outcome(_selection_refused()) == "refused_by_gate"
    refusal = DispatchRefused(capability="c", tier="medium", reason="denied")
    assert classify_outcome(refusal) == "refused_by_gate"
    # Gap 9: UnknownCapability has its OWN outcome now — it is no longer swept
    # into the backstop below as a generic typed_error.
    assert classify_outcome(UnknownCapability(name="nope")) == "unknown_capability"
    # Broker-domain failures normally surface as exceptions (audited
    # typed_error on the exception path); the value backstop stays total, and
    # still catches a BrokerOutcome that is neither a refusal nor an unknown
    # name.
    assert classify_outcome(AuditFailure(
        capability="c", unaudited_outcome="ok", detail="d", notice="n"
    )) == "typed_error"
    assert classify_outcome(None) == "ok"
    assert classify_outcome(object()) == "ok"


def test_unknown_capability_arm_precedes_the_broker_outcome_backstop() -> None:
    """ORDERING PIN for the gap-9 arm — load-bearing, not documentation.

    ``UnknownCapability`` IS a ``BrokerOutcome``, so the two arms are NESTED
    (unlike the disjoint CannotEvaluate/SelectionRefused pair). Placed after
    the backstop, the new arm would be dead code and an unregistered-name
    dispatch would classify ``typed_error`` again — which the AuditRecord
    both-or-neither validator would then reject outright, because the dispatch
    path passes ``risk_tier=None`` for it. Swapping the arms therefore does not
    merely mislabel: it makes the path raise.
    """
    unknown = UnknownCapability(name="nope")
    assert isinstance(unknown, BrokerOutcome)  # the nesting the order guards
    assert classify_outcome(unknown) == "unknown_capability"
    assert classify_outcome(unknown) != "typed_error"


@pytest.mark.parametrize(
    "outcome",
    ["refused_no_session", "refused_selection_order", "refused_incomplete_selection"],
)
def test_every_selection_refusal_remedy_audits_as_a_refusal(outcome: str) -> None:
    # All three remedies are refusals in the log. A new remedy tag added to the
    # contract without a classifier branch would fall through to "ok" and hide a
    # refusal — the one thing this log must never do.
    assert classify_outcome(_selection_refused(outcome)) == "refused_by_gate"


def test_selection_refused_is_classified_a_refusal_not_a_cannot_evaluate() -> None:
    """ORDERING PIN for the gap-3 arm.

    ``SelectionRefused`` and ``CannotEvaluate`` are disjoint types, so the
    cannot_evaluate branch preceding the refusal branch is documentation rather
    than a correctness dependency — but the CLASSIFICATION is load-bearing: a
    session gate that never reached PyAEDT must be audited as a refusal, never
    as a PyAEDT failure. (Contrast the DispatchRefused/BrokerOutcome pair below,
    where order genuinely is load-bearing because the types are nested.)
    """
    assert classify_outcome(_selection_refused()) == "refused_by_gate"
    assert classify_outcome(_selection_refused()) != "cannot_evaluate"
    # And the reverse direction stays intact: an adapter-reported cannot_evaluate
    # must not be swept into the broadened refusal arm.
    assert classify_outcome(_cannot_evaluate()) == "cannot_evaluate"


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
