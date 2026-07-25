"""``Broker.require_environment`` — the non-dispatchable control-plane accessor
(W-5 prerequisite 2).

It is deliberately NOT a capability: not registered, not dispatchable, and
therefore never audited. What it must guarantee is that it reads THROUGH to the
session every time (a cached copy would outlive the process it describes) and
that it RAISES rather than answering ``None`` when there is no attached session,
so no caller can quietly stamp a missing version onto a record.

Everything drives the licence-free ``FakeAdapter`` via the shared broker helpers.
"""

from __future__ import annotations

import pytest
from broker_helpers import DEFAULT_PID, session_broker

from hfss_agent.adapter.fake import OpBehavior, Scenario
from hfss_agent.adapter.results import AdapterDisconnect
from hfss_agent.broker import NoAttachedSessionError
from hfss_agent.contract import Environment
from hfss_agent.contract.tool_io import SessionStatus

OTHER_PID = 5678

RELAUNCHED = Environment(
    aedt_version="2027.1",
    pyaedt_version="1.3.0",
    python_version="3.12.9",
    wrapper_version="0.0.0",
)


def test_require_environment_returns_the_attached_environment() -> None:
    broker, sink, _session, _fake = session_broker()
    broker.dispatch("attach", {"process_id": DEFAULT_PID})

    environment = broker.require_environment()

    assert isinstance(environment, Environment)
    assert environment.aedt_version == "2026.1"
    # Non-dispatchable: the accessor is not a capability, so it appends no audit
    # record. The attach dispatch above is still the only one in the log.
    assert [record.tool_name for record in sink.records] == ["attach"]


def test_require_environment_raises_when_never_attached() -> None:
    broker, _sink, _session, _fake = session_broker()

    with pytest.raises(NoAttachedSessionError) as excinfo:
        broker.require_environment()

    # The message names the remedy; it never implies a version exists.
    assert "no AEDT session is attached" in str(excinfo.value)


def test_require_environment_raises_after_the_session_is_lost() -> None:
    scenario = Scenario(
        behavior={"select": OpBehavior(fault=AdapterDisconnect(detail="dropped"))}
    )
    broker, _sink, session, _fake = session_broker(scenario)
    broker.dispatch("attach", {"process_id": DEFAULT_PID})
    assert broker.require_environment() is not None

    status = broker.dispatch("select", {"stage": "project", "choice": "patch_antenna"})
    assert isinstance(status, SessionStatus)
    assert status.lost_cause == "disconnect"

    # The session dropped its environment on the way to LOST; the broker holds no
    # copy to fall back on, so the invalid access raises instead of returning a
    # dead process's versions.
    with pytest.raises(NoAttachedSessionError):
        broker.require_environment()
    assert session.get_environment() is None


def test_require_environment_reads_through_after_a_reattach() -> None:
    # The no-caching proof: the session is re-attached to a DIFFERENT process
    # running different versions, WITHOUT the broker being told. A broker-side
    # cache would still be answering with the first process's versions here.
    scenario = Scenario()
    broker, _sink, _session, _fake = session_broker(scenario)
    broker.dispatch("attach", {"process_id": DEFAULT_PID})
    assert broker.require_environment() == scenario.environment

    scenario.environment = RELAUNCHED
    broker.dispatch("attach", {"process_id": OTHER_PID})

    assert broker.require_environment() == RELAUNCHED
