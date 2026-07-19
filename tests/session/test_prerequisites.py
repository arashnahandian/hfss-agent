"""Order enforcement and no-session refusals (W-2 is the SOLE order-enforcer,
since the adapter permits out-of-order selection).

Every refusal is a typed ``CannotEvaluate`` whose text states PyAEDT was not
reached — a knowing ADR-16-decision-5 deviation (the pinned unions offer no other
typed arm), made explicit rather than smuggled into an unchanged SessionStatus.
"""

from __future__ import annotations

import pytest
from session_helpers import attached, make_session

from hfss_agent.adapter.fake import OpBehavior, Scenario
from hfss_agent.adapter.results import AdapterDisconnect
from hfss_agent.contract.tool_io import CannotEvaluate
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
    assert isinstance(result, CannotEvaluate)
    assert result.reason == "selection order"
    assert f"select a {upstream} before selecting a {stage}" in result.limitation
    assert "PyAEDT was not reached" in result.limitation
    # refused without touching the chain (only process_id present)
    assert session._state.chain.model_dump(exclude_none=True) == {"process_id": 1234}


@pytest.mark.parametrize("stage, upstream", list(_PREREQ.items()))
def test_list_options_refuses_stage_without_prerequisite(stage, upstream) -> None:
    session, _ = attached()
    result = session.list_selection_options(stage)
    assert isinstance(result, CannotEvaluate)
    assert f"select a {upstream} before selecting a {stage}" in result.limitation
    assert "PyAEDT was not reached" in result.limitation


def test_detached_operations_are_refused() -> None:
    # project's "prerequisite" is an attached session; with none, both ops refuse.
    session, _ = make_session()  # never attached
    for result in (
        session.select("project", "x"),
        session.list_selection_options("project"),
    ):
        assert isinstance(result, CannotEvaluate)
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
        assert isinstance(result, CannotEvaluate)
        assert "was lost" in result.limitation
        assert "re-attach" in result.limitation
        assert "PyAEDT was not reached" in result.limitation
