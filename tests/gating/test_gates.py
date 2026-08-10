"""W-9 gate semantics: every reachable outcome, under both arms of solve_state.

TWO OF THE FOUR GATES ARE BUILT HERE. ``freshness`` is deliberately absent: its
``pass`` condition turns on a reading of ``FreshnessEvidence.determinable`` that
the type's own docstring does not support, and that conflict was escalated rather
than papered over. ``target_coverage`` is Part 4, blocked on a product ruling for
its no-target case. Neither absence is an oversight and neither is worked around
here.

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
    matching_entry,
    round_tripped,
    snapshot,
    solve_state,
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
    SolveDataUnavailableReason,
)
from hfss_agent.gating import common as gating_common
from hfss_agent.gating import convergence, freshness, solution_exists

# The three built gates, by the name their rule_id and calculation_ref encode.
# Written as a mapping here rather than imported from the package so a test
# comparing names is comparing against a second source. Gate 4
# (``target_coverage``) is Part 4; ``test_every_gate_module_in_the_package_is_
# under_test`` is what forces this to move when it lands.
_GATES = {
    "solution_exists": solution_exists.evaluate,
    "convergence": convergence.evaluate,
    "freshness": freshness.evaluate,
}


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
    """The behavioural half: the gate really does emit what the table says."""
    snap = snapshot(solve_state=unavailable(reason))
    finding = _GATES[gate_name](snap)
    assert finding.outcome == _ABSENCE_MAPPING[gate_name][reason]
    assert finding.observed_values["reason"] == reason
    assert finding.applicability.held is False
    assert finding.inspected == ["solve_state.reason", "solve_state.limitation"]


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
    return [evaluate(snap) for evaluate in _GATES.values()]


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
    assert _GATES[gate_name](snapshot()).severity == "info"


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
    finding = _GATES[gate_name](snapshot())
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


def _snapshot_for_arm(solve: str | None) -> DesignSnapshot:
    """The solved arm, or the absence arm under a reason that is not a verdict.

    ``not_exposed_by_pyaedt`` rather than ``no_solution``, deliberately: the
    latter is the one reason that yields a ``fail`` on one of the two gates, which
    would make an arm-shape test also depend on a verdict mapping.
    """
    if solve is None:
        return snapshot()
    return snapshot(solve_state=unavailable("not_exposed_by_pyaedt"))


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
    snap = _snapshot_for_arm(solve)
    finding = _GATES[gate_name](snap)
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
        finding = _GATES[gate_name](snap)
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
    snap = _snapshot_for_arm(solve)
    provenance = _GATES[gate_name](snap).provenance
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
    assert _GATES[gate_name](snapshot()).provenance.engine_version is None


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
    finding = _GATES[gate_name](snapshot())
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
        conditions = _GATES[gate_name](snap).applicability.conditions
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
        path.stem
        for path in package_dir.glob("*.py")
        if path.stem not in {"__init__", "common"}
    }
    assert modules == set(_GATES), (
        "every module in hfss_agent.gating that is not __init__ or common is a "
        "gate and must be registered in this suite"
    )
    for name in modules:
        module = importlib.import_module(f"{gating.__name__}.{name}")
        assert callable(module.evaluate)
