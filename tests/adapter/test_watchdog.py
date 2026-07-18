"""Per-call watchdog behavior (W-3).

Proves: a simulated hang resolves to a typed AdapterTimeout within the bound
(no real long sleep); an operational exception is caught and converted, never
escapes; a KeyboardInterrupt during the (stuck) call is NOT reclassified — it
behaves like Ctrl-C (revision 2). Uses a tiny timeout so nothing takes ~1s.
"""

import threading
import time

import pytest

from hfss_agent.adapter.fake import FakeAdapter, OpBehavior, Scenario
from hfss_agent.adapter.results import (
    AdapterInternalError,
    AdapterTimeout,
    SessionFault,
)
from hfss_agent.adapter.watchdog import run_with_watchdog

_TINY = 0.05  # 50 ms bound; a simulated hang resolves in about this long.


def test_hang_resolves_to_typed_timeout_within_the_bound() -> None:
    scenario = Scenario(behavior={"read_solve_state": OpBehavior(hang=True)})
    fake = FakeAdapter(scenario, timeout_seconds=_TINY)
    try:
        start = time.perf_counter()
        result = fake.read_solve_state()
        elapsed = time.perf_counter() - start

        assert isinstance(result, AdapterTimeout)
        assert isinstance(result, SessionFault)  # -> session marked suspect
        assert result.operation == "read_solve_state"
        assert result.limit_seconds == _TINY
        assert elapsed < 1.0  # never waits for the abandoned worker
    finally:
        fake.close()  # release the parked worker thread


def test_operational_exception_is_caught_and_converted_never_escapes() -> None:
    scenario = Scenario(
        behavior={"attach": OpBehavior(raises=ValueError("boom in pyaedt"))}
    )
    fake = FakeAdapter(scenario, timeout_seconds=_TINY)
    result = fake.attach(4321)  # returns normally; nothing propagates
    assert isinstance(result, AdapterInternalError)
    assert isinstance(result, SessionFault)
    assert "ValueError" in result.detail and "boom in pyaedt" in result.detail


def test_watchdog_passes_through_a_fast_success() -> None:
    sentinel = object()
    assert run_with_watchdog(lambda: sentinel, _TINY, "x") is sentinel


def test_watchdog_converts_a_raised_exception_directly() -> None:
    def boom():
        raise RuntimeError("kaboom")

    result = run_with_watchdog(boom, _TINY, "boom_op")
    assert isinstance(result, AdapterInternalError)
    assert "RuntimeError" in result.detail


def test_keyboardinterrupt_during_call_is_not_reclassified(monkeypatch) -> None:
    # Ctrl-C during a stuck call arrives on the main thread and interrupts the
    # join; the watchdog must let it propagate, not turn it into an adapter fault.
    def interrupting_join(self, timeout=None):
        raise KeyboardInterrupt

    monkeypatch.setattr(threading.Thread, "join", interrupting_join)
    with pytest.raises(KeyboardInterrupt):
        run_with_watchdog(lambda: "unused", _TINY, "stuck_op")
