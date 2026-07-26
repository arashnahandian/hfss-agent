"""validate_native (W-2 session read) — plumbing for the native validation tool.

Drives the licence-free ``FakeAdapter``; faults are injected via ``OpBehavior``
scenario scripting, never real sleeps (the session suite's determinism
convention). This layer returns the RAW ``NativeValidation`` on success — no
``NativeValidationBlock``, provenance, or ``template_text``; that pairing is the
W-6 module's job, exactly as ``InspectionResult`` is W-5's.

Its two non-success arms are kept apart on the refusal-vs-failure line, like
``inspect``: a session gate that declined BEFORE PyAEDT was reached (no usable
session, an incomplete selection) is a ``SelectionRefused``; an operation that
WAS attempted and did not complete (an adapter fault, or a genuine adapter
cannot_evaluate) is a ``CannotEvaluate``.

The distinction this file guards hardest is ADR-23's: "the validator RAN and
reported nothing" is a SUCCESS carrying an empty ``raw_output``, while "the
validator could not be run" is a ``CannotEvaluate``. They are different facts
about different things, and a caller that cannot tell them apart cannot report
either one honestly.
"""

from __future__ import annotations

import pytest
from session_helpers import attached, force_suspect, list_timeout_then, make_session

from hfss_agent.adapter.fake import OpBehavior, Scenario
from hfss_agent.adapter.fake.scenario import _empty_native_validation
from hfss_agent.adapter.results import (
    AdapterCannotEvaluate,
    AdapterCrash,
    AdapterDisconnect,
    AdapterInternalError,
    AdapterTimeout,
)
from hfss_agent.contract import NativeValidation
from hfss_agent.contract.tool_io import (
    CannotEvaluate,
    NativeValidationBlock,
    SelectionRefused,
)
from hfss_agent.session import Session
from hfss_agent.session.status import _Health, _LostCause

# The default fake scenario's single ValidateDesign message.
_DEFAULT_MESSAGE = "Design validation completed. 0 errors, 0 warnings."


def _scoped(scenario: Scenario | None = None) -> tuple[Session, object]:
    """An attached session with project+design selected — validate_native's whole
    prerequisite (ValidateDesign is design-level) — over a FakeAdapter driven by
    ``scenario``, which scripts ops other than attach/select so the setup drive
    succeeds."""
    session, fake = attached(scenario)
    session.select("project", "patch_antenna")
    session.select("design", "HFSSDesign1")
    assert session._state.health is _Health.ATTACHED
    return session, fake


# --- success arm: the raw NativeValidation ------------------------------------


def test_clean_validate_native_returns_the_raw_native_validation() -> None:
    session, _ = _scoped()
    result = session.validate_native()
    assert isinstance(result, NativeValidation)
    # RAW, not assembled: a block carries provenance this layer cannot honestly
    # fill (it cannot reach the attach-time AEDT version), so returning one here
    # would mean inventing it. W-6 pairs them across the broker boundary.
    assert not isinstance(result, NativeValidationBlock)
    assert result.raw_output == [_DEFAULT_MESSAGE]
    assert result.source == "hfss_native"
    assert session._state.health is _Health.ATTACHED


def test_empty_raw_output_is_a_success_not_a_failure() -> None:
    # ADR-23's most misreadable shape, pinned at the session layer too: the
    # validator ran and had nothing to say. Not a refusal, not a cannot_evaluate,
    # and emphatically not "the validator could not be run".
    scenario = Scenario()
    scenario.native_validation = _empty_native_validation()
    session, _ = _scoped(scenario)
    result = session.validate_native()
    assert isinstance(result, NativeValidation)
    assert result.raw_output == []
    assert not isinstance(result, (CannotEvaluate, SelectionRefused))
    assert result.source == "hfss_native"  # attribution survives an empty run
    assert session._state.health is _Health.ATTACHED


# --- session gates: honest refusals, before PyAEDT is reached -----------------


def test_nothing_selected_is_an_honest_selection_gap_refusal() -> None:
    # Freshly attached, no project/design selected. The fake does NOT scope-check
    # (its _validate_native returns canned data regardless of selection), so the
    # session's own gap check is the only thing keeping this honest — without it
    # this call would wrongly return a canned validation for no design at all.
    session, _ = attached()
    result = session.validate_native()
    assert isinstance(result, SelectionRefused)
    assert result.outcome == "refused_incomplete_selection"
    # Honest by TYPE, not only by careful wording: a gate that never reached
    # PyAEDT cannot be reported as "PyAEDT could not evaluate".
    assert not isinstance(result, CannotEvaluate)
    blob = f"{result.reason} {result.limitation} {result.template_text}".lower()
    assert "project" in blob and "design" in blob
    assert "pyaedt" not in blob
    assert "cannot evaluate" not in blob
    # A selection gap must not degrade the session.
    assert session._state.health is _Health.ATTACHED


def test_project_without_design_also_refuses_honestly() -> None:
    session, _ = attached()
    session.select("project", "patch_antenna")
    result = session.validate_native()
    assert isinstance(result, SelectionRefused)
    assert result.outcome == "refused_incomplete_selection"
    assert "pyaedt" not in result.limitation.lower()
    assert session._state.health is _Health.ATTACHED


def test_detached_session_refuses_with_no_usable_session() -> None:
    session, _ = make_session()  # DETACHED, never attached
    result = session.validate_native()
    assert isinstance(result, SelectionRefused)
    assert result.outcome == "refused_no_session"
    assert result.reason == "no usable session"


# --- the shared selection-gap gate: each caller names its OWN operation --------

# The exact strings ``_require_project_and_design`` produces for its two callers,
# written out in full and side by side. This is the ONLY place either one is
# pinned byte-for-byte, and they are pinned TOGETHER on purpose: the gate is one
# method with one parameterized clause, so an edit aimed at one caller can only
# reach the other through this file, where both are visible in the same diff.
#
# Why this test exists at all: before validate_native there was one caller, and
# its wording was hardcoded — so a second caller would have inherited a remedy
# sentence describing INSPECTION, in the one message type whose entire purpose is
# naming the correct remedy. The parameter fixed that; this test is what keeps it
# fixed.
_INSPECT_GAP_LIMITATION = (
    "a project and a design must both be selected before the design can be "
    "inspected; select a project, then a design, then retry."
)
_VALIDATE_GAP_LIMITATION = (
    "a project and a design must both be selected before HFSS's own validation "
    "can be run on the design; select a project, then a design, then retry."
)


def test_the_two_gate_messages_name_their_own_operation() -> None:
    session, _ = attached()  # attached, nothing selected: both gates fire

    inspected = session.inspect()
    validated = session.validate_native()
    assert isinstance(inspected, SelectionRefused)
    assert isinstance(validated, SelectionRefused)

    assert inspected.limitation == _INSPECT_GAP_LIMITATION
    assert validated.limitation == _VALIDATE_GAP_LIMITATION
    assert inspected.template_text == f"Cannot proceed: {_INSPECT_GAP_LIMITATION}"
    assert validated.template_text == f"Cannot proceed: {_VALIDATE_GAP_LIMITATION}"

    # Neither may describe the other's operation.
    assert "inspect" not in validated.limitation.lower()
    assert "validation" not in inspected.limitation.lower()
    # The tag and reason are deliberately IDENTICAL: they name the remedy, and
    # the remedy (select a project, then a design) really is the same one.
    assert inspected.outcome == validated.outcome == "refused_incomplete_selection"
    assert inspected.reason == validated.reason == "incomplete selection"


# --- adapter faults: CannotEvaluate + the transitions inspect makes ------------


@pytest.mark.parametrize(
    "fault, health, cause",
    [
        (
            AdapterTimeout(operation="validate_native", limit_seconds=1.0),
            _Health.SUSPECT,
            None,
        ),
        (AdapterInternalError(detail="boom"), _Health.SUSPECT, None),
        (AdapterDisconnect(detail="dropped"), _Health.LOST, _LostCause.DISCONNECT),
        (AdapterCrash(detail="died"), _Health.LOST, _LostCause.CRASH),
    ],
)
def test_session_fault_midvalidation_yields_cannot_evaluate_and_transitions(
    fault, health, cause
) -> None:
    # Deliberately a CannotEvaluate, NOT a SelectionRefused: the call was
    # ATTEMPTED and broke mid-flight. That is a failure, not a refusal, so the
    # honest-refusal type would be the wrong one here (_session_fault_refusal).
    session, _ = _scoped(
        Scenario(behavior={"validate_native": OpBehavior(fault=fault)})
    )
    result = session.validate_native()
    assert isinstance(result, CannotEvaluate)
    assert not isinstance(result, SelectionRefused)
    assert session._state.health is health
    assert session._state.lost_cause is cause
    # The message names native validation — not the wrong "listing" or
    # "inspection" it would have inherited from a hardcoded label.
    assert "native validation" in result.reason
    assert "listing" not in result.reason
    assert "inspection" not in result.reason


# --- genuine adapter cannot_evaluate: faithful mapping, no transition ---------


def test_adapter_cannot_evaluate_maps_through_faithfully() -> None:
    # The sixth fixture-ledger case as the SESSION sees it. Note what separates
    # this from test_empty_raw_output_is_a_success_not_a_failure above: there the
    # validator ran and said nothing; here it could not be run at all. Same tool,
    # different facts, different types — which is the point.
    scenario = Scenario(
        behavior={
            "validate_native": OpBehavior(
                fault=AdapterCannotEvaluate(
                    reason="native validation unavailable",
                    limitation="ValidateDesign is not exposed by this pyaedt build",
                )
            )
        }
    )
    session, _ = _scoped(scenario)
    result = session.validate_native()
    assert isinstance(result, CannotEvaluate)
    assert result.reason == "native validation unavailable"
    assert result.limitation == "ValidateDesign is not exposed by this pyaedt build"
    assert result.template_text == (
        "Cannot evaluate via PyAEDT: ValidateDesign is not exposed by this pyaedt build"
    )
    # A genuine cannot_evaluate is PyAEDT answering, not a session fault.
    assert session._state.health is _Health.ATTACHED


# --- the suspect guard, behaviourally ----------------------------------------


def test_a_suspect_session_reverifies_before_validating() -> None:
    """The reflection test in test_guard.py proves the marker is PRESENT; this
    proves it is WIRED. A suspect session re-verifies on the existing adapter
    (never re-attaches), and only then does the validation run."""
    session, _ = _scoped(list_timeout_then())
    force_suspect(session)  # scripted first-list_options timeout -> SUSPECT

    result = session.validate_native()

    assert isinstance(result, NativeValidation)
    assert result.raw_output == [_DEFAULT_MESSAGE]
    # Verify re-drove the saved chain, found it intact, and cleared suspect.
    assert session._state.health is _Health.ATTACHED
    assert session._state.chain.design == "HFSSDesign1"
