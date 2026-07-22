"""inspect (W-2 session read) — plumbing for the inspect_design capability.

Drives the licence-free ``FakeAdapter``; faults are injected via ``OpBehavior``
scenario scripting, never real sleeps (the session suite's determinism
convention). This layer returns the RAW section dict on success — no
``InspectionResult``, ``template_text``, or provenance; that is the W-5 module's
job.

Its two non-success arms are kept apart on the refusal-vs-failure line: a session
gate that declined BEFORE PyAEDT was reached (no usable session, an incomplete
selection) is a ``SelectionRefused``; an operation that WAS attempted and did not
complete (an adapter fault, or a genuine adapter cannot_evaluate) is a
``CannotEvaluate``.
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
from hfss_agent.contract import InspectionSection
from hfss_agent.contract.tool_io import CannotEvaluate, SelectionRefused
from hfss_agent.session import Session
from hfss_agent.session.status import _Health, _LostCause

# The eight sections the default fake scenario returns.
_ALL_SECTIONS = {
    "variables",
    "objects",
    "materials",
    "boundaries",
    "excitations_ports",
    "setups",
    "sweeps",
    "available_results",
}


def _scoped(scenario: Scenario | None = None) -> tuple[Session, object]:
    """An attached session with project+design selected — the inspect
    prerequisite — over a FakeAdapter driven by ``scenario`` (which scripts ops
    other than attach/select, so the setup drive succeeds)."""
    session, fake = attached(scenario)
    session.select("project", "patch_antenna")
    session.select("design", "HFSSDesign1")
    assert session._state.health is _Health.ATTACHED
    return session, fake


# --- success arm: raw section dict -------------------------------------------


def test_clean_inspect_returns_all_sections() -> None:
    session, _ = _scoped()
    result = session.inspect()
    assert isinstance(result, dict)
    assert set(result) == _ALL_SECTIONS
    assert all(isinstance(section, InspectionSection) for section in result.values())
    assert result["objects"].data == ["Patch", "Substrate", "GroundPlane"]
    assert result["objects"].read_status == "ok"
    assert session._state.health is _Health.ATTACHED


def test_subset_returns_only_requested_sections() -> None:
    session, _ = _scoped()
    result = session.inspect(["variables", "setups"])
    assert isinstance(result, dict)
    assert set(result) == {"variables", "setups"}
    assert result["variables"].data == {"width": "2.0mm", "height": "1.6mm"}


# --- Change 1: honest selection-gap refusal ----------------------------------


def test_nothing_selected_is_an_honest_selection_gap_refusal() -> None:
    # Freshly attached, no project/design selected. The fake does NOT scope-check
    # (its _inspect returns canned data regardless of selection), so the
    # session's own gap check is the only thing keeping this honest — without it
    # this call would wrongly return fake sections.
    session, _ = attached()
    result = session.inspect()
    assert isinstance(result, SelectionRefused)
    assert result.outcome == "refused_incomplete_selection"
    # Honest by TYPE now, not only by careful wording: a gate that never reached
    # PyAEDT cannot be reported as "PyAEDT could not evaluate".
    assert not isinstance(result, CannotEvaluate)
    blob = f"{result.reason} {result.limitation} {result.template_text}".lower()
    assert "project" in blob and "design" in blob
    assert "pyaedt" not in blob
    assert "cannot evaluate via pyaedt" not in blob
    # A selection gap must not degrade the session.
    assert session._state.health is _Health.ATTACHED


def test_project_without_design_also_refuses_honestly() -> None:
    session, _ = attached()
    session.select("project", "patch_antenna")
    result = session.inspect()
    assert isinstance(result, SelectionRefused)
    assert result.outcome == "refused_incomplete_selection"
    assert "pyaedt" not in result.limitation.lower()
    assert session._state.health is _Health.ATTACHED


def test_detached_session_refuses_with_no_usable_session() -> None:
    session, _ = make_session()  # DETACHED, never attached
    result = session.inspect()
    assert isinstance(result, SelectionRefused)
    assert result.outcome == "refused_no_session"
    assert result.reason == "no usable session"


# --- adapter faults: CannotEvaluate + the same transition list_options makes --


@pytest.mark.parametrize(
    "fault, health, cause",
    [
        (
            AdapterTimeout(operation="inspect", limit_seconds=1.0),
            _Health.SUSPECT,
            None,
        ),
        (AdapterInternalError(detail="boom"), _Health.SUSPECT, None),
        (AdapterDisconnect(detail="dropped"), _Health.LOST, _LostCause.DISCONNECT),
        (AdapterCrash(detail="died"), _Health.LOST, _LostCause.CRASH),
    ],
)
def test_session_fault_midinspect_yields_cannot_evaluate_and_transitions(
    fault, health, cause
) -> None:
    # Deliberately still a CannotEvaluate, NOT a SelectionRefused: the read was
    # ATTEMPTED and broke mid-flight. That is a failure, not a refusal, so the
    # honest-refusal type would be the wrong one here (_session_fault_refusal).
    session, _ = _scoped(Scenario(behavior={"inspect": OpBehavior(fault=fault)}))
    result = session.inspect()
    assert isinstance(result, CannotEvaluate)
    assert not isinstance(result, SelectionRefused)
    assert session._state.health is health
    assert session._state.lost_cause is cause
    # Change 2: the message names inspection, not the wrong "listing".
    assert "inspection" in result.reason
    assert "listing" not in result.reason


# --- genuine adapter cannot_evaluate: faithful mapping, no transition ---------


def test_adapter_cannot_evaluate_maps_through_faithfully() -> None:
    scenario = Scenario(
        behavior={
            "inspect": OpBehavior(
                fault=AdapterCannotEvaluate(
                    reason="unreadable",
                    limitation="sections not exposed by pyaedt",
                )
            )
        }
    )
    session, _ = _scoped(scenario)
    result = session.inspect()
    assert isinstance(result, CannotEvaluate)
    assert result.reason == "unreadable"
    assert result.limitation == "sections not exposed by pyaedt"
    assert (
        result.template_text
        == "Cannot evaluate via PyAEDT: sections not exposed by pyaedt"
    )
    # A genuine cannot_evaluate is PyAEDT answering, not a session fault.
    assert session._state.health is _Health.ATTACHED
