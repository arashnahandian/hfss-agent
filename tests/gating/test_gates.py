"""W-9 gate semantics: every reachable outcome of all four gates, plus the
aggregator that runs them.

THE FOUR GATES DO NOT SHARE ONE SIGNATURE, and ``_run`` below is where the suite
pays for that. ``target_coverage`` takes a target frequency; the other three take
the snapshot alone, because a parameter a gate never reads would assert a
capability it does not have.

THREE GATES NARROW ``solve_state`` AND ONE NARROWS ``solved_data``. They are
independent fields that merely share the ``SolveDataUnavailable`` type, which is
why ``_ABSENCE_FIELD`` exists: a test that set the wrong field would exercise the
PRESENT arm of the gate under test and still go green.

THE SNAPSHOTS COME FROM ``assemble_snapshot``, never from a direct
``DesignSnapshot(...)`` -- see ``gating_helpers`` for why a hand-built input would
let a gate be tested against a shape W-8 could not produce.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, get_args

import pytest
from gating_helpers import (
    empty_solved_data,
    intent,
    matching_entry,
    round_tripped,
    snapshot,
    solve_state,
    swept,
    unavailable,
    variation,
)

from hfss_agent import gating
from hfss_agent.contract import (
    CONTRACT_VERSION,
    ConvergenceStatus,
    DesignSnapshot,
    Finding,
    SolutionExists,
    SolveDataUnavailable,
    SolveDataUnavailableReason,
)
from hfss_agent.gating import common as gating_common
from hfss_agent.gating import (
    convergence,
    freshness,
    solution_exists,
    target_coverage,
)
from hfss_agent.gating.gates import GATE_NAMES, evaluate_gates

# The four gates, by the name their rule_id and calculation_ref encode. Written as
# a mapping here rather than imported from the package so a test comparing names is
# comparing against a second source. Values are the REAL module functions, so the
# identity assertion in the calculation_ref test still means something.
_GATES = {
    "solution_exists": solution_exists.evaluate,
    "convergence": convergence.evaluate,
    "freshness": freshness.evaluate,
    "target_coverage": target_coverage.evaluate,
}

# Modules in the package that are NOT gates. Named explicitly so adding one is a
# deliberate act, and verified below to genuinely lack ``evaluate`` -- so this list
# cannot be used to hide a gate from the suite.
_NON_GATE_MODULES = {"common", "gates"}


def _run(
    gate_name: str,
    snap: DesignSnapshot,
    target_frequency_hz: float | None = None,
) -> Finding:
    """Call one gate through ITS OWN signature.

    ``target_coverage`` alone takes a second parameter, because it is the only gate
    whose question involves a value the caller names. The three siblings
    deliberately did not grow an ignored one -- a parameter a function never reads
    asserts a capability that does not exist. That asymmetry has to be paid for
    somewhere, and here is the test suite's one place, mirroring
    ``gates.evaluate_gates``' single non-uniform call.
    """
    if gate_name == "target_coverage":
        return _GATES[gate_name](snap, target_frequency_hz)
    return _GATES[gate_name](snap)


# --- 1. solution_exists, the SolveState arm ----------------------------------


def test_a_matching_solved_entry_passes() -> None:
    finding = solution_exists.evaluate(snapshot())
    assert finding.outcome == "pass"
    assert finding.observed_values["exists"] is True
    assert finding.observed_values["matching_entries"] == 1
    assert finding.applicability.held is True


def test_a_matching_unsolved_entry_fails() -> None:
    """``exists=False`` is a NEGATIVE OBSERVATION, and the one thing that fails."""
    snap = snapshot(solve_state=solve_state(entries=[matching_entry(exists=False)]))
    finding = solution_exists.evaluate(snap)
    assert finding.outcome == "fail"
    assert finding.observed_values["exists"] is False
    # The gate reached a determination, so its preconditions DID hold. ``held`` is
    # about applicability, never about whether the answer was favourable.
    assert finding.applicability.held is True


def test_an_empty_flag_list_is_insufficient_evidence_not_a_failure() -> None:
    """D1. Absence of an observation is not a negative observation.

    Neither adapter can produce this today -- the real one builds a
    single-element list FROM the selection, the fake hard-codes one entry -- but
    the contract permits it (``list[SolutionExists]`` has no ``min_length``), so a
    gate must decide. ``fail`` would assert "no solution exists here" on evidence
    the wrapper does not hold.
    """
    snap = snapshot(solve_state=solve_state(entries=[]))
    finding = solution_exists.evaluate(snap)
    assert finding.outcome == "insufficient_evidence"
    assert finding.observed_values["entries_reported"] == 0
    assert finding.observed_values["matching_entries"] == 0
    assert "exists" not in finding.observed_values
    assert finding.applicability.held is False


def test_a_flag_for_a_different_setup_is_insufficient_evidence() -> None:
    """The state the FAKE adapter can actually reach, and why ``fail`` is wrong.

    The fake hard-codes ``setup="Setup1"``, so a suite that selects anything else
    lands here. Reporting that as ``fail`` would surface a fixture mistake as a
    product finding about the user's design.
    """
    other = SolutionExists(
        setup="SomeOtherSetup", sweep="Sweep1", variation=variation(), exists=True
    )
    snap = snapshot(solve_state=solve_state(entries=[other]))
    finding = solution_exists.evaluate(snap)
    assert finding.outcome == "insufficient_evidence"
    assert finding.observed_values["entries_reported"] == 1
    assert finding.observed_values["matching_entries"] == 0


def test_two_entries_claiming_one_selection_is_insufficient_evidence() -> None:
    """``!= 1`` rather than ``not matching``: a duplicate is a disagreement.

    Two entries matching one selection disagree about something even when both say
    the same thing today, and taking the first would hide it.
    """
    snap = snapshot(
        solve_state=solve_state(
            entries=[matching_entry(exists=True), matching_entry(exists=False)]
        )
    )
    finding = solution_exists.evaluate(snap)
    assert finding.outcome == "insufficient_evidence"
    assert finding.observed_values["matching_entries"] == 2


# --- 2. convergence, the SolveState arm --------------------------------------


def test_a_converged_solve_passes() -> None:
    finding = convergence.evaluate(snapshot())
    assert finding.outcome == "pass"
    assert finding.observed_values["convergence_status"] == "converged"
    assert finding.applicability.held is True


def test_a_stopped_solve_warns_and_does_not_fail() -> None:
    """Neda's ruling (ADR-30 dec. 6), which is the whole reason this arm exists.

    ``warning`` is a member of ``GATE_OUTCOMES_THAT_QUALIFY_COMPUTATION``, so this
    outcome is what lets W-7 return numbers beside a caveat rather than refusing.
    A regression to ``fail`` would silently restore the pre-2.6a behaviour of
    withholding numbers from every non-converged solve.
    """
    snap = snapshot(solve_state=solve_state(convergence_status="stopped"))
    finding = convergence.evaluate(snap)
    assert finding.outcome == "warning"
    assert finding.classification == "warning"
    assert "may be wrong" in finding.reason_flagged


@pytest.mark.parametrize(
    "delta_s",
    [[0.021], [0.15], [0.9, 0.5, 0.3], [0.0009]],
    ids=["just-over", "far-over", "descending", "tiny"],
)
def test_no_delta_s_magnitude_changes_the_convergence_outcome(
    delta_s: list[float],
) -> None:
    """SHE GAVE NO THRESHOLD AND NONE MAY BE INVENTED (ADR-30 dec. 6).

    The decisive case is ``[0.0009]`` beside ``stopped``: a delta-S small enough
    that any invented cutoff would call it converged. If someone adds a threshold,
    this parameter is the one that goes red.
    """
    stopped = convergence.evaluate(
        snapshot(solve_state=solve_state(convergence_status="stopped", delta_s=delta_s))
    )
    converged = convergence.evaluate(
        snapshot(
            solve_state=solve_state(convergence_status="converged", delta_s=delta_s)
        )
    )
    assert stopped.outcome == "warning"
    assert converged.outcome == "pass"
    assert stopped.observed_values["delta_s_progression"] == delta_s


def test_the_pass_history_is_counted_and_never_read_inside() -> None:
    """``adaptive_pass_history`` is ``list[Any]`` with a mock-only row shape.

    A row here is a bare string rather than the fake's dict, so a gate that
    reached inside one would raise. Passing proves only the length is read.
    """
    snap = snapshot(
        solve_state=solve_state(pass_history=["not a dict", "also not a dict"])
    )
    finding = convergence.evaluate(snap)
    assert finding.outcome == "pass"
    assert finding.observed_values["adaptive_pass_count"] == 2


# --- 3. the absence arm, exhaustively ----------------------------------------

# THE DECIDED MAPPING, WRITTEN INDEPENDENTLY OF THE GATE MODULES. Nothing here
# reads ``_ABSENCE_OUTCOMES`` from the product code, so this cannot pass by
# tautology: a changed mapping fails the behavioural test below, and a changed
# Literal fails the set-equality test beside it.
_ABSENCE_MAPPING: dict[str, dict[str, str]] = {
    "solution_exists": {
        # The only member that is a NEGATIVE OBSERVATION rather than an absent
        # one, and the only ``fail`` in either table.
        "no_solution": "fail",
        "not_exposed_by_pyaedt": "insufficient_evidence",
        "not_found_in_design": "insufficient_evidence",
        "unrecognised_by_wrapper": "insufficient_evidence",
    },
    "convergence": {
        # ``no_solution`` is NOT a convergence failure: it is the absence of a
        # solve to have an opinion about. Routing it to ``fail`` would report a
        # never-run solve as a non-converged one.
        "no_solution": "insufficient_evidence",
        "not_exposed_by_pyaedt": "insufficient_evidence",
        "not_found_in_design": "insufficient_evidence",
        "unrecognised_by_wrapper": "insufficient_evidence",
    },
    "freshness": {
        # Uniform for a reason the other two do not share: this gate has ONE legal
        # outcome on BOTH arms, by design (Part 3b). The rows are written out
        # anyway so a fifth Literal member with a different right answer cannot be
        # absorbed silently.
        "no_solution": "insufficient_evidence",
        "not_exposed_by_pyaedt": "insufficient_evidence",
        "not_found_in_design": "insufficient_evidence",
        "unrecognised_by_wrapper": "insufficient_evidence",
    },
    "target_coverage": {
        # Uniform again, and for a THIRD distinct reason: none of the four is a
        # negative observation about COVERAGE. ``no_solution`` is the one to check
        # rather than assume -- it fails on ``solution_exists``, because there it
        # answers that gate's question, but here it says only that no series
        # arrived. Mapping it to ``fail`` would report "your target is outside the
        # sweep" when no sweep was read at all.
        "no_solution": "insufficient_evidence",
        "not_exposed_by_pyaedt": "insufficient_evidence",
        "not_found_in_design": "insufficient_evidence",
        "unrecognised_by_wrapper": "insufficient_evidence",
    },
}

# WHICH SNAPSHOT FIELD EACH GATE'S ABSENCE ARM LIVES ON. The table above could not
# simply gain a fourth row: three gates narrow ``solve_state`` and
# ``target_coverage`` narrows ``solved_data``, and those are INDEPENDENT fields
# that merely share the ``SolveDataUnavailable`` type.
#
# THE TRAP THIS CLOSES, and it is a silent one. A behavioural test that set
# ``solve_state=unavailable(reason)`` for every gate would hand ``target_coverage``
# a snapshot whose ``solved_data`` is still PRESENT -- so that gate would take its
# solved arm, return ``insufficient_evidence`` for the unrelated reason that no
# target was supplied, and the assertion would pass while testing nothing about the
# absence arm at all. Right answer, wrong reason, green suite.
_ABSENCE_FIELD = {
    "solution_exists": "solve_state",
    "convergence": "solve_state",
    "freshness": "solve_state",
    "target_coverage": "solved_data",
}


@pytest.mark.parametrize("gate_name", sorted(_ABSENCE_MAPPING))
def test_absence_mapping_covers_every_reason(gate_name: str) -> None:
    """SET EQUALITY, NOT CONTAINMENT, and the direction matters both ways.

    A ``<=`` check would pass for a new ``SolveDataUnavailableReason`` member with
    no row here -- the rot this guards against -- and a ``>=`` check would pass for
    a row whose member was deleted. Only equality fails on both.

    THIS IS THE ONLY THING ENFORCING EXHAUSTIVENESS. There is no type checker in
    this project (CI runs ``ruff check`` and ``pytest``, nothing else), so a
    missing branch in a gate's reason lookup is caught by no static analysis at
    all. The gates use a bare ``dict[...]`` subscript with no default precisely so
    an unmapped member raises loudly; this test is what makes sure the mapping is
    complete before that can happen at runtime.

    Built as the sibling of
    ``test_snapshot_absence_arms.test_every_reason_member_names_at_least_one_adapter_refusal``.
    """
    assert set(get_args(SolveDataUnavailableReason)) == set(_ABSENCE_MAPPING[gate_name])


@pytest.mark.parametrize("gate_name", sorted(_ABSENCE_MAPPING))
@pytest.mark.parametrize("reason", sorted(get_args(SolveDataUnavailableReason)))
def test_each_absence_reason_yields_its_decided_outcome(
    gate_name: str, reason: str
) -> None:
    """The behavioural half: the gate really does emit what the table says.

    THE ABSENCE IS PLANTED ON THE FIELD THAT GATE ACTUALLY NARROWS -- see
    ``_ABSENCE_FIELD`` for the silent green this avoids.

    A TARGET IS ALWAYS SUPPLIED, so that for ``target_coverage`` the absent field
    is the ONLY blocker. Without it that gate would return the right outcome for
    the wrong reason (no target), and the assertion would not distinguish them.
    The other three ignore the argument.
    """
    field = _ABSENCE_FIELD[gate_name]
    snap = snapshot(**{field: unavailable(reason)})
    finding = _run(gate_name, snap, target_frequency_hz=2.4e9)
    assert finding.outcome == _ABSENCE_MAPPING[gate_name][reason]
    assert finding.observed_values["reason"] == reason
    assert finding.applicability.held is False
    assert finding.inspected == [f"{field}.reason", f"{field}.limitation"]


@pytest.mark.parametrize("gate_name", sorted(_ABSENCE_FIELD))
def test_the_absence_field_names_the_field_each_gate_actually_narrows(
    gate_name: str,
) -> None:
    """``_ABSENCE_FIELD`` is load-bearing suite metadata, and this is its guard.

    A WRONG ENTRY IS ALREADY CAUGHT, and this test does not pretend otherwise --
    measured, not assumed: pointing ``target_coverage`` at ``solve_state`` fails
    ``test_each_absence_reason_yields_its_decided_outcome`` in all four of its
    cases, because that gate takes its PRESENT arm and ``observed_values`` then has
    no ``reason`` key. So the coverage here overlaps.

    WHAT THIS ADDS IS DIAGNOSIS AND ONE ASSERTION THE OTHER CANNOT MAKE.
    Diagnosis: the existing failure is a ``KeyError`` on a data assertion, which
    points a maintainer at ``observed_values`` rather than at the metadata that is
    actually wrong. And two further tests -- ``test_every_inspected_path_resolves_
    on_the_snapshot`` and ``test_the_provenance_is_complete_under_both_arms`` --
    route through ``_snapshot_for_arm`` and stay GREEN under the same mutation,
    silently exercising the present arm while claiming the absent one. Naming the
    invariant is what stops that degradation being invisible.

    THE SECOND ASSERTION IS THE GENUINELY NEW ONE. It proves the blanking is
    TARGETED: the other absence-carrying field is still present, so this gate is
    being handed a snapshot where exactly one arm flipped. A never-solved snapshot
    (both fields blank) would satisfy the first assertion for free and would test
    nothing about which field belongs to which gate.
    """
    field = _ABSENCE_FIELD[gate_name]
    snap = snapshot(**{field: unavailable("not_exposed_by_pyaedt")})
    finding = _run(gate_name, snap, target_frequency_hz=2.4e9)
    # Took its absence arm: it named the blanked field and nothing else, which no
    # present-arm path of any gate does.
    assert finding.inspected == [f"{field}.reason", f"{field}.limitation"]
    # And exactly one arm flipped -- see the docstring for why this matters.
    other = "solved_data" if field == "solve_state" else "solve_state"
    assert not isinstance(getattr(snap, other), SolveDataUnavailable)


def test_convergence_status_mapping_covers_every_member() -> None:
    """The second exhaustive lookup, on the same construction as the first.

    ``ConvergenceStatus`` has two members today. A third added later must be a
    decision made HERE rather than a ``KeyError`` discovered in production.
    """
    decided = {"converged": "pass", "stopped": "warning"}
    assert set(get_args(ConvergenceStatus)) == set(decided)
    for status, expected in decided.items():
        snap = snapshot(solve_state=solve_state(convergence_status=status))
        assert convergence.evaluate(snap).outcome == expected


# --- 4. determinism ----------------------------------------------------------


def _all_findings(snap: DesignSnapshot) -> list[Finding]:
    return [_run(name, snap) for name in GATE_NAMES]


def _as_json(findings: list[Finding]) -> list[str]:
    return [finding.model_dump_json() for finding in findings]


def test_the_same_snapshot_yields_byte_identical_findings() -> None:
    """A gate is a PURE FUNCTION of the snapshot (ADR-30 dec. 2 depends on it).

    That decision refuses ``evaluated_at`` on the grounds that minting one would
    mean calling a clock from the module whose determinism is what makes it
    testable. This is the test that makes the claim true rather than asserted.

    ``model_dump_json`` rather than object equality or a Python-mode dump,
    following ``test_metrics_assembly``'s stated reasoning: a Python-mode dump
    would happily keep values strict JSON cannot carry and prove nothing.

    WHAT THIS TEST CATCHES, AND THE ONE THING IT MEASURABLY DOES NOT. Three
    non-deterministic values were planted in ``convergence._from_solve_state`` and
    the file restored byte-for-byte after each:

      * ``random.random()``      -> this test FAILS. Caught.
      * ``time.perf_counter_ns()`` -> this test FAILS. Caught.
      * ``time.time()``          -> this test PASSES. NOT CAUGHT.

    The third is not a structural gap but a resolution one, and it is worth
    knowing rather than assuming: ``time.time()`` returns a float near 1.75e9, and
    float64 carries about sixteen significant digits there, so two calls a few
    microseconds apart can land on the SAME representable value and serialize
    identically. A clock planted in that exact spelling would slip past this
    assertion.

    SO THIS TEST IS THE BACKSTOP, NOT THE PRIMARY GUARD. The primary guard is the
    gating import audit (Part 5), which forbids the import rather than hoping to
    observe its effect -- and this measurement is the argument for that audit
    being an ALLOW-LIST: a behavioural check demonstrably cannot see every clock.
    """
    snap = snapshot()
    assert _as_json(_all_findings(snap)) == _as_json(_all_findings(snap))


def test_two_equal_snapshots_yield_byte_identical_findings() -> None:
    """The second assertion, so the first cannot pass by returning one object.

    A JSON round-trip gives EQUAL VALUES in a genuinely separate object graph --
    a ``model_copy`` would share sub-objects, and a second ``snapshot()`` call
    would differ, since ``created_at`` and ``snapshot_id`` are minted per call. So
    this is the only construction that isolates "depends on the data" from
    "depends on the identity".
    """
    original = snapshot()
    twin = round_tripped(original)
    assert twin == original
    assert twin is not original
    assert _as_json(_all_findings(original)) == _as_json(_all_findings(twin))


# --- 5. the field conventions ------------------------------------------------


def test_the_finding_ids_in_one_evaluation_are_distinct() -> None:
    """The property D6's content-derived id relies on.

    The id is unique WITHIN one evaluation because the gate names differ; it is
    NOT globally unique, and nothing here claims it is. If a gate name is ever
    duplicated, or the id stops carrying the name, this is what notices.
    """
    ids = [finding.finding_id for finding in _all_findings(snapshot())]
    assert len(set(ids)) == len(ids)
    assert set(ids) == {
        "gate-solution_exists-pass",
        "gate-convergence-pass",
        # Freshness carries its outcome like the others; that outcome is simply
        # always the same one (Part 3b). The id shape is unchanged by that.
        "gate-freshness-insufficient_evidence",
        # And target_coverage on the default snapshot, which carries no intent and
        # is given no parameter here -- Neda's no-target case.
        "gate-target_coverage-insufficient_evidence",
    }


def test_the_id_is_derived_from_content_not_minted() -> None:
    """Two evaluations of equal snapshots produce the SAME id, not a fresh one.

    A ``uuid4()`` would fail this, and it is the assertion that keeps ``uuid`` out
    of the module -- which is what lets Part 5's import allow-list stay closed.
    """
    first = solution_exists.evaluate(snapshot())
    second = solution_exists.evaluate(snapshot())
    assert first.finding_id == second.finding_id == "gate-solution_exists-pass"
    # And it tracks the outcome, so two different verdicts are distinguishable.
    failing = solution_exists.evaluate(
        snapshot(solve_state=solve_state(entries=[matching_entry(exists=False)]))
    )
    assert failing.finding_id == "gate-solution_exists-fail"


@pytest.mark.parametrize("gate_name", sorted(_GATES))
def test_every_gate_emits_the_constant_severity(gate_name: str) -> None:
    """``severity`` IS DEGENERATE ON PURPOSE, and this is what says so.

    A deliberate constant is indistinguishable from an accidental one unless
    something asserts it, which is the whole reason this test exists rather than
    being folded into a field-shape check. ``Finding`` already declares two
    judgment axes and ``finding.py`` calls ``classification`` "the coarse severity
    classification" -- so the severity axis exists and is spelled
    ``classification``. A second, varying, free-string severity would be two homes
    for one fact.

    Both pre-existing fixtures use ``"info"`` and it is the only
    ``Finding.severity`` value anywhere in the repo, so this follows them rather
    than inventing a vocabulary. NOTE the near-miss: ``ComponentCheck.severity`` is
    a different field on a different type with a closed
    ``Literal["required", "advisory"]``; copying that here would be silently wrong.
    """
    assert _run(gate_name, snapshot()).severity == "info"


@pytest.mark.parametrize("gate_name", sorted(_GATES))
def test_calculation_ref_names_a_real_importable_callable(gate_name: str) -> None:
    """Recon found NOTHING pins the composed module paths -- this is that test.

    ``tests/metrics/assembly_helpers.FOUR_GATE_NAMES`` pins four BARE NAMES, and
    the ``hfss_agent.gating.<name>:evaluate`` form is composed one function away in
    an f-string; ``tests/schemas/conftest.py`` carries the only literal, and only
    for one of the four. So no existing test would notice if a gate's
    ``calculation_ref`` pointed at nothing.

    RESOLVED, NOT JUST STRING-MATCHED. A reference into the open formula code is
    the evidence field a reader follows to check a judgment; one that does not
    import is a dead citation, and a string comparison alone would not catch it.
    """
    finding = _run(gate_name, snapshot())
    expected = f"hfss_agent.gating.{gate_name}:evaluate"
    assert finding.calculation_ref == expected
    assert finding.rule_id == f"gate.{gate_name}"

    module_path, separator, attribute = finding.calculation_ref.partition(":")
    assert separator == ":", "the ref must carry the module:attribute separator"
    resolved = getattr(importlib.import_module(module_path), attribute)
    assert callable(resolved)
    # And it is the very function that produced this finding, not a same-named
    # callable in some other module.
    assert resolved is _GATES[gate_name]


def _resolve(obj: object, dotted: str) -> Any:
    for part in dotted.split("."):
        obj = getattr(obj, part)
    return obj


def _snapshot_for_arm(gate_name: str, solve: str | None) -> DesignSnapshot:
    """The solved arm, or the absence arm OF THE FIELD THIS GATE NARROWS.

    GATE-AWARE, because the field differs: three gates narrow ``solve_state`` and
    ``target_coverage`` narrows ``solved_data``. Blanking the wrong field would
    hand the gate under test its PRESENT arm, so an "absence arm" test would
    silently exercise the other one.

    ``not_exposed_by_pyaedt`` rather than ``no_solution``, deliberately: the latter
    is the one reason that yields a ``fail`` on ``solution_exists``, which would
    make an arm-shape test also depend on a verdict mapping.
    """
    if solve is None:
        return snapshot()
    return snapshot(**{_ABSENCE_FIELD[gate_name]: unavailable("not_exposed_by_pyaedt")})


@pytest.mark.parametrize("gate_name", sorted(_GATES))
@pytest.mark.parametrize(
    "solve",
    [None, "absent"],
    ids=["solve-state-arm", "absence-arm"],
)
def test_every_inspected_path_resolves_on_the_snapshot(
    gate_name: str, solve: str | None
) -> None:
    """``inspected`` names snapshot elements, so every entry must BE one.

    THIS GUARDS A BUG THAT ALREADY EXISTS ONE SUITE OVER.
    ``tests/metrics/assembly_helpers.gate()`` builds ``inspected`` as
    ``[f"solve_state.{name}"]``, which names ``solve_state.freshness`` and
    ``solve_state.target_coverage`` -- neither of which is a field on anything.
    That is harmless there because the value is an input rather than an assertion,
    but copying the spelling into the product would put a dead path into the one
    field a reader uses to retrace a judgment.

    Both arms are exercised because the paths legitimately DIFFER between them:
    the absence arm names ``solve_state.reason``, which does not resolve on a
    ``SolveState``, and vice versa.
    """
    snap = _snapshot_for_arm(gate_name, solve)
    finding = _run(gate_name, snap)
    assert finding.inspected, "a gate must name what it read"
    for path in finding.inspected:
        _resolve(snap, path)


@pytest.mark.parametrize("gate_name", sorted(_GATES))
def test_the_classification_follows_the_decided_mapping(gate_name: str) -> None:
    """The 5-to-3 map the contract deliberately left open.

    ``warning`` covers exactly the two members of
    ``GATE_OUTCOMES_THAT_QUALIFY_COMPUTATION``, which makes ``classification`` a
    readable proxy for "this result travels with a caveat".
    """
    decided = {
        "pass": "judgment_call",
        "fail": "error",
        "warning": "warning",
        "not_evaluated": "judgment_call",
        "insufficient_evidence": "warning",
    }
    for snap in (
        snapshot(),
        snapshot(solve_state=solve_state(convergence_status="stopped")),
        snapshot(solve_state=solve_state(entries=[matching_entry(exists=False)])),
        snapshot(solve_state=unavailable("no_solution")),
        snapshot(solve_state=unavailable("not_exposed_by_pyaedt")),
    ):
        finding = _run(gate_name, snap)
        assert finding.classification == decided[finding.outcome]


# --- 6. provenance -----------------------------------------------------------


@pytest.mark.parametrize("gate_name", sorted(_GATES))
@pytest.mark.parametrize(
    "solve",
    [None, "absent"],
    ids=["solve-state-arm", "absence-arm"],
)
def test_the_provenance_is_complete_under_both_arms(
    gate_name: str, solve: str | None
) -> None:
    """ADR-30 dec. 1's shaping property, tested rather than asserted in prose.

    Every required field of ``FindingProvenance`` is sourceable from a snapshot
    under BOTH arms of ``solve_state`` -- which is why a gate can report on a
    design that was never solved, the ordinary case rather than an edge one. The
    recon found this property lived ONLY in docstrings
    (``tests/schemas/conftest.py``, ``provenance_record.py``) with no assertion
    anywhere; this is the assertion.
    """
    snap = _snapshot_for_arm(gate_name, solve)
    provenance = _run(gate_name, snap).provenance
    assert provenance.project == "patch_antenna"
    assert provenance.design == "HFSSDesign1"
    assert provenance.solution_type == "DrivenModal"
    assert provenance.setup == "Setup1"
    assert provenance.sweep == "Sweep1"
    assert provenance.variation == snap.selection.variation
    assert provenance.snapshot_id == snap.snapshot_id
    assert provenance.contract_version == CONTRACT_VERSION
    assert provenance.wrapper_version == "0.0.0"


@pytest.mark.parametrize("gate_name", sorted(_GATES))
def test_no_gate_ever_claims_an_engine_version(gate_name: str) -> None:
    """A gate has no engine behind it and never will, by construction.

    ``engine_version`` is ``FindingProvenance``'s one optional, and the rule
    permitting it turns on an engine RULE filling it while a gate genuinely
    cannot. A gate that set it would be claiming a capability that does not exist.
    """
    assert _run(gate_name, snapshot()).provenance.engine_version is None


def test_the_provenance_carries_no_filesystem_path() -> None:
    """``Selection.project`` is the bare NAME (ADR-28), and a finding leaves.

    The helper's selection chain deliberately carries a real Windows project path
    -- one that embeds an operator account name -- so W-8's drop is exercised
    rather than arranged away. A finding travels to W-10 and into a tool response,
    so a path reaching the provenance would leave this process.
    """
    provenance = solution_exists.evaluate(snapshot()).provenance
    serialized = provenance.model_dump_json()
    assert "Ansoft" not in serialized
    assert "Owner" not in serialized
    assert ".aedt" not in serialized


# --- 7. the shape every finding shares ---------------------------------------


@pytest.mark.parametrize("gate_name", sorted(_GATES))
def test_every_finding_is_a_gate_finding_with_deterministic_text(
    gate_name: str,
) -> None:
    """``source`` and the ``template_text`` prefix, both fixed by the fixtures.

    The prefix ``[gate] <name>: <outcome>`` is the spelling BOTH pre-existing
    fixtures use. The text is rendered from fields the finding already carries, so
    it cannot disagree with them -- which is what the second assertion checks.
    """
    finding = _run(gate_name, snapshot())
    assert finding.source == "gate"
    assert finding.template_text.startswith(
        f"[gate] {gate_name}: {finding.outcome}."
    )
    assert finding.reason_flagged in finding.template_text
    assert finding.rule_version == "1.0.0"
    assert finding.rule_purpose


@pytest.mark.parametrize("gate_name", sorted(_GATES))
def test_every_gate_names_at_least_one_applicability_condition(
    gate_name: str,
) -> None:
    """A gate must NAME its preconditions, on every arm it reaches.

    REDUCED FROM A TEST THAT ALSO RECOMPUTED ``held``. That half asserted
    ``held == all(conditions.values())`` over the builder's own output, which is
    the expression the builder had just evaluated on the same data -- it could not
    fail while the builder computed it that way, whatever the conditions were. The
    derivation is now pinned once, at the builder, by
    ``test_the_builder_derives_held_from_its_conditions``.

    THIS LIMB SURVIVES BECAUSE IT IS NOT DERIVABLE FROM THE LINE ABOVE IT.
    ``all({}.values())`` is ``True``, so a gate shipping ``conditions={}`` would
    produce ``held=True`` with nothing named -- a claim that conditions held when
    none were stated. Only a non-emptiness check on the output can see that, and
    the builder deliberately does not raise on it (see ``common.applicability``).
    """
    for snap in (
        snapshot(),
        snapshot(solve_state=solve_state(convergence_status="stopped")),
        snapshot(solve_state=solve_state(entries=[])),
        snapshot(solve_state=solve_state(determinable=True)),
        snapshot(solve_state=unavailable("no_solution")),
        snapshot(solve_state=unavailable("unrecognised_by_wrapper")),
    ):
        conditions = _run(gate_name, snap).applicability.conditions
        assert conditions, "a gate must name its preconditions"


@pytest.mark.parametrize(
    ("conditions", "expected"),
    [
        ({"only": True}, True),
        ({"first": True, "second": True}, True),
        ({"first": True, "second": False}, False),
        ({"only": False}, False),
        ({"first": False, "second": False}, False),
    ],
    ids=["one-true", "all-true", "one-false", "single-false", "all-false"],
)
def test_the_builder_derives_held_from_its_conditions(
    conditions: dict[str, object], expected: bool
) -> None:
    """``held`` is derived AT THE BUILDER, so it is pinned at the builder.

    Guards ``common.applicability`` directly rather than recomputing over a gate's
    output. The difference is what makes this non-vacuous: a refactor that gave
    ``applicability`` a ``held`` parameter, or that changed ``all`` to ``any``,
    fails HERE -- whereas a test asserting the same expression over a gate's
    finished ``Applicability`` would agree with the implementation by construction.

    ``one-false`` is the decisive row: ``any`` and ``all`` differ only when the
    conditions disagree with each other, so a mixed case is the one a wrong
    reduction cannot survive.
    """
    assert gating_common.applicability(conditions).held is expected


# --- 8. freshness: one legal outcome, by design ------------------------------


@pytest.mark.parametrize(
    ("determinable", "signals"),
    [
        (False, {}),
        (True, {"design_modified_since_solve": False}),
        (True, {"design_modified_since_solve": True}),
        (True, {"some_future_signal": "anything at all"}),
    ],
    ids=["real-adapter-shape", "fake-shape", "fake-shape-modified", "unknown-key"],
)
def test_freshness_is_insufficient_evidence_whatever_the_signals_say(
    determinable: bool, signals: dict[str, Any]
) -> None:
    """THE BEHAVIOURAL STATEMENT OF THE PART-3b DECISION (option (c)).

    The gate decides on ``determinable`` alone and never on a key, so no value of
    ``available_signals`` can move the outcome. The two ``design_modified_since_
    solve`` rows are the ones that matter and they are deliberately opposite: a
    gate that branched on that key to PASS would fail the ``False`` row, and one
    that branched on it to FAIL would fail the ``True`` row. Between them they
    catch a key-branch in either direction -- which is the whole prohibition the
    contract states and this module obeys.

    ``real-adapter-shape`` is the only row reachable on real hardware; the other
    three exist only against the fake, which is itself the accepted limitation
    recorded in the module docstring.
    """
    snap = snapshot(
        solve_state=solve_state(determinable=determinable, signals=signals)
    )
    finding = freshness.evaluate(snap)
    assert finding.outcome == "insufficient_evidence"
    assert finding.classification == "warning"
    assert finding.applicability.held is False


def test_freshness_carries_the_evidence_step_3_4_needs_to_derive_from() -> None:
    """The NARROWED obligation from Part 2: enable the derivation, mint nothing.

    Step 3.4 must fill ``ProvenanceRecord.freshness_status`` -- required on every
    ``MetricRecord`` -- and a ``Finding`` travels without the snapshot beside it.
    So both halves of the evidence must be ON the finding: the flag that was
    branched on, and the signals that were not.

    Copied VERBATIM, including a key this package has no vocabulary for. That is
    the point of ``dict(...)`` rather than a filtered projection: filtering would
    require deciding which keys matter, which is the vocabulary ADR-30 dec. 16
    declined to mint.
    """
    signals = {"design_modified_since_solve": False, "unknown": [1, 2]}
    snap = snapshot(solve_state=solve_state(determinable=True, signals=signals))
    observed = freshness.evaluate(snap).observed_values
    assert observed["determinable"] is True
    assert observed["available_signals"] == signals


def test_freshness_on_the_absence_arm_reports_no_determinable_at_all() -> None:
    """Its ABSENCE is the honest signal, so it must not be defaulted to False.

    There is no freshness evidence on the absence arm, so reporting
    ``determinable=False`` there would assert the wrapper looked and found the
    answer unobtainable, when in truth there was nothing to look at. Step 3.4
    derives its status from the reason instead, which is why the reason travels.
    """
    snap = snapshot(solve_state=unavailable("not_exposed_by_pyaedt"))
    observed = freshness.evaluate(snap).observed_values
    assert "determinable" not in observed
    assert "available_signals" not in observed
    assert observed["reason"] == "not_exposed_by_pyaedt"


def test_freshness_never_claims_the_results_are_current() -> None:
    """The accepted risk, stated on every finding rather than only in an ADR.

    A reader who sees ``insufficient_evidence`` must not read it as "current". The
    limitation text is the only place that distinction is carried to them, so it
    is required to say that staleness cannot be reported at all.
    """
    limitations = freshness.evaluate(snapshot()).limitations_and_assumptions
    assert "CANNOT REPORT STALENESS" in limitations
    assert "determinable=False unconditionally" in limitations
    assert "never as 'the results are current'" in limitations


def test_every_gate_module_in_the_package_is_under_test() -> None:
    """No gate module may exist without appearing in this suite's registry.

    REPLACED A TEST THAT COMPARED TWO LISTS I HAD WRITTEN IN THE SAME CHANGE. That
    version asserted the test module's ``_GATES`` equalled a ``BUILT_GATES``
    constant in the helper file, which nothing else read -- so the constant existed
    only to be compared against, and both could drift together and stay green. It
    said nothing about ``hfss_agent`` at all.

    This one reads the PACKAGE DIRECTORY instead, so the failure it catches is the
    real one: Part 4 adding ``target_coverage.py`` (or ``freshness.py``, if the
    escalation resolves that way) and forgetting to register it here, which would
    leave a shipped gate with no test and a green suite.

    ``common`` is excluded because it is the shared primitives module, not a gate;
    a gate is identified by exposing ``evaluate``, which is asserted rather than
    assumed.
    """
    package_dir = Path(gating.__file__).parent
    modules = {
        path.stem for path in package_dir.glob("*.py") if path.stem != "__init__"
    }
    assert modules - _NON_GATE_MODULES == set(_GATES), (
        "every module in hfss_agent.gating that is not listed in "
        "_NON_GATE_MODULES is a gate and must be registered in this suite"
    )
    # A gate IS a module exposing ``evaluate``; asserted rather than assumed, so a
    # new gate that forgot to expose one is caught here rather than by a confusing
    # AttributeError somewhere downstream.
    for name in _GATES:
        module = importlib.import_module(f"{gating.__name__}.{name}")
        assert callable(module.evaluate)
    # And the exclusion list cannot be used to HIDE a gate: every module on it must
    # genuinely lack ``evaluate``, so adding a real gate's name to it fails here.
    for name in _NON_GATE_MODULES:
        module = importlib.import_module(f"{gating.__name__}.{name}")
        assert not hasattr(module, "evaluate"), (
            f"{name} exposes evaluate, so it is a gate and cannot be excluded"
        )


# --- 9. target_coverage: containment, and the target that may not exist ------


def test_a_target_inside_the_sweep_passes() -> None:
    finding = target_coverage.evaluate(snapshot(), 2.4e9)
    assert finding.outcome == "pass"
    assert finding.observed_values["target_frequency_hz"] == 2.4e9
    assert finding.observed_values["target_source"] == "parameter"
    assert finding.observed_values["lowest_swept_hz"] == 2.3e9
    assert finding.observed_values["highest_swept_hz"] == 2.5e9
    assert finding.applicability.held is True


@pytest.mark.parametrize("target", [2.3e9, 2.5e9], ids=["at-lowest", "at-highest"])
def test_a_target_exactly_on_a_bound_is_covered(target: float) -> None:
    """Containment is CLOSED at both ends, which is a decision, not an accident.

    The bounds are swept frequencies that were actually solved, so a target landing
    exactly on one is the best-covered case there is. An open interval would refuse
    the one target whose value needs no interpolation at all.
    """
    assert target_coverage.evaluate(snapshot(), target).outcome == "pass"


@pytest.mark.parametrize(
    "target", [2.2e9, 2.6e9], ids=["below-lowest", "above-highest"]
)
def test_a_target_outside_the_sweep_fails(target: float) -> None:
    """The one ``fail`` this gate can emit, on both sides of the interval."""
    finding = target_coverage.evaluate(snapshot(), target)
    assert finding.outcome == "fail"
    assert finding.classification == "error"
    assert "OUTSIDE" in finding.reason_flagged
    # A verdict WAS reached, so the applicability conditions held.
    assert finding.applicability.held is True


def test_no_target_from_either_source_is_insufficient_evidence() -> None:
    """NEDA'S RULING, as behaviour: insufficient_evidence, not not_evaluated.

    ``insufficient_evidence`` is on ``GATE_OUTCOMES_THAT_QUALIFY_COMPUTATION`` and
    ``not_evaluated`` is not, so this one choice is what lets W-7 still return the
    three whole-sweep metrics under a caveat rather than refusing everything. A
    regression to ``not_evaluated`` would silently implement option B -- show
    nothing -- which is the option she declined.
    """
    snap = snapshot()
    assert snap.intent is None
    finding = target_coverage.evaluate(snap)
    assert finding.outcome == "insufficient_evidence"
    assert "target_frequency_hz" not in finding.observed_values
    assert finding.applicability.conditions["target_supplied"] is False
    assert finding.applicability.held is False
    # The sweep is still reported, which is what makes the finding useful rather
    # than merely negative: a reader learns what range WAS solved.
    assert finding.observed_values["lowest_swept_hz"] == 2.3e9


def test_the_intent_supplies_the_target_when_the_caller_does_not() -> None:
    snap = snapshot(intent=intent(2.45e9))
    finding = target_coverage.evaluate(snap)
    assert finding.outcome == "pass"
    assert finding.observed_values["target_frequency_hz"] == 2.45e9
    assert finding.observed_values["target_source"] == "intent"
    assert "intent.target_frequency_hz" in finding.inspected


def test_the_parameter_wins_and_the_disagreement_stays_recoverable() -> None:
    """D2, and the half that matters is RECOVERABILITY.

    A ``Finding`` is rendered without the snapshot beside it, so a reader who sees
    only the finding cannot otherwise tell that an explicit argument overrode a
    stated intent. Both values therefore travel. The assertions below deliberately
    read ONLY the finding -- never the snapshot -- because that is the situation
    the field exists for.
    """
    snap = snapshot(intent=intent(2.45e9))
    finding = target_coverage.evaluate(snap, 2.35e9)
    assert finding.observed_values["target_frequency_hz"] == 2.35e9
    assert finding.observed_values["target_source"] == "parameter"
    assert finding.observed_values["intent_target_frequency_hz"] == 2.45e9
    # The intent was NOT the source, so it is not named as inspected.
    assert "intent.target_frequency_hz" not in finding.inspected
    # A disagreement does not refuse: asking about a different frequency than the
    # stated intent is an ordinary exploratory question.
    assert finding.outcome == "pass"


def test_both_values_travel_even_when_they_agree() -> None:
    """Absence of the intent value must mean "no intent", never "it agreed".

    Recording it only on disagreement would make the field's absence ambiguous --
    a reader could not tell a design with no intent from one whose intent matched.
    """
    snap = snapshot(intent=intent(2.4e9))
    observed = target_coverage.evaluate(snap, 2.4e9).observed_values
    assert observed["intent_target_frequency_hz"] == 2.4e9
    assert observed["target_source"] == "parameter"


def test_a_zero_hz_target_is_supplied_not_absent() -> None:
    """``is not None``, never truthiness. 0.0 Hz is nonsensical but SUPPLIED.

    Falling through to the intent because the caller passed a falsy float would be
    the wrong kind of helpful: it would silently answer a different question than
    the one asked, and the caller would have no way to see it happened.
    """
    snap = snapshot(intent=intent(2.4e9))
    finding = target_coverage.evaluate(snap, 0.0)
    assert finding.observed_values["target_frequency_hz"] == 0.0
    assert finding.observed_values["target_source"] == "parameter"
    assert finding.outcome == "fail"


def test_an_empty_sweep_is_insufficient_evidence() -> None:
    """No range to test containment against, even with a target in hand."""
    snap = snapshot(solved_data=empty_solved_data())
    finding = target_coverage.evaluate(snap, 2.4e9)
    assert finding.outcome == "insufficient_evidence"
    assert finding.observed_values["sample_count"] == 0
    assert "lowest_swept_hz" not in finding.observed_values
    assert finding.applicability.conditions["sweep_non_empty"] is False


# --- 10. evaluate_gates ------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"solve_state": unavailable("not_exposed_by_pyaedt")},
        {"solved_data": unavailable("no_solution")},
        {
            "solve_state": unavailable("not_exposed_by_pyaedt"),
            "solved_data": unavailable("no_solution"),
        },
        {"solve_state": solve_state(convergence_status="stopped")},
        {"solve_state": solve_state(entries=[])},
    ],
    ids=[
        "solved",
        "no-solve-state",
        "no-solved-data",
        "never-solved",
        "stopped",
        "no-flags",
    ],
)
def test_evaluate_gates_always_returns_four_in_order(
    overrides: dict[str, Any],
) -> None:
    """FOUR, ALWAYS, IN ORDER -- for every snapshot shape including never-solved.

    A gate that could not decide emits a finding SAYING so; it is never omitted.
    Omitting one would make "not applicable" indistinguishable from "forgotten",
    and would quietly falsify W-7's rendered count, which states how many gate
    results it was handed.
    """
    findings = evaluate_gates(snapshot(**overrides))
    assert len(findings) == 4
    assert [f.rule_id for f in findings] == [f"gate.{n}" for n in GATE_NAMES]
    assert all(f.source == "gate" for f in findings)


def test_the_aggregator_order_matches_the_contract_fixtures_spelling() -> None:
    """``GATE_NAMES`` is §1.1's order, and the rule ids encode it.

    Pinned against a literal tuple rather than against ``GATE_NAMES`` itself, so
    reordering the product constant is a visible test diff rather than a silent
    agreement. This is the same spelling the Step 1.1 contract fixtures pinned
    before any gate existed.
    """
    assert GATE_NAMES == (
        "solution_exists",
        "convergence",
        "freshness",
        "target_coverage",
    )


def test_evaluate_gates_passes_the_target_to_the_one_gate_that_takes_one() -> None:
    """The non-uniform dispatch, asserted through its observable effect.

    Without the target reaching ``target_coverage``, that gate would report no
    target supplied. So this is what proves the argument is not silently dropped
    on the way through the aggregator.
    """
    covered = {f.rule_id: f for f in evaluate_gates(snapshot(), 2.4e9)}
    target_finding = covered["gate.target_coverage"]
    assert target_finding.outcome == "pass"
    assert target_finding.observed_values["target_source"] == "parameter"
    # And with no target, the same snapshot yields the no-target report.
    without = {f.rule_id: f for f in evaluate_gates(snapshot())}
    assert without["gate.target_coverage"].outcome == "insufficient_evidence"


def test_evaluate_gates_is_deterministic() -> None:
    """Same snapshot twice, then an equal snapshot -- byte-identical both times.

    The second assertion needs ``round_tripped`` rather than a second
    ``snapshot()`` call: ``assemble_snapshot`` mints ``created_at`` and
    ``snapshot_id`` per call, so two separately built snapshots are never equal and
    their provenance differs. A failure there would look like gate logic and would
    not be.
    """
    snap = snapshot()
    first = [f.model_dump_json() for f in evaluate_gates(snap, 2.4e9)]
    second = [f.model_dump_json() for f in evaluate_gates(snap, 2.4e9)]
    assert first == second

    twin = round_tripped(snap)
    assert twin == snap and twin is not snap
    assert [f.model_dump_json() for f in evaluate_gates(twin, 2.4e9)] == first


def test_evaluate_gates_finding_ids_are_distinct_on_every_shape() -> None:
    """The property the content-derived id relies on, over the aggregator.

    Ids carry ``gate-<name>-<outcome>``, so four distinct names give four distinct
    ids whatever the outcomes are. If a gate name were ever duplicated, or the id
    stopped carrying the name, this notices on the shape where the outcomes
    collide -- never-solved, where all four say the same thing.
    """
    never_solved = snapshot(
        solve_state=unavailable("not_exposed_by_pyaedt"),
        solved_data=unavailable("no_solution"),
    )
    ids = [f.finding_id for f in evaluate_gates(never_solved)]
    assert len(set(ids)) == 4


def test_the_public_surface_is_the_aggregator_only() -> None:
    """``evaluate_gates`` and ``GATE_NAMES``, and nothing else.

    A caller wanting the gate set wants all four in order; re-exporting individual
    gates would make a partial gate list the easy thing to build, which is exactly
    what W-7 cannot detect. The per-gate modules stay importable by path -- the
    ``calculation_ref`` strings must resolve -- but they are not offered here.
    """
    # Set equality already excludes every gate name; a follow-up loop asserting
    # each is absent would restate it, so there isn't one.
    assert set(gating.__all__) == {"evaluate_gates", "GATE_NAMES"}
    assert gating.evaluate_gates is evaluate_gates


def test_not_evaluated_is_unreachable_across_every_gate_and_input_shape() -> None:
    """ENUMERATED, not asserted: no gate emits ``not_evaluated`` on any input.

    ``FindingOutcome`` has five members and this package produces four of them,
    which reads as a gap unless something says otherwise. The record lives at
    ``common.NOT_EVALUATED_IS_UNREACHABLE_IN_GATING``; this is its behavioural
    half, swept over every snapshot shape the suite can build -- both arms of both
    absence-carrying fields, every convergence status, every reason literal, with
    and without a target, with and without an intent.

    A NEW GATE THAT EMITS ``not_evaluated`` FAILS HERE, which is the point: the
    exclusion of that member from ``GATE_OUTCOMES_THAT_QUALIFY_COMPUTATION`` means
    a gate emitting one would refuse all metrics, and that must be a decision
    rather than a side effect.
    """
    shapes: list[DesignSnapshot] = [snapshot(), snapshot(intent=intent(2.4e9))]
    for reason in get_args(SolveDataUnavailableReason):
        shapes.append(snapshot(solve_state=unavailable(reason)))
        shapes.append(snapshot(solved_data=unavailable(reason)))
        shapes.append(
            snapshot(solve_state=unavailable(reason), solved_data=unavailable(reason))
        )
    for status in get_args(ConvergenceStatus):
        shapes.append(snapshot(solve_state=solve_state(convergence_status=status)))
    shapes.append(snapshot(solve_state=solve_state(entries=[])))
    shapes.append(snapshot(solve_state=solve_state(determinable=True)))
    shapes.append(snapshot(solved_data=empty_solved_data()))

    seen: set[str] = set()
    for shape in shapes:
        for target in (None, 2.4e9, 9.9e9):
            seen.update(f.outcome for f in evaluate_gates(shape, target))

    assert "not_evaluated" not in seen, (
        "a gate emitted not_evaluated; it is excluded from the qualifying "
        "allow-list, so it would refuse all metrics"
    )
    # The complement, so this cannot pass by the sweep being too narrow to reach
    # anything: all four other members ARE produced across these shapes.
    assert seen == {"pass", "fail", "warning", "insufficient_evidence"}
    assert gating_common.NOT_EVALUATED_IS_UNREACHABLE_IN_GATING is True


# --- 11. reason_flagged carries what `outcome` cannot ------------------------
#
# THE BAR THESE ARE WRITTEN TO. ``reason_flagged`` is one of only three Finding
# fields that reach a user through W-7's caveat block (traced at Part 6b -- the
# other two are ``rule_id`` and ``outcome``). So the property worth pinning is
# precise: THE REASON MUST DISTINGUISH INPUTS THAT ``outcome`` CANNOT. If two
# genuinely different situations produce the same outcome AND the same reason, a
# reader has no way to tell them apart, and the field has failed at its only job.
#
# DIFFERENTIAL, NOT SUBSTRING. Every assertion below compares two reasons to each
# other rather than to a literal. A REWORDING passes; a DROPPED FACT fails. That
# is the difference between pinning a property and pinning prose, and it is why
# these look different from ``test_freshness_never_claims_the_results_are_current``
# -- a DISCLOSURE is worth pinning verbatim (the Part-6b precedent, where the
# wording is a domain expert's and the words themselves are the deliverable);
# an ordinary evidence sentence is not.


def test_solution_exists_distinguishes_its_three_insufficient_causes() -> None:
    """Three different failures, one outcome. Only the reason separates them.

    An empty flag list, a list whose entries name a different setup, and two
    entries claiming the same selection are three distinct situations that all
    yield ``insufficient_evidence``. A reader who sees only the outcome cannot act
    on any of them; the counts in the reason are what tell them whether the
    adapter reported nothing, reported something irrelevant, or contradicted
    itself.

    WHAT WOULD HAVE TO CHANGE FOR THIS TO FAIL: the three reasons collapsing into
    one generic sentence -- dropping either count, or replacing them with a fixed
    "no determination was made". A reworded sentence that still carries both
    counts passes, which is the point.
    """
    other = SolutionExists(
        setup="SomeOtherSetup", sweep="Sweep1", variation=variation(), exists=True
    )
    causes = {
        "empty": snapshot(solve_state=solve_state(entries=[])),
        "no match": snapshot(solve_state=solve_state(entries=[other])),
        "duplicate": snapshot(
            solve_state=solve_state(
                entries=[matching_entry(True), matching_entry(False)]
            )
        ),
    }
    findings = {
        label: solution_exists.evaluate(snap) for label, snap in causes.items()
    }
    # Same outcome for all three -- which is what makes the reason load-bearing.
    assert {f.outcome for f in findings.values()} == {"insufficient_evidence"}
    reasons = [f.reason_flagged for f in findings.values()]
    assert len(set(reasons)) == 3, (
        "all three insufficient_evidence causes render the same reason, so a "
        f"reader cannot tell them apart: {reasons}"
    )


def test_solution_exists_reports_the_flag_it_read() -> None:
    """``pass`` and ``fail`` differ in outcome, so the reason must add something.

    What it adds is WHICH entry was read: the reason must change when the matched
    entry's ``exists`` flips, so the sentence describes the evidence rather than
    restating the verdict.

    WHAT WOULD HAVE TO CHANGE: the reason becoming a constant string per outcome,
    i.e. saying nothing the outcome did not already say.
    """
    solved = solution_exists.evaluate(snapshot())
    unsolved = solution_exists.evaluate(
        snapshot(solve_state=solve_state(entries=[matching_entry(exists=False)]))
    )
    assert solved.outcome == "pass" and unsolved.outcome == "fail"
    assert solved.reason_flagged != unsolved.reason_flagged


def test_convergence_reports_how_many_passes_ran() -> None:
    """Two solves, same status, different pass counts -- the reason must differ.

    The pass count is the one piece of evidence a reader can act on when a solve
    stopped short: two adaptive passes and nine are different situations with the
    same ``warning``. Neda gave no delta-S threshold, so the count and the
    progression are ALL the evidence this gate is permitted to offer.

    WHAT WOULD HAVE TO CHANGE: the count being dropped from the sentence. Any
    rewording that still reports it passes.
    """
    short = convergence.evaluate(
        snapshot(solve_state=solve_state(pass_history=[{"p": 1}, {"p": 2}]))
    )
    long = convergence.evaluate(
        snapshot(solve_state=solve_state(pass_history=[{"p": n} for n in range(9)]))
    )
    assert short.outcome == long.outcome == "pass"
    assert short.reason_flagged != long.reason_flagged


def test_convergence_reports_the_status_it_read() -> None:
    """``converged`` and ``stopped`` must read differently beyond the outcome.

    On ``stopped`` the reason also has to carry WHY it matters -- AEDT warns and
    proceeds, so a reader needs to know the numbers exist but may be wrong. That
    half is a disclosure rather than evidence, so it is the one substring pinned
    here, on the Part-6b precedent.
    """
    converged = convergence.evaluate(snapshot())
    stopped = convergence.evaluate(
        snapshot(solve_state=solve_state(convergence_status="stopped"))
    )
    assert converged.reason_flagged != stopped.reason_flagged
    assert "may be wrong" in stopped.reason_flagged
    assert "may be wrong" not in converged.reason_flagged


def test_target_coverage_reports_which_source_supplied_the_target() -> None:
    """THE SAME FREQUENCY FROM TWO SOURCES. Identical outcome, identical value.

    A user who set an intent and then passed an explicit argument cannot otherwise
    tell which one was honoured -- and a ``Finding`` travels without the snapshot
    beside it, so the reason is the only place that can say. This is the same
    recoverability the ``observed_values`` disagreement fields exist for, asserted
    on the field a human actually reads.

    WHAT WOULD HAVE TO CHANGE: the source label being dropped from the sentence.
    """
    from_parameter = target_coverage.evaluate(snapshot(), 2.4e9)
    from_intent = target_coverage.evaluate(snapshot(intent=intent(2.4e9)))
    assert from_parameter.outcome == from_intent.outcome == "pass"
    assert (
        from_parameter.observed_values["target_frequency_hz"]
        == from_intent.observed_values["target_frequency_hz"]
    )
    assert from_parameter.reason_flagged != from_intent.reason_flagged


def test_target_coverage_reports_the_swept_bounds_it_tested_against() -> None:
    """Same target, same verdict, different sweep -- the reason must differ.

    "2.4 GHz is inside the sweep" is not actionable; "inside a sweep running
    2.3-2.5 GHz" is, because it tells a reader how much margin they have and
    whether the sweep covers what they care about. The bounds are also what makes
    a ``fail`` diagnosable rather than merely negative.

    WHAT WOULD HAVE TO CHANGE: the bounds being dropped. A rewording that still
    reports them passes.
    """
    narrow = target_coverage.evaluate(
        snapshot(solved_data=swept(2.3e9, 2.4e9, 2.5e9)), 2.4e9
    )
    wide = target_coverage.evaluate(
        snapshot(solved_data=swept(1.0e9, 2.4e9, 6.0e9)), 2.4e9
    )
    assert narrow.outcome == wide.outcome == "pass"
    assert narrow.reason_flagged != wide.reason_flagged


def test_target_coverage_distinguishes_its_insufficient_causes() -> None:
    """No target, an empty sweep, and no solved data all yield one outcome.

    Three situations a user resolves three different ways -- supply a frequency,
    re-run the sweep, or solve the design -- so the reason has to separate them.

    WHAT WOULD HAVE TO CHANGE: the three collapsing into one sentence.
    """
    causes = {
        "no target": target_coverage.evaluate(snapshot()),
        "empty sweep": target_coverage.evaluate(
            snapshot(solved_data=empty_solved_data()), 2.4e9
        ),
        "no solved data": target_coverage.evaluate(
            snapshot(solved_data=unavailable("no_solution")), 2.4e9
        ),
    }
    assert {f.outcome for f in causes.values()} == {"insufficient_evidence"}
    reasons = [f.reason_flagged for f in causes.values()]
    assert len(set(reasons)) == 3, reasons


@pytest.mark.parametrize("gate_name", sorted(_GATES))
def test_no_gate_leaves_reason_flagged_empty_or_equal_to_its_outcome(
    gate_name: str,
) -> None:
    """The floor beneath all of the above, over every gate and every arm.

    A reason that is blank, or that merely restates the outcome, carries nothing.
    This is the assertion that would catch a NEW gate shipping without a real
    sentence -- the differential tests above each cover one gate, and a fifth gate
    would slip past all of them.
    """
    for snap in (
        snapshot(),
        snapshot(intent=intent(2.4e9)),
        snapshot(solve_state=solve_state(convergence_status="stopped")),
        snapshot(solve_state=solve_state(entries=[])),
        snapshot(solve_state=unavailable("no_solution")),
        snapshot(solved_data=unavailable("no_solution")),
    ):
        finding = _run(gate_name, snap)
        reason = finding.reason_flagged.strip()
        assert reason, f"{gate_name} left reason_flagged empty"
        assert reason != finding.outcome
        # A real sentence, not a token: the shortest genuine reason in the package
        # is well over this, and a bare status word would not clear it.
        assert len(reason) > 30, f"{gate_name} reason is not a sentence: {reason!r}"
