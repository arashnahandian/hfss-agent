"""The never-solved design assembles, and every field in it is honest.

This is the case ADR-28 was written for, and ADR-28 calls it the ORDINARY one:
"a design that was never solved is the ordinary case". Before the absence arms
existed, the only constructible ``DesignSnapshot`` for such a design asserted
``convergence_status="stopped"`` for a solve that never started — a fabricated
value in a required field. ``tests/schemas/test_snapshot_absence_arms.py`` pinned
that the SCHEMA now permits the honest shape; this file pins that W-8 actually
PRODUCES it, from the exact object set a caller would hold.

WHAT MAKES THIS DIFFERENT FROM THE SCHEMA SUITE: there, the snapshot is
hand-built. Here it goes through ``assemble_snapshot``, so the narrowings run,
``created_at`` and ``snapshot_id`` are minted, and the artifact is the one a
caller would actually get.

EVERY OBJECT BELOW IS CONSTRUCTIBLE WITHOUT FABRICATING A VALUE, which is the
property the never-solved case exists to demonstrate:

  * ``selection`` — a never-SOLVED design is fully SELECTABLE, so all seven
    stages are real choices the user made;
  * ``inspection`` — reads design STRUCTURE and is independent of solve state, so
    all eight sections are genuinely readable;
  * ``native_validation`` — ValidateDesign is DESIGN-LEVEL and needs no solution
    (``NativeValidationProvenance`` records that it reads no setup and needs no
    solve), so this is a real run with real messages, never the absence arm;
  * ``environment`` — read from the live session at attach;
  * the two solve fields — the absence arm, each naming the adapter's own reason.
"""

from __future__ import annotations

import pytest
from snapshot_helpers import chain, environment, inspection_result, native_block

from hfss_agent.contract import (
    DesignSnapshot,
    Inspection,
    NativeValidation,
    NativeValidationUnavailable,
    Selection,
    SolveDataUnavailable,
    SolvedData,
    SolveState,
)
from hfss_agent.snapshot import assemble_snapshot

# THE TWO REASONS ARE DIFFERENT, AND THE ASYMMETRY IS A LIVE ADAPTER MISREPORT
# RATHER THAN A W-8 CHOICE. Both describe the same underlying fact — this design
# was never solved — but the adapter can only observe one of them honestly:
#
#   * ``read_solved_data`` reaches its own refusal and reports "no solved data",
#     which maps to ``no_solution``. That is the true reason.
#   * ``read_solve_state`` refuses EARLIER, at its convergence-history step, and
#     never consults ``setup.is_solved`` at all — so all it can say is
#     "convergence history unavailable", which maps to ``not_exposed_by_pyaedt``.
#     That is a true statement about what PyAEDT exposed, and a WEAKER one than
#     the field deserves: the design has no solution, and this reason does not
#     say so.
#
# ``contract/common.py`` records the same asymmetry as accepted rather than
# papered over, and names the fix: a small reorder inside the adapter so
# ``is_solved`` is consulted before the convergence read. That reorder is QUEUED
# TO ITS OWN ADAPTER-HYGIENE STEP and is deliberately not done here.
#
# WHEN IT LANDS, THIS FILE MUST BE EDITED BY HAND — ``SOLVE_STATE_REASON``
# becomes ``"no_solution"`` and the two constants become equal. NOTHING HERE WILL
# FAIL TO TELL YOU THAT, and the correction is Part 7's: this comment previously
# claimed the opposite ("a test asserting the old misreport fails and forces
# someone to notice"), which was wrong. See the honesty note below for what is
# and is not pinned. The reorder step owns updating this file; no tripwire will
# do it for them. It needs no schema event either way, because adding a producer
# for an existing Literal member is not a contract change.
SOLVE_STATE_REASON = "not_exposed_by_pyaedt"
SOLVED_DATA_REASON = "no_solution"

# WHAT THESE CONSTANTS ARE, AND WHAT THEY ARE NOT (corrected in Part 7). They are
# TRANSCRIPTIONS of the adapter's limitation strings, written here so a reader
# sees realistic prose instead of ``"x"``. They are NOT a pin on the adapter, and
# the comment that stood here until Part 7 said they were ("quoted from
# real_adapter.py ... so a reworded refusal surfaces here as a diff"). Nothing in
# this file imports, reads, or executes the adapter; every assertion below
# compares an assembled snapshot to the same constant used to build its input, so
# a reworded refusal changes nothing here and no diff appears.
#
# THERE IS NO CHEAP WAY TO MAKE THEM A REAL PIN, which is why the fix is this
# note rather than a better assertion. ``SOLVE_STATE_LIMITATION`` could be
# imported if it were a module constant, but it is an inline literal; and
# ``SOLVED_DATA_LIMITATION`` is not a literal at all — ``real_adapter`` builds it
# with an f-string over ``f"{setup} : {sweep}"``, so the full string exists only
# at call time and a grep for it finds nothing. Pinning it genuinely needs either
# an adapter refactor (hoisting the limitations to constants — out of scope for a
# snapshot step, and a change to the module every other suite depends on) or a
# source-text scrape of ``real_adapter.py``, which pins source text rather than
# behaviour and is the brittleness this suite avoids elsewhere.
#
# WHAT IS GENUINELY PINNED, so the gap is not overstated: the adapter's ``reason``
# STRINGS are held to the contract's ``SolveDataUnavailableReason`` members by the
# documented table in ``tests/schemas/test_snapshot_absence_arms.py``, under set
# equality in both directions. That catches a member added or deleted on either
# side. It will NOT catch the queued reorder either, because the reorder changes
# which field gets which existing member and adds no member.
SOLVE_STATE_LIMITATION = (
    "per-pass convergence history and convergence status are not exposed by "
    "PyAEDT for this setup type"
)
SOLVED_DATA_LIMITATION = (
    "no solved S-parameter data is available for Setup1 : Sweep1"
)


def never_solved() -> DesignSnapshot:
    """The snapshot of a design that has never been solved."""
    return assemble_snapshot(
        inspection=inspection_result(),
        # A REAL validation run with a real message. A design-level validator
        # needs no solution, so the absence arm here would be wrong.
        native_validation=native_block(
            ["Design validation completed. 0 errors, 0 warnings."]
        ),
        solve_state=SolveDataUnavailable(
            reason=SOLVE_STATE_REASON, limitation=SOLVE_STATE_LIMITATION
        ),
        solved_data=SolveDataUnavailable(
            reason=SOLVED_DATA_REASON, limitation=SOLVED_DATA_LIMITATION
        ),
        selection=chain(),
        environment=environment(),
    )


# --- 1. it assembles at all ---------------------------------------------------


def test_a_never_solved_design_assembles() -> None:
    """The direct answer to the probe that opened Step 2.5a.

    That probe could build a snapshot for an unsolved design ONLY by passing
    ``convergence_status="stopped"``. This one is built by the real entry point
    and passes no convergence claim at all.
    """
    snapshot = never_solved()

    assert isinstance(snapshot, DesignSnapshot)
    assert isinstance(snapshot.selection, Selection)
    assert isinstance(snapshot.inspection, Inspection)
    assert isinstance(snapshot.solve_state, SolveDataUnavailable)
    assert isinstance(snapshot.solved_data, SolveDataUnavailable)


def test_every_input_is_constructible_without_fabricating_a_value() -> None:
    """Asserted field by field, because "it constructs" is not the property —
    the lie constructed too. What matters is that each value is one somebody
    could honestly supply for a design that was never solved.
    """
    snapshot = never_solved()

    # A never-SOLVED design is fully SELECTABLE: all seven stages are real.
    for stage in ("project", "design", "solution_type", "setup", "sweep"):
        assert getattr(snapshot.selection, stage)
    assert snapshot.selection.process_id > 0
    assert snapshot.selection.variation.variation_hash

    # Structure reads fine without a solve: all eight sections, all readable.
    for name in Inspection.model_fields:
        section = getattr(snapshot.inspection, name)
        assert section.read_status == "ok"

    # Versions come from the attached session.
    assert snapshot.environment.aedt_version
    assert snapshot.environment.pyaedt_version

    # And the two absent fields each name a reason the adapter actually emits.
    assert snapshot.solve_state.limitation
    assert snapshot.solved_data.limitation


# --- 2. the two reasons differ, and both are the adapter's -------------------


def test_the_two_solve_fields_carry_different_reasons() -> None:
    """W-8 PROPAGATES TWO DIFFERENT REASONS WITHOUT FLATTENING THEM — that, and
    only that, is what this asserts.

    It is not a pin on the adapter. The inputs are built from the two module
    constants and the assertions compare the snapshot back to them, so what is
    actually shown is that assembly carries two distinct ``SolveDataUnavailable``
    values through to two distinct fields rather than reusing one. That is a real
    W-8 property — a pass-through that re-wrapped either field would break it —
    and it is a much smaller claim than this docstring made before Part 7.

    See the comment on ``SOLVE_STATE_REASON`` for why the two reasons differ in
    the live adapter, and for why nothing here fails when that stops being true.
    """
    snapshot = never_solved()

    assert snapshot.solve_state.reason == SOLVE_STATE_REASON
    assert snapshot.solved_data.reason == SOLVED_DATA_REASON
    assert snapshot.solve_state.reason != snapshot.solved_data.reason


def test_both_reasons_are_real_adapter_refusals() -> None:
    """Checked against the contract ``Literal`` — which reaches the producer
    table only INDIRECTLY, and the distinction is worth one line.

    This asserts membership in ``SolveDataUnavailableReason``. What ties that
    Literal to real adapter refusals is a separate assertion one suite over:
    ``tests/schemas/test_snapshot_absence_arms.py`` holds the Literal and its
    documented producer table to SET EQUALITY in both directions. So a reason
    nobody derived from an adapter refusal cannot be smuggled in here — but the
    thing preventing it lives there, not in this assertion.
    """
    from hfss_agent.contract import SolveDataUnavailableReason

    valid = set(SolveDataUnavailableReason.__args__)
    assert SOLVE_STATE_REASON in valid
    assert SOLVED_DATA_REASON in valid


def test_the_limitations_are_the_adapters_own_wording() -> None:
    """W-8 WRITES NO LIMITATION TEXT OF ITS OWN — it has no way to know why a
    read refused, so whatever prose it was handed must arrive unchanged.

    The prose used here is the adapter's, transcribed; but this test pins the
    PASS-THROUGH, not the wording. An assembler that rewrote, truncated or
    prefixed a limitation fails here. An adapter that rewords one does not — see
    the comment on ``SOLVE_STATE_LIMITATION`` for why that pin is not cheaply
    available and what does cover the reason strings instead.
    """
    snapshot = never_solved()
    assert snapshot.solve_state.limitation == SOLVE_STATE_LIMITATION
    assert snapshot.solved_data.limitation == SOLVED_DATA_LIMITATION


# --- 3. nothing claims a convergence status ----------------------------------


def test_no_convergence_status_appears_anywhere_in_the_dumped_tree() -> None:
    """THE HONESTY HALF, and the half a construct-only test would miss.

    Asserted over the whole serialized tree rather than over the field, so a
    convergence claim reintroduced ANYWHERE below ``solve_state`` fails this too.
    Both the key and both of its possible values are checked: a producer that
    started emitting a bare ``"converged"`` string under some other key would be
    just as wrong.
    """
    snapshot = never_solved()
    for mode in ("python", "json"):
        rendered = str(snapshot.model_dump(mode=mode))  # type: ignore[arg-type]
        assert "convergence_status" not in rendered
        assert "converged" not in rendered
        assert "stopped" not in rendered


def _solved(convergence_status: str) -> DesignSnapshot:
    """A snapshot whose ``solve_state`` IS a ``SolveState``, carrying the given
    status — the shape the never-solved assertion above must be able to catch."""
    from datetime import datetime, timezone

    from snapshot_helpers import variation

    from hfss_agent.contract import FreshnessEvidence, SolutionExists

    return assemble_snapshot(
        inspection=inspection_result(),
        native_validation=native_block([]),
        solve_state=SolveState(
            solution_exists=[
                SolutionExists(
                    setup="Setup1",
                    sweep="Sweep1",
                    variation=variation(),
                    exists=True,
                )
            ],
            adaptive_pass_history=[],
            delta_s_progression=[0.004],
            convergence_status=convergence_status,  # type: ignore[arg-type]
            solve_timestamps={
                "Setup1:Sweep1": datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)
            },
            solver_messages=[],
            freshness_evidence=FreshnessEvidence(
                available_signals={}, determinable=False
            ),
        ),
        solved_data=SolvedData(frequencies=[2.4e9], s_parameters={}),
        selection=chain(),
        environment=environment(),
    )


@pytest.mark.parametrize("status", ["converged", "stopped"])
@pytest.mark.parametrize("mode", ["python", "json"])
def test_the_solved_arm_would_carry_one_which_is_why_the_check_is_meaningful(
    status: str, mode: str
) -> None:
    """A control on the assertion above: it must be capable of failing.

    MATCHED TO THE ASSERTION IT CONTROLS, which it was not until Part 8. That
    assertion loops BOTH dump modes and checks THREE strings —
    ``convergence_status``, ``converged`` and ``stopped``; this control checked
    one mode and two strings, so the ``"stopped"`` half had no proof it could
    fail at all. ``ConvergenceStatus`` is a two-member Literal, so both members
    get a snapshot and both dump modes get a pass.

    Without this, "convergence_status not in the tree" could be passing because
    the string never appears in any snapshot.
    """
    rendered = str(_solved(status).model_dump(mode=mode))  # type: ignore[arg-type]
    assert "convergence_status" in rendered
    assert status in rendered


# --- 4. native validation is a real run, not the absence arm -----------------


def test_native_validation_is_a_real_run_not_the_absence_arm() -> None:
    """A DESIGN-LEVEL VALIDATOR NEEDS NO SOLUTION, so a never-solved design gets
    a real ``NativeValidation`` with real messages.

    Using the absence arm here would be the misread ADR-23 most guards against,
    pointed the other way: it would say "the validator could not be run" about a
    validator that ran perfectly well and simply had nothing to do with the
    absent solve.
    """
    snapshot = never_solved()

    assert isinstance(snapshot.native_validation, NativeValidation)
    assert not isinstance(snapshot.native_validation, NativeValidationUnavailable)
    assert snapshot.native_validation.raw_output == [
        "Design validation completed. 0 errors, 0 warnings."
    ]
    assert snapshot.native_validation.source == "hfss_native"


def test_an_empty_message_list_is_still_a_real_run() -> None:
    """``raw_output=[]`` is a validator that RAN and reported nothing — a
    completed run, and a success. It is not the absence arm, and a never-solved
    design is the case most likely to produce it."""
    snapshot = assemble_snapshot(
        inspection=inspection_result(),
        native_validation=native_block([]),
        solve_state=SolveDataUnavailable(
            reason=SOLVE_STATE_REASON, limitation=SOLVE_STATE_LIMITATION
        ),
        solved_data=SolveDataUnavailable(
            reason=SOLVED_DATA_REASON, limitation=SOLVED_DATA_LIMITATION
        ),
        selection=chain(),
        environment=environment(),
    )
    assert isinstance(snapshot.native_validation, NativeValidation)
    assert snapshot.native_validation.raw_output == []


# --- 5. the artifact survives the seam ---------------------------------------


def test_the_never_solved_snapshot_round_trips_as_its_own_types() -> None:
    """Both absence arms are resolved by their disjoint field sets under
    ``extra="forbid"`` with no discriminator, so an arm that collapsed into its
    sibling on the way through JSON would be invisible in-process."""
    snapshot = never_solved()
    reloaded = DesignSnapshot.model_validate_json(snapshot.model_dump_json())

    assert reloaded == snapshot
    assert isinstance(reloaded.solve_state, SolveDataUnavailable)
    assert isinstance(reloaded.solved_data, SolveDataUnavailable)
    assert isinstance(reloaded.native_validation, NativeValidation)
    assert reloaded.solve_state.reason == SOLVE_STATE_REASON
    assert reloaded.solved_data.reason == SOLVED_DATA_REASON


@pytest.mark.parametrize("field", ["solve_state", "solved_data"])
def test_neither_absent_field_was_rewrapped(field: str) -> None:
    """Passed through as the SAME object. A ``SolveDataUnavailable`` is already
    the honest artifact for "there is none", and wrapper text over a reason the
    adapter worded correctly would add a second voice to a single fact."""
    absent = SolveDataUnavailable(reason="no_solution", limitation="x")
    snapshot = assemble_snapshot(
        **{  # type: ignore[arg-type]
            "inspection": inspection_result(),
            "native_validation": native_block([]),
            "solve_state": absent,
            "solved_data": absent,
            "selection": chain(),
            "environment": environment(),
        }
    )
    assert getattr(snapshot, field) is absent
