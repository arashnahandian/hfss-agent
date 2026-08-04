"""The absence arms: a never-solved design becomes representable (ADR-28).

Before this amendment there was no honest snapshot for a design that had never
been solved. ``ConvergenceStatus`` has exactly two members, ``converged`` and
``stopped``, and neither is true of a solve that never started — so the only
constructible ``DesignSnapshot`` for an unsolved design asserted
``convergence_status="stopped"`` for a run that never happened. That is a
fabricated value in a required field, which is the one thing this package's
schemas exist to make impossible.

This suite pins the three things the amendment claims:

  1. the never-solved snapshot now constructs, AND does so without asserting a
     convergence status at all — the honesty half, which is the half a
     construct-only test would miss;
  2. the two absence vocabularies are SEPARATE, so ``native_validation`` cannot
     carry a reason that means "never solved";
  3. every reason member has a real adapter refusal behind it, checked by set
     equality so a member added without one cannot reach main.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import get_args

import pytest
from pydantic import ValidationError

from hfss_agent.contract import (
    CONTRACT_VERSION,
    DesignSnapshot,
    Environment,
    Inspection,
    InspectionSection,
    NativeValidation,
    NativeValidationUnavailable,
    NativeValidationUnavailableReason,
    Selection,
    SolveDataUnavailable,
    SolveDataUnavailableReason,
    Variation,
)

# --- fixtures ----------------------------------------------------------------

_SECTION_NAMES = (
    "variables",
    "objects",
    "materials",
    "boundaries",
    "excitations_ports",
    "setups",
    "sweeps",
    "available_results",
)


def _inspection() -> Inspection:
    """All eight sections readable. ``inspection`` has no absence arm (ADR-28),
    so it is always a real ``Inspection`` here."""
    section = InspectionSection(data=[], read_status="ok")
    return Inspection(**{name: section for name in _SECTION_NAMES})


def _environment() -> Environment:
    return Environment(
        aedt_version="2026.1",
        pyaedt_version="1.2.0",
        python_version="3.12.10",
        wrapper_version="0.0.0",
    )


def _selection(variation: Variation) -> Selection:
    return Selection(
        process_id=12345,
        project="patch_antenna",
        design="HFSSDesign1",
        solution_type="DrivenModal",
        setup="Setup1",
        sweep="Sweep1",
        variation=variation,
    )


def _never_solved(variation: Variation) -> DesignSnapshot:
    """The snapshot of a design that has never been solved.

    Both solve fields take the absence arm, each naming why. The reasons differ
    on purpose and reflect what the adapter can actually observe today: the
    solved-data read reports ``no_solution``, while the solve-state read refuses
    at its convergence step and can only say ``not_exposed_by_pyaedt`` — see the
    asymmetry note on ``SolveDataUnavailableReason``.
    """
    return DesignSnapshot(
        contract_version=CONTRACT_VERSION,
        created_at=datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc),
        snapshot_id="snap-unsolved-001",
        environment=_environment(),
        selection=_selection(variation),
        inspection=_inspection(),
        native_validation=NativeValidation(raw_output=[]),
        solve_state=SolveDataUnavailable(
            reason="not_exposed_by_pyaedt",
            limitation=(
                "per-pass convergence history and convergence status are not "
                "exposed by PyAEDT for this setup type"
            ),
        ),
        solved_data=SolveDataUnavailable(
            reason="no_solution",
            limitation=(
                "no solved S-parameter data is available for Setup1 : Sweep1"
            ),
        ),
    )


# --- 1. the never-solved snapshot is constructible AND honest -----------------


def test_a_never_solved_design_constructs_without_asserting_a_convergence_status(
    variation: Variation,
) -> None:
    """The direct answer to the probe that opened this step.

    That probe could build a snapshot for an unsolved design ONLY by passing
    ``convergence_status="stopped"``. Constructibility alone was therefore never
    the property worth testing — the lie was constructible too. What this asserts
    is that the snapshot now exists AND carries no convergence claim at all,
    because there is no ``SolveState`` in it to carry one.
    """
    snapshot = _never_solved(variation)

    assert isinstance(snapshot.solve_state, SolveDataUnavailable)
    assert isinstance(snapshot.solved_data, SolveDataUnavailable)
    # The honesty half: nothing anywhere in the emitted artifact claims the
    # design converged or stopped. Asserted over the serialized tree rather than
    # over the field, so a convergence status reintroduced ANYWHERE below
    # solve_state would fail this too.
    dumped = snapshot.model_dump(mode="json")
    assert "convergence_status" not in str(dumped)
    assert snapshot.solved_data.reason == "no_solution"


def test_the_solved_arm_still_constructs_unchanged(variation: Variation) -> None:
    """The union did not break the data arm — the regression this amendment is
    most likely to cause and least likely to be noticed causing."""
    from hfss_agent.contract import ComplexSample, SolvedData

    snapshot = _never_solved(variation).model_copy(
        update={
            "solved_data": SolvedData(
                frequencies=[2.4e9],
                s_parameters={"S(1,1)": [ComplexSample(real=-0.1, imag=0.02)]},
            )
        }
    )
    assert isinstance(snapshot.solved_data, SolvedData)
    assert snapshot.solved_data.frequencies == [2.4e9]


# --- 2. what must be unconstructible is unconstructible -----------------------


@pytest.mark.parametrize(
    "bad_reason", ["never_solved", "unsolved", "unknown", "", "no_data"]
)
def test_a_reason_outside_the_literal_set_is_refused(bad_reason: str) -> None:
    """A reason nobody derived from a refusal cannot be invented at the call
    site. ``never_solved`` is the tempting one and is deliberately in this list:
    it reads exactly like the state this amendment is for, and no adapter
    refusal produces it."""
    with pytest.raises(ValidationError):
        SolveDataUnavailable(reason=bad_reason, limitation="x")  # type: ignore[arg-type]


def test_a_reason_without_a_limitation_is_refused() -> None:
    """``limitation`` is REQUIRED here where ``InspectionSection``'s is optional.

    That field is optional because its ``read_status="ok"`` case has nothing to
    explain; this type exists only in the absent case, and every refusal behind
    it carries a limitation string. An optional one would advertise a state — a
    reason with no explanation — that no producer can produce.
    """
    with pytest.raises(ValidationError) as caught:
        SolveDataUnavailable(reason="no_solution")  # type: ignore[call-arg]
    assert caught.value.errors()[0]["loc"] == ("limitation",)

    with pytest.raises(ValidationError):
        NativeValidationUnavailable(reason="not_exposed_by_pyaedt")  # type: ignore[call-arg]


def test_neither_absence_type_accepts_an_extra_field() -> None:
    """``extra="forbid"`` holds here as everywhere: an unexpected key is a
    contract violation surfaced loudly, not silently absorbed."""
    with pytest.raises(ValidationError):
        SolveDataUnavailable(
            reason="no_solution", limitation="x", convergence_status="stopped"
        )  # type: ignore[call-arg]


# --- 3. the split, which is the whole point of two types ----------------------


@pytest.mark.parametrize(
    "solve_only_reason",
    ["no_solution", "not_found_in_design", "unrecognised_by_wrapper"],
)
def test_native_validation_refuses_every_solve_data_reason(
    solve_only_reason: str,
) -> None:
    """THE TEST THE SPLIT EXISTS FOR.

    A single shared reason vocabulary would let ``native_validation`` say
    "no_solution" — nonsense for a design-level validation run that needs no
    solution — plus "not_found_in_design" (it reads no setup) and
    "unrecognised_by_wrapper" (it normalises no units). Three nonsense states a
    shared type would permit, asserted here one at a time rather than trusting
    the two vocabularies to stay apart.

    Parametrised over exactly the members of ``SolveDataUnavailableReason`` that
    are NOT in ``NativeValidationUnavailableReason``, so adding a member to
    either set without revisiting this test leaves a gap the set-equality test
    below then catches.
    """
    with pytest.raises(ValidationError):
        NativeValidationUnavailable(reason=solve_only_reason, limitation="x")  # type: ignore[arg-type]


def test_the_one_shared_spelling_is_a_coincidence_not_a_kinship() -> None:
    """``not_exposed_by_pyaedt`` is spelled the same in both sets and means the
    same thing in English, and nothing may depend on that staying true.

    Asserted as an explicit statement of the CURRENT overlap, so that a future
    member added to one set makes this test's arithmetic visibly wrong rather
    than silently stale — the same independence ADR-23 fixed between the three
    provenance types.
    """
    solve = set(get_args(SolveDataUnavailableReason))
    native = set(get_args(NativeValidationUnavailableReason))
    assert solve & native == {"not_exposed_by_pyaedt"}
    assert native - solve == set()
    assert solve - native == {
        "no_solution",
        "not_found_in_design",
        "unrecognised_by_wrapper",
    }


# --- 4. absence is not an empty success ---------------------------------------


def test_an_absent_native_validation_is_not_an_empty_one(
    variation: Variation,
) -> None:
    """The misread ADR-23 most guards against, now structural.

    ``raw_output=[]`` is a validator that RAN and reported nothing — a completed
    run, and a success. "The validator could not be run" is a different fact, and
    before this arm the snapshot had nowhere to put it except that same empty
    list. Both states are built here and shown to be distinguishable by type,
    not by reading prose.
    """
    ran_and_said_nothing = _never_solved(variation)
    could_not_run = ran_and_said_nothing.model_copy(
        update={
            "native_validation": NativeValidationUnavailable(
                reason="not_exposed_by_pyaedt",
                limitation=(
                    "HFSS's own design validator could not be run, or its "
                    "messages could not be read back, through PyAEDT for this "
                    "design."
                ),
            )
        }
    )

    assert isinstance(ran_and_said_nothing.native_validation, NativeValidation)
    assert ran_and_said_nothing.native_validation.raw_output == []
    assert isinstance(
        could_not_run.native_validation, NativeValidationUnavailable
    )
    assert ran_and_said_nothing != could_not_run


# --- 5. both arms survive the engine seam -------------------------------------


def test_every_arm_round_trips_through_json_as_its_own_type(
    variation: Variation,
) -> None:
    """The snapshot crosses ``evaluate()`` as JSON, so an arm that collapsed into
    its sibling on the way would be a defect invisible in-process.

    Both unions are resolved by their disjoint field sets under
    ``extra="forbid"``, with no discriminator field — this is what proves that
    resolution survives serialization in both directions.
    """
    from hfss_agent.contract import ComplexSample, SolvedData

    absent = _never_solved(variation)
    present = absent.model_copy(
        update={
            "native_validation": NativeValidation(raw_output=["0 errors."]),
            "solved_data": SolvedData(
                frequencies=[2.4e9],
                s_parameters={"S(1,1)": [ComplexSample(real=-0.1, imag=0.0)]},
            ),
        }
    )

    for snapshot, solved_type, native_type in (
        (absent, SolveDataUnavailable, NativeValidation),
        (present, SolvedData, NativeValidation),
    ):
        reloaded = DesignSnapshot.model_validate_json(snapshot.model_dump_json())
        assert isinstance(reloaded.solved_data, solved_type)
        assert isinstance(reloaded.native_validation, native_type)
        assert reloaded == snapshot


# --- 6. anti-rot: every member names a producer -------------------------------

# The refusal behind each reason, by the adapter's own ``reason`` string. This
# table is the mapping ADR-28 derived, written where the assertion can reach it.
# It is NOT a restatement of the Literal: the test below compares the two by SET
# EQUALITY in both directions, so a member added to either side without the
# other fails — which is the only construction under which "the table is pinned"
# means anything.
_SOLVE_DATA_REASON_PRODUCERS: dict[str, tuple[str, ...]] = {
    "no_solution": ("no solved data",),
    "not_exposed_by_pyaedt": (
        "convergence history unavailable",
        "solve timestamp unavailable",
    ),
    "not_found_in_design": ("setup not found",),
    "unrecognised_by_wrapper": ("unknown frequency unit",),
}

_NATIVE_REASON_PRODUCERS: dict[str, tuple[str, ...]] = {
    "not_exposed_by_pyaedt": ("native validation unavailable",),
}


@pytest.mark.parametrize(
    ("literal", "table"),
    [
        (SolveDataUnavailableReason, _SOLVE_DATA_REASON_PRODUCERS),
        (NativeValidationUnavailableReason, _NATIVE_REASON_PRODUCERS),
    ],
)
def test_every_reason_member_names_at_least_one_adapter_refusal(
    literal: object, table: dict[str, tuple[str, ...]]
) -> None:
    """Admitting a member because it seems like a state that ought to exist is
    the allow-list rot ADR-27 decision 14 named.

    SET EQUALITY, NOT CONTAINMENT, and the direction matters both ways: a
    ``<=`` check would pass for a new Literal member with no table row (the rot
    this guards against), and a ``>=`` check would pass for a table row whose
    member was deleted. Only equality fails on both.

    This can assert the mapping AS DOCUMENTED, not derive it — ``contract`` may
    not import ``adapter`` (ADR-3), and importing it here to read the real
    strings would put an adapter import in the contract suite. What it buys is
    that adding a member forces an edit that names its producer.
    """
    assert set(get_args(literal)) == set(table)
    for member, refusals in table.items():
        assert refusals, f"{member} names no adapter refusal"
        assert all(refusal.strip() for refusal in refusals)
