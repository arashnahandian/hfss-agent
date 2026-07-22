"""Adapter outcome -> session transition (W-2).

Each of the six outcomes maps to exactly one transition, and crash/disconnect/
timeout never collapse (ADR-10 / ADR-17 #3). Also covers attach: success ->
ATTACHED, any fault -> DETACHED (suspect/lost presuppose a prior session).
"""

from __future__ import annotations

import pytest
from session_helpers import attached, make_session

from hfss_agent.adapter.fake import OpBehavior, Scenario
from hfss_agent.adapter.results import (
    AdapterCannotEvaluate,
    AdapterCrash,
    AdapterDisconnect,
    AdapterInternalError,
    AdapterTimeout,
)
from hfss_agent.contract.tool_io import CannotEvaluate, SessionStatus
from hfss_agent.session.status import _Health, _LostCause, build_status

# --- operation outcomes (triggered on select) --------------------------------


def test_success_advances_chain_and_stays_attached() -> None:
    session, _ = attached()
    result = session.select("project", "patch_antenna")
    assert isinstance(result, SessionStatus)
    assert session._state.health is _Health.ATTACHED
    assert result.selection.project is not None
    assert result.selection.project.name == "patch_antenna"


def test_cannot_evaluate_stays_attached_and_leaves_chain_untouched() -> None:
    # call 1 (project) succeeds; call 2 (design) returns cannot_evaluate.
    scenario = Scenario(
        behavior_sequence={
            "select": [
                None,
                OpBehavior(
                    fault=AdapterCannotEvaluate(reason="r", limitation="unreadable")
                ),
            ]
        }
    )
    session, _ = attached(scenario)
    session.select("project", "patch_antenna")
    before = session._state.chain
    result = session.select("design", "HFSSDesign1")
    assert isinstance(result, CannotEvaluate)
    assert session._state.health is _Health.ATTACHED  # not a session fault
    assert session._state.chain == before  # design never added


@pytest.mark.parametrize(
    "fault, health, cause, reported_cause",
    [
        (
            AdapterTimeout(operation="select", limit_seconds=1.0),
            _Health.SUSPECT,
            None,
            None,
        ),
        (AdapterInternalError(detail="boom"), _Health.SUSPECT, None, None),
        (
            AdapterDisconnect(detail="dropped"),
            _Health.LOST,
            _LostCause.DISCONNECT,
            "disconnect",
        ),
        (AdapterCrash(detail="died"), _Health.LOST, _LostCause.CRASH, "crash"),
    ],
)
def test_fault_maps_to_its_transition(fault, health, cause, reported_cause) -> None:
    session, _ = attached(Scenario(behavior={"select": OpBehavior(fault=fault)}))
    session.select("project", "patch_antenna")
    assert session._state.health is health
    assert session._state.lost_cause is cause
    # The internal distinction now also reaches the caller as a typed field.
    assert build_status(session._state).lost_cause == reported_cause


def test_disconnect_and_crash_do_not_collapse() -> None:
    disc, _ = attached(
        Scenario(behavior={"select": OpBehavior(fault=AdapterDisconnect(detail="x"))})
    )
    crash, _ = attached(
        Scenario(behavior={"select": OpBehavior(fault=AdapterCrash(detail="y"))})
    )
    disc.select("project", "patch_antenna")
    crash.select("project", "patch_antenna")
    assert disc._state.lost_cause is _LostCause.DISCONNECT
    assert crash._state.lost_cause is _LostCause.CRASH
    assert disc._state.lost_cause is not crash._state.lost_cause
    # ...and the contract no longer flattens them: connection_health still
    # collapses both to "disconnected" (it is the binary reachability signal),
    # while lost_cause carries the differing recovery action (gap 2).
    disc_status, crash_status = build_status(disc._state), build_status(crash._state)
    assert disc_status.connection_health == crash_status.connection_health
    assert disc_status.connection_health == "disconnected"
    assert (disc_status.lost_cause, crash_status.lost_cause) == ("disconnect", "crash")


# --- attach ------------------------------------------------------------------


def test_attach_success_is_connected_and_unsuspect() -> None:
    session, _ = make_session()
    result = session.attach(4321)
    assert isinstance(result, SessionStatus)
    assert result.connection_health == "connected" and result.suspect is False
    assert session._state.health is _Health.ATTACHED
    assert result.selection.process_id == 4321


@pytest.mark.parametrize(
    "fault",
    [
        AdapterTimeout(operation="attach", limit_seconds=1.0),
        AdapterInternalError(detail="boom"),
        AdapterDisconnect(detail="dropped"),
        AdapterCrash(detail="died"),
    ],
)
def test_attach_fault_goes_detached(fault) -> None:
    session, _ = make_session(Scenario(behavior={"attach": OpBehavior(fault=fault)}))
    result = session.attach(1)
    assert session._state.health is _Health.DETACHED
    assert isinstance(result, SessionStatus)
    assert result.connection_health == "disconnected" and result.suspect is False
    # All four faults collapse here, in BOTH fields, and that is correct: a failed
    # attach is DETACHED, not LOST — there was never a session to lose, so even
    # the crash fault has no lost-session cause to name. lost_cause explains a
    # LOST session only; DETACHED must not borrow "unverifiable" (gap 2).
    assert result.lost_cause is None
