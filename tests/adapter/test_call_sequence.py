"""Per-call-sequence fault scripting on the FakeAdapter (W-3 prerequisite for W-2).

``Scenario.behavior_sequence`` lets a test script "call 1 faults, call 2
recovers" — the exact shape the session module's reconnect/verify tests need.
Verifies the sequence is consumed one entry per call, that a ``None`` entry
yields canned data, that an exhausted sequence falls through to the static
per-op behavior, that the reconnect shape (hang then recover) is scriptable, and
that purely static scenarios are unchanged.
"""

from __future__ import annotations

from hfss_agent.adapter.fake import FakeAdapter, OpBehavior, Scenario
from hfss_agent.adapter.results import (
    AdapterCrash,
    AdapterDisconnect,
    AdapterTimeout,
)
from hfss_agent.contract import Environment, SolveState

_TINY = 0.05  # 50 ms watchdog bound for the hang-then-recover case.


def test_op_faults_on_first_call_then_recovers_on_second() -> None:
    # The canonical reconnect shape: attach disconnects once, then succeeds.
    scenario = Scenario(
        behavior_sequence={
            "attach": [OpBehavior(fault=AdapterDisconnect(detail="dropped"))]
        }
    )
    fake = FakeAdapter(scenario)
    first = fake.attach(1234)
    second = fake.attach(1234)
    assert isinstance(first, AdapterDisconnect)
    assert isinstance(second, Environment)  # sequence exhausted -> canned data


def test_none_entry_returns_canned_data_that_call() -> None:
    scenario = Scenario(
        behavior_sequence={
            "attach": [None, OpBehavior(fault=AdapterCrash(detail="died"))]
        }
    )
    fake = FakeAdapter(scenario)
    assert isinstance(fake.attach(1), Environment)  # call 1: None -> canned
    assert isinstance(fake.attach(1), AdapterCrash)  # call 2: scripted fault
    assert isinstance(fake.attach(1), Environment)  # call 3: exhausted -> canned


def test_exhausted_sequence_falls_through_to_static_behavior() -> None:
    # First call scripted to recover (None); every call after falls to the static
    # per-op override, proving the two axes compose predictably.
    scenario = Scenario(
        behavior={
            "read_solve_state": OpBehavior(fault=AdapterDisconnect(detail="x"))
        },
        behavior_sequence={"read_solve_state": [None]},
    )
    fake = FakeAdapter(scenario)
    assert isinstance(fake.read_solve_state(), SolveState)  # call 1: None -> canned
    assert isinstance(fake.read_solve_state(), AdapterDisconnect)  # call 2: static
    assert isinstance(fake.read_solve_state(), AdapterDisconnect)  # call 3: static


def test_hang_then_recover_is_scriptable_for_reconnect_tests() -> None:
    # Call 1 hangs -> watchdog abandons it -> AdapterTimeout (session suspect);
    # call 2 returns canned data. This is exactly the session reconnect path.
    # The AdapterTimeout assertion also proves the hung worker ran past its
    # per-op counter increment, so call 2 deterministically sees index 1.
    scenario = Scenario(
        behavior_sequence={"read_solve_state": [OpBehavior(hang=True)]}
    )
    fake = FakeAdapter(scenario, timeout_seconds=_TINY)
    try:
        first = fake.read_solve_state()
        second = fake.read_solve_state()
        assert isinstance(first, AdapterTimeout)
        assert isinstance(second, SolveState)
    finally:
        fake.close()  # release the parked worker thread


def test_static_only_scenarios_are_unchanged() -> None:
    # No behavior_sequence: the static override applies on every call, exactly as
    # before this feature existed.
    scenario = Scenario(
        behavior={"attach": OpBehavior(fault=AdapterDisconnect(detail="dropped"))}
    )
    fake = FakeAdapter(scenario)
    assert isinstance(fake.attach(1), AdapterDisconnect)
    assert isinstance(fake.attach(1), AdapterDisconnect)
