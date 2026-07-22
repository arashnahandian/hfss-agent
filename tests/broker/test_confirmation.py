"""The medium/high confirmation flow — exercised via synthetic capabilities
defined here in the test file only, because nothing in the shipped surface can
reach it (the production registry is 100% safe-tier; that proof lands in
tests/prohibited_ops/ in Part 5).

The two properties under test, per the approved plan (§5, revision 1):
MEDIUM is confirm-or-refuse with deny-by-default; HIGH refuses unconditionally
BEFORE the confirmer — no approval, however emphatic, can run it until the
ADR-6 snapshot provider exists.
"""

from __future__ import annotations

import pytest
from broker_helpers import (
    ApproveAllConfirmer,
    ExplodingConfirmer,
    HandlerSpy,
    RecordingRefuseAllConfirmer,
    RecordingSink,
    make_broker,
    spec_for,
)

from hfss_agent.broker import ConfirmationRequest, DispatchRefused, RefuseAllConfirmer

_HOSTILE = "choice\x1b[2Jwipe"
_CLEAN = "choice[2Jwipe"


# --- medium tier --------------------------------------------------------------


def test_medium_refused_by_default_never_reaches_the_handler() -> None:
    spy = HandlerSpy()
    confirmer = RecordingRefuseAllConfirmer()
    broker, sink = make_broker(
        (spec_for(spy, name="synthetic_medium", tier="medium"),), confirmer=confirmer
    )
    result = broker.dispatch("synthetic_medium", {"arg": "v"})

    assert spy.calls == []  # the handler spy is never invoked
    assert isinstance(result, DispatchRefused)
    assert result.tier == "medium"
    assert "confirmation" in result.reason
    # The confirmer WAS consulted (unlike high tier) and refused.
    assert [request.capability for request in confirmer.requests] == [
        "synthetic_medium"
    ]
    assert isinstance(sink, RecordingSink)
    (record,) = sink.records
    assert record.risk_tier == "medium"
    assert record.outcome == "refused_by_gate"
    assert record.duration == 0.0  # the handler never ran
    # ...and for the same reason session_degraded is None, not False: nothing
    # ran that COULD have worsened the session, which is different from having
    # run and left it clean (gap 8).
    assert record.session_degraded is None


def test_medium_approved_runs_and_audits_ok() -> None:
    spy = HandlerSpy(result="ran")
    confirmer = ApproveAllConfirmer()
    spec = spec_for(spy, name="synthetic_medium", tier="medium")
    broker, sink = make_broker((spec,), confirmer=confirmer)
    result = broker.dispatch("synthetic_medium", {"arg": "v"})

    assert result == "ran"
    assert spy.calls == [{"arg": "v"}]
    assert isinstance(sink, RecordingSink)
    (record,) = sink.records
    assert record.risk_tier == "medium"
    assert record.outcome == "ok"
    # The confirmer saw the registered description, not an improvised one.
    (request,) = confirmer.requests
    assert request.description == spec.description
    assert request.tier == "medium"


def test_confirmation_request_carries_sanitized_arguments() -> None:
    # A confirmation prompt must never render raw untrusted strings (ADR-9):
    # the request carries the sanitized dict, same as the audit record.
    spy = HandlerSpy()
    confirmer = RecordingRefuseAllConfirmer()
    broker, _sink = make_broker(
        (spec_for(spy, name="synthetic_medium", tier="medium"),), confirmer=confirmer
    )
    broker.dispatch("synthetic_medium", {"choice": _HOSTILE})

    (request,) = confirmer.requests
    assert request.sanitized_arguments == {"choice": _CLEAN}


# --- high tier ----------------------------------------------------------------


@pytest.mark.parametrize(
    "confirmer_factory", [RecordingRefuseAllConfirmer, ApproveAllConfirmer]
)
def test_high_is_refused_unconditionally_and_confirmer_never_consulted(
    confirmer_factory: type,
) -> None:
    # Under BOTH a refuse-all and an approve-all confirmer: the handler spy is
    # never invoked and the confirmer is never even consulted — proving the
    # refusal happens BEFORE the confirmation step, not through it.
    spy = HandlerSpy()
    confirmer = confirmer_factory()
    broker, sink = make_broker(
        (spec_for(spy, name="synthetic_high", tier="high"),), confirmer=confirmer
    )
    result = broker.dispatch("synthetic_high", {"target": "x"})

    assert spy.calls == []
    assert confirmer.requests == []
    assert isinstance(result, DispatchRefused)
    assert result.tier == "high"
    assert isinstance(sink, RecordingSink)
    (record,) = sink.records
    assert record.risk_tier == "high"
    assert record.outcome == "refused_by_gate"
    assert record.session_degraded is None  # no handler ran (gap 8)


def test_high_refusal_names_the_adrs_and_the_missing_snapshot_provider() -> None:
    spy = HandlerSpy()
    broker, _sink = make_broker((spec_for(spy, name="synthetic_high", tier="high"),))
    result = broker.dispatch("synthetic_high")

    assert isinstance(result, DispatchRefused)
    assert "ADR-5" in result.reason
    assert "ADR-6" in result.reason
    assert "snapshot provider" in result.reason
    assert "does not exist" in result.reason


# --- safe tier ----------------------------------------------------------------


def test_safe_never_consults_the_confirmer() -> None:
    # ExplodingConfirmer raises if asked; a clean run IS the proof.
    spy = HandlerSpy(result="fine")
    broker, sink = make_broker((spec_for(spy),), confirmer=ExplodingConfirmer())
    assert broker.dispatch("synthetic") == "fine"
    assert isinstance(sink, RecordingSink)
    assert sink.records[0].outcome == "ok"


def test_refuse_all_confirmer_refuses_directly() -> None:
    request = ConfirmationRequest(
        capability="anything",
        tier="medium",
        description="anything",
        sanitized_arguments={},
    )
    assert RefuseAllConfirmer().confirm(request) is False
