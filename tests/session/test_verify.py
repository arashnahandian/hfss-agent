"""Reconnect-and-verify (W-2): no re-attach, proof-of-life, per-stage mismatch
reset, terminal faults, the empty-chain liveness probe, post-verify escalation,
and the resync override.

All faults are scripted via ``behavior_sequence`` — no real sleeps. The SUSPECT
trigger is always the first ``list_options`` call (chain-building uses only
``select``), so verify's re-drive runs on ``list_options`` calls 2+.
"""

from __future__ import annotations

import pytest
from session_helpers import (
    DEFAULT_PID,
    FULL_CHAIN,
    PROJECT_PATH,
    SOLUTION_TYPE,
    STAGES,
    attached,
    build_full_chain,
    force_suspect,
    list_timeout_then,
    make_session,
)

from hfss_agent.adapter.fake import OpBehavior, Scenario
from hfss_agent.adapter.results import (
    AdapterCannotEvaluate,
    AdapterDisconnect,
    AdapterInternalError,
    AdapterTimeout,
)
from hfss_agent.contract import Project
from hfss_agent.contract.tool_io import (
    CannotEvaluate,
    SelectionChain,
    SelectionRefused,
)
from hfss_agent.session.status import _Health, _LostCause, _SessionState


def _value(chain: SelectionChain, stage: str) -> object | None:
    return {
        "project": chain.project,
        "design": chain.design,
        "setup": chain.setup,
        "sweep": chain.sweep,
        "variation": chain.variation,
    }[stage]


# --- happy path --------------------------------------------------------------


def test_verify_happy_path_restores_full_chain() -> None:
    session, _ = attached(list_timeout_then())
    build_full_chain(session)
    force_suspect(session)
    assert session.get_session_status().suspect is True
    # a guarded op runs verify first; the whole chain re-confirms
    session.list_selection_options("project")
    status = session.get_session_status()
    assert session._state.health is _Health.ATTACHED and status.suspect is False
    chain = session._state.chain
    assert chain.project is not None and chain.project.name == "patch_antenna"
    assert chain.design == "HFSSDesign1" and chain.setup == "Setup1"
    assert chain.sweep == "Sweep1" and chain.variation is not None


# --- mismatch at each stage --------------------------------------------------


@pytest.mark.parametrize("mismatch_stage", STAGES)
def test_verify_mismatch_resets_from_stage_down(mismatch_stage) -> None:
    session, _ = attached(list_timeout_then())
    build_full_chain(session, stale_stage=mismatch_stage)
    force_suspect(session)
    session.list_selection_options("project")  # -> verify -> mismatch

    status = session.get_session_status()
    assert session._state.health is _Health.ATTACHED and status.suspect is False

    chain = session._state.chain
    idx = STAGES.index(mismatch_stage)
    for stage in STAGES[:idx]:  # upstream retained
        assert _value(chain, stage) is not None, f"{stage} should be retained"
    for stage in STAGES[idx:]:  # the stage and everything below cleared
        assert _value(chain, stage) is None, f"{stage} should be cleared"
    assert f"'{mismatch_stage}'" in (session._state.note or "")


# --- fault during verify is terminal (never re-enters verify) ----------------


def test_verify_fault_is_terminal_and_does_not_re_enter() -> None:
    # list_options call 1 = timeout (suspect); call 2 (verify's read) = disconnect.
    session, _ = attached(
        list_timeout_then(OpBehavior(fault=AdapterDisconnect(detail="verify drop")))
    )
    build_full_chain(session)
    force_suspect(session)
    session.list_selection_options("project")  # verify faults -> terminal LOST

    assert session._state.health is _Health.LOST
    assert session._state.lost_cause is _LostCause.DISCONNECT
    # LOST does not trigger verify, so the next op is refused (no re-entry loop)
    result = session.list_selection_options("project")
    assert isinstance(result, SelectionRefused)
    assert result.outcome == "refused_no_session" and "was lost" in result.limitation


# --- empty-chain liveness probe ----------------------------------------------


def test_empty_chain_probe_data_clears_suspect() -> None:
    session, _ = attached(list_timeout_then())  # no chain built -> empty chain
    force_suspect(session)
    session.list_selection_options("project")  # probe returns data -> alive
    assert session._state.health is _Health.ATTACHED
    assert session.get_session_status().suspect is False


def test_empty_chain_probe_fault_goes_lost() -> None:
    session, _ = attached(
        list_timeout_then(OpBehavior(fault=AdapterDisconnect(detail="x")))
    )
    force_suspect(session)
    session.list_selection_options("project")  # probe faults
    assert session._state.health is _Health.LOST


def test_empty_chain_probe_cannot_evaluate_goes_unverifiable_lost() -> None:
    session, _ = attached(
        list_timeout_then(
            OpBehavior(fault=AdapterCannotEvaluate(reason="r", limitation="l"))
        )
    )
    force_suspect(session)
    session.list_selection_options("project")  # probe cannot_evaluate: no proof of life
    assert session._state.health is _Health.LOST
    assert session._state.lost_cause is None  # unverifiable, NOT crash/disconnect
    text = session.get_session_status().template_text
    assert "no longer usable" in text
    assert "exited" not in text and "dropped" not in text


# --- post-verify AdapterInternalError escalation -----------------------------


def test_post_verify_internal_error_escalates_instead_of_re_verifying() -> None:
    # empty chain: verify's probe succeeds and clears suspect; then the op's own
    # select returns InternalError -> surfaced, and the session stays ATTACHED so
    # the next op does NOT re-verify and hit the same bug forever.
    scenario = Scenario(
        behavior_sequence={
            "list_options": [
                OpBehavior(
                    fault=AdapterTimeout(operation="list_options", limit_seconds=1.0)
                )
            ],
            "select": [
                OpBehavior(fault=AdapterInternalError(detail="incoherent scope"))
            ],
        }
    )
    session, _ = attached(scenario)
    force_suspect(session)
    result = session.select("project", "patch_antenna")
    # Deliberately still a CannotEvaluate, NOT a SelectionRefused: the select was
    # ATTEMPTED and failed on a persistent internal error (_internal_error_refusal).
    # A refusal type would claim we declined to try, which is not what happened.
    assert isinstance(result, CannotEvaluate)
    assert not isinstance(result, SelectionRefused)
    assert "internal inconsistency" in result.reason
    assert "PyAEDT was not the cause" in result.limitation
    assert session._state.health is _Health.ATTACHED  # NOT suspect -> no loop


def test_internal_error_without_prior_verify_goes_suspect() -> None:
    # Contrast: a first internal error (not post-verify) takes the normal path.
    session, _ = attached(
        Scenario(
            behavior={"select": OpBehavior(fault=AdapterInternalError(detail="x"))}
        )
    )
    session.select("project", "patch_antenna")
    assert session._state.health is _Health.SUSPECT


# --- resync fault overrides the ATTACHED that _reset_from set ----------------


def test_resync_fault_overrides_attached_with_lost() -> None:
    # White-box: place the session directly in SUSPECT with a design verify will
    # find stale, so the ONLY two `select` calls are verify's project re-drive
    # (call 1, canned OK) and resync's project re-select (call 2, scripted to
    # fault) — isolating the resync fault deterministically.
    scenario = Scenario(
        behavior_sequence={
            "select": [None, OpBehavior(fault=AdapterDisconnect(detail="resync boom"))]
        }
    )
    session, _ = make_session(scenario)
    session._state = _SessionState(
        health=_Health.SUSPECT,
        last_process_id=DEFAULT_PID,
        chain=SelectionChain(
            process_id=DEFAULT_PID,
            project=Project(name="patch_antenna", path=PROJECT_PATH),
            design="GHOST",  # verify finds this stale -> reset_from(design) -> resync
            solution_type=SOLUTION_TYPE,
        ),
    )
    result = session.list_selection_options("project")  # guarded op -> verify -> resync
    assert session._state.health is _Health.LOST
    assert session._state.lost_cause is _LostCause.DISCONNECT
    assert isinstance(result, SelectionRefused)
    assert result.outcome == "refused_no_session" and "was lost" in result.limitation


def test_full_chain_uses_every_stage() -> None:
    # Guard against a silently-shortened chain fixture masking coverage above.
    assert [stage for stage, _ in FULL_CHAIN] == list(STAGES)
    assert len(STAGES) == 5
