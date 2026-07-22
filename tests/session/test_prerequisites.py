"""Order enforcement and no-session refusals (W-2 is the SOLE order-enforcer,
since the adapter permits out-of-order selection).

Every refusal here is a typed ``SelectionRefused`` — a session gate that declined
the call before it ever reached PyAEDT — never a ``CannotEvaluate``, which would
blame the solver for the wrapper's own refusal, and never an unchanged
SessionStatus, which ADR-16 decision 4 designed against. Each is asserted BOTH by
type and by its remedy tag, so a refusal cannot silently change which fix it
sends the caller to.
"""

from __future__ import annotations

import pytest
from session_helpers import attached, make_session

from hfss_agent.adapter.fake import OpBehavior, Scenario
from hfss_agent.adapter.results import AdapterDisconnect
from hfss_agent.contract.tool_io import CannotEvaluate, SelectionRefused
from hfss_agent.session.status import _Health

# Each downstream stage and the upstream it requires. ``project`` has no upstream
# stage (it requires only an attached session — see the DETACHED test below).
_PREREQ = {
    "design": "project",
    "setup": "design",
    "sweep": "setup",
    "variation": "sweep",
}


@pytest.mark.parametrize("stage, upstream", list(_PREREQ.items()))
def test_select_refuses_stage_without_prerequisite(stage, upstream) -> None:
    session, _ = attached()
    result = session.select(stage, "whatever")
    assert isinstance(result, SelectionRefused)
    assert result.outcome == "refused_selection_order"
    assert result.reason == "selection order"
    assert f"select a {upstream} before selecting a {stage}" in result.limitation
    assert "PyAEDT was not reached" in result.limitation
    # refused without touching the chain (only process_id present)
    assert session._state.chain.model_dump(exclude_none=True) == {"process_id": 1234}


@pytest.mark.parametrize("stage, upstream", list(_PREREQ.items()))
def test_list_options_refuses_stage_without_prerequisite(stage, upstream) -> None:
    session, _ = attached()
    result = session.list_selection_options(stage)
    assert isinstance(result, SelectionRefused)
    assert result.outcome == "refused_selection_order"
    assert f"select a {upstream} before selecting a {stage}" in result.limitation
    assert "PyAEDT was not reached" in result.limitation


def test_detached_operations_are_refused() -> None:
    # project's "prerequisite" is an attached session; with none, both ops refuse.
    session, _ = make_session()  # never attached
    for result in (
        session.select("project", "x"),
        session.list_selection_options("project"),
    ):
        assert isinstance(result, SelectionRefused)
        assert result.outcome == "refused_no_session"
        assert "no AEDT session is attached" in result.limitation
        assert "PyAEDT was not reached" in result.limitation


def test_lost_operations_are_refused_with_reattach_guidance() -> None:
    session, _ = attached(
        Scenario(behavior={"select": OpBehavior(fault=AdapterDisconnect(detail="x"))})
    )
    session.select("project", "patch_antenna")  # -> LOST
    assert session._state.health is _Health.LOST
    for result in (
        session.select("project", "x"),
        session.list_selection_options("project"),
    ):
        assert isinstance(result, SelectionRefused)
        # DETACHED and LOST share one tag: the remedy (attach / re-attach) is the
        # same, and it is the prose that distinguishes which state we were in.
        assert result.outcome == "refused_no_session"
        assert "was lost" in result.limitation
        assert "re-attach" in result.limitation
        assert "PyAEDT was not reached" in result.limitation


def test_a_session_gate_refusal_is_never_a_cannot_evaluate() -> None:
    """The gap-3 line itself: a refusal that never reached PyAEDT must not claim
    PyAEDT could not evaluate it. Pinned across all three gates so re-typing any
    one of them back to CannotEvaluate fails here, not in review."""
    detached, _ = make_session()
    attached_session, _ = attached()
    for result in (
        detached.select("project", "x"),  # refused_no_session
        attached_session.select("design", "x"),  # refused_selection_order
        attached_session.inspect(),  # refused_incomplete_selection
    ):
        assert isinstance(result, SelectionRefused)
        assert not isinstance(result, CannotEvaluate)
