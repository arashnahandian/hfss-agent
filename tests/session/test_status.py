"""SessionStatus projection (status.py): determinism, three distinct LOST
templates that never imply the wrong cause, the typed ``lost_cause`` projection
for every internal situation, and the reachable disconnected+suspect safety
invariant.
"""

from __future__ import annotations

import pytest

from hfss_agent.contract.tool_io import SelectionChain
from hfss_agent.session.status import (
    _forbid_disconnected_suspect,
    _Health,
    _LostCause,
    _SessionState,
    build_status,
)


def _lost(cause, note=None) -> _SessionState:
    return _SessionState(
        health=_Health.LOST, last_process_id=7, lost_cause=cause, note=note
    )


def test_same_state_produces_same_text() -> None:
    a = _SessionState(health=_Health.ATTACHED, chain=SelectionChain(process_id=1))
    b = _SessionState(health=_Health.ATTACHED, chain=SelectionChain(process_id=1))
    assert build_status(a).template_text == build_status(b).template_text


def test_three_lost_variants_are_distinct() -> None:
    crash = build_status(_lost(_LostCause.CRASH)).template_text
    disc = build_status(_lost(_LostCause.DISCONNECT)).template_text
    unver = build_status(
        _lost(None, note="the liveness read could not list projects")
    ).template_text
    assert len({crash, disc, unver}) == 3


def test_lost_variants_do_not_imply_the_wrong_cause() -> None:
    crash = build_status(_lost(_LostCause.CRASH)).template_text
    disc = build_status(_lost(_LostCause.DISCONNECT)).template_text
    unver = build_status(_lost(None, note="probe failed")).template_text
    # crash: speaks of exit + a NEW pid, never "the same process"
    assert "exited" in crash and "same process" not in crash
    # disconnect: speaks of a dropped link + same pid, never an exit
    assert "dropped" in disc and "exited" not in disc
    # unverifiable: claims neither crash nor disconnect, and is a real sentence
    assert "exited" not in unver and "dropped" not in unver
    assert "no longer usable" in unver and "None" not in unver


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (_SessionState(health=_Health.ATTACHED), None),
        (_SessionState(health=_Health.SUSPECT), None),
        (_SessionState(health=_Health.DETACHED), None),
        (_SessionState(health=_Health.LOST, lost_cause=_LostCause.CRASH), "crash"),
        (
            _SessionState(health=_Health.LOST, lost_cause=_LostCause.DISCONNECT),
            "disconnect",
        ),
        (_SessionState(health=_Health.LOST, lost_cause=None), "unverifiable"),
    ],
    ids=["attached", "suspect", "detached", "lost_crash", "lost_disc", "lost_unver"],
)
def test_lost_cause_is_projected_for_every_internal_situation(
    state: _SessionState, expected: str | None
) -> None:
    """All six internal situations, pinned (gap 2).

    The load-bearing pair is DETACHED -> None vs. LOST-with-no-cause ->
    "unverifiable": both are ``state.lost_cause is None`` internally, and they
    must NOT collapse. A never-attached session has no cause to name; a LOST one
    with no nameable transport cause does, and saying so is the honest answer.
    """
    assert build_status(state).lost_cause == expected


def test_lost_cause_is_populated_only_when_disconnected() -> None:
    # The field is the WHY of a disconnection, so it can only be populated when
    # connection_health says there is one.
    for health in _Health:
        for cause in (None, _LostCause.CRASH, _LostCause.DISCONNECT):
            status = build_status(_SessionState(health=health, lost_cause=cause))
            if status.lost_cause is not None:
                assert status.connection_health == "disconnected"


def test_no_health_state_produces_disconnected_and_suspect() -> None:
    for health in _Health:
        status = build_status(
            _SessionState(health=health, chain=SelectionChain(process_id=1))
        )
        assert not (status.connection_health == "disconnected" and status.suspect)


def test_disconnected_suspect_invariant_is_reachable_and_raises() -> None:
    with pytest.raises(RuntimeError, match="disconnected"):
        _forbid_disconnected_suspect("disconnected", True)
    # the three valid combinations never raise
    _forbid_disconnected_suspect("connected", True)
    _forbid_disconnected_suspect("disconnected", False)
    _forbid_disconnected_suspect("connected", False)
