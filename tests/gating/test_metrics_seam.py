"""The W-9 -> W-7 seam: gate findings crossing into a rendered metrics result.

THE END-TO-END TEST ADR-30's CONSEQUENCES NAME, and it is buildable today rather
than at Step 3.4. Step 3.4 owns the TOOL composition -- dispatching the solved-data
read and constructing ``SolutionValidityReport`` -- but ``evaluate_gates`` already
returns ``list[Finding]`` and ``compute_metrics`` already accepts one, so the seam
itself is wired and can be crossed in a test with data built here.

BOTH VERDICTS CROSS IT. The first half of this file crosses into
``MetricsComputedWithCaveats``; the section at the bottom crosses into
``MetricsRefused``, which is the done-bar clause "metrics refuses to compute when a
gate fails" and which nothing verified end to end until it was written. See that
section's own comment for why only ``fail`` -- and not ``not_evaluated`` -- can be
reached from this end.

WHY THIS FILE EXISTS AT ALL, stated because the gap it closes was invisible: at
Step 2.6b Part 6b, adding Neda's user-facing guidance to ``freshness.py`` broke
NOTHING. The full suite stayed green at 1244. ``test_freshness_never_claims_the_
results_are_current`` string-matches ``limitations_and_assumptions``, and nothing
anywhere pinned ``reason_flagged``'s CONTENT -- so her guidance could have been
added, omitted, or paraphrased away and no test would have noticed. A ruling that
reaches a user only by accident is not implemented.

WHY tests/gating AND NOT tests/metrics. The snapshot machinery lives here
(``gating_helpers`` drives the real ``assemble_snapshot``), and ``tests/metrics``
cannot import it: ``tests/gating`` sorts first, so ``gating_helpers`` is on
``sys.path`` when this suite is collected but ``assembly_helpers`` is not yet. A
test that passed for a reason as fragile as collection order would be worse than
no test.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from gating_helpers import matching_entry, snapshot, solve_state, unavailable

from hfss_agent.contract import (
    CONTRACT_VERSION,
    ComplexSample,
    IntentObject,
    ProvenanceRecord,
    SolvedData,
    Variation,
)
from hfss_agent.contract.tool_io import MetricsComputedWithCaveats, MetricsRefused
from hfss_agent.gating import evaluate_gates
from hfss_agent.gating import freshness as freshness_gate
from hfss_agent.metrics import compute_metrics

# HER SENTENCE, WRITTEN OUT INDEPENDENTLY OF THE PRODUCT CONSTANT. Importing
# ``freshness._CURRENCY_NOTICE`` would make this a tautology -- the test would
# agree with whatever the module said, including a paraphrase. This is a second
# source, so changing one word in ``freshness.py`` fails here.
#
# Verbatim from the option Neda chose (ADR-30 dec. 7), with the single typographic
# adaptation recorded at the product constant: her em-dash rendered as ASCII ``--``,
# matching the convention of every other runtime string it is displayed beside.
NEDA_GUIDANCE = (
    "We could not confirm these results are current -- we cannot tell whether "
    "this design was changed after it was solved. Check the Message Manager and "
    "the report icons in the Project Manager before trusting these."
)

# The half of her sentence that is ACTIONABLE -- it names where to look in AEDT.
# Pinned separately because it is the part no wording of ours would have produced,
# and the part most likely to be trimmed by someone shortening the message.
NEDA_ACTIONABLE = (
    "Check the Message Manager and the report icons in the Project Manager "
    "before trusting these."
)


def _provenance() -> ProvenanceRecord:
    """A metric provenance. Built here rather than in ``gating_helpers``: no gate
    constructs one, so it is this file's need and not the gating suite's."""
    return ProvenanceRecord(
        project="patch_antenna",
        design="HFSSDesign1",
        solution_type="DrivenModal",
        setup="Setup1",
        sweep="Sweep1",
        variation=Variation(values={"w": "2mm"}, variation_hash="sha256:seam"),
        expression="dB(S(1,1))",
        reference_impedance=50.0,
        solve_timestamp=datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc),
        # W-9 does not construct this type and does not mint this vocabulary
        # (ADR-30 dec. 16 declined a Literal for it). The value here is the test's
        # own, standing in for what Step 3.4 will derive from the freshness gate.
        freshness_status="not_confirmable",
        snapshot_id="snap-seam",
        contract_version=CONTRACT_VERSION,
        wrapper_version="0.0.0",
    )


def _solved() -> SolvedData:
    return SolvedData(
        frequencies=[2.3e9, 2.4e9, 2.5e9],
        s_parameters={
            "S(1,1)": [
                ComplexSample(real=-0.1, imag=0.0),
                ComplexSample(real=-0.01, imag=0.0),
                ComplexSample(real=-0.2, imag=0.0),
            ]
        },
    )


def _intent() -> IntentObject:
    return IntentObject(
        target_frequency_hz=2.4e9, threshold_type="s11", threshold_value=-10.0
    )


def _crossed(**overrides: object) -> MetricsComputedWithCaveats:
    """One snapshot through BOTH modules, narrowed to the caveated arm.

    The real ``assemble_snapshot`` builds the input, the real ``evaluate_gates``
    judges it, and the real ``compute_metrics`` renders it -- no gate finding is
    hand-built anywhere in this file.
    """
    findings = evaluate_gates(snapshot(**overrides), 2.4e9)
    result = compute_metrics(findings, _solved(), _provenance(), _intent())
    assert isinstance(result, MetricsComputedWithCaveats), result
    return result


def _refused(target_frequency_hz: float, **overrides: object) -> MetricsRefused:
    """The same seam, narrowed to the REFUSING arm, through the same real path.

    Identical construction to ``_crossed`` in every respect but the snapshot shape
    and the target: real ``assemble_snapshot``, real ``evaluate_gates``, real
    ``compute_metrics``. No ``Finding`` is hand-built here either, which is what
    makes the refusal a property of the gates rather than of a fixture.
    """
    findings = evaluate_gates(snapshot(**overrides), target_frequency_hz)
    result = compute_metrics(findings, _solved(), _provenance(), _intent())
    assert isinstance(result, MetricsRefused), result
    return result


def test_the_seam_carries_four_gates_into_a_caveated_metrics_result() -> None:
    """The seam itself: W-9's output is accepted by W-7 unchanged.

    ``MetricsComputedWithCaveats`` rather than ``MetricsComputed`` is the expected
    arm on EVERY real design, because the real adapter reports freshness
    undeterminable unconditionally. That is the consequence of Neda's two rulings
    compounding, and it is asserted here rather than left to be discovered.

    FOUR-NESS IS NOW ASSERTED RATHER THAN MERELY NAMED, and the name is kept
    because asserting it is the right fix. Measured: deleting ``target_coverage``
    from ``evaluate_gates`` left this test GREEN, because ``qualifying_gates``
    carries only the HEDGERS and freshness is the only one -- so every assertion
    below the first three was blind to how many gates had actually crossed. The
    alternative, renaming the test to what it checked, would have deleted the one
    place in the repo where the seam's gate COUNT is examined end to end: W-7
    states outright that it "does not itself confirm that this is the complete set
    of four", so the aggregator on this side is the only thing that can, and this
    is where that is checked.
    """
    result = _crossed()
    assert result.outcome == "metrics_with_caveats"
    assert result.metrics, "her ruling is that the numbers still appear"
    assert [finding.rule_id for finding in result.qualifying_gates] == [
        "gate.freshness"
    ]

    # WHERE THE OTHER THREE ARE VISIBLE. ``MetricsComputedWithCaveats`` carries the
    # hedgers alone in a typed field, so the rendered gate sentence is the only
    # place the COMPLETE supplied set appears -- which is exactly why W-7 renders
    # the count and the rule ids there rather than leaving them to the status
    # string. A short gate list makes the first assertion read "1 of 3".
    text = result.template_text
    assert "1 of 4 gate result(s) supplied did NOT pass" in text
    for rule_id in (
        "gate.solution_exists",
        "gate.convergence",
        "gate.freshness",
        "gate.target_coverage",
    ):
        assert rule_id in text, f"{rule_id} did not cross the seam"


def test_nedas_guidance_reaches_what_a_user_reads() -> None:
    """THE POINT OF THIS FILE. Her words, in the rendered result, verbatim.

    Not "a freshness caveat appears" -- her SENTENCE appears. ADR-30 dec. 22's
    rule is that a domain expert's wording is what a domain reader understands,
    and it applies in both directions: paraphrasing her guidance into house
    vocabulary would lose the only part that tells an engineer where to look.
    """
    text = _crossed().template_text
    assert NEDA_GUIDANCE in text
    assert NEDA_ACTIONABLE in text


def test_her_guidance_is_in_the_caveat_block_not_buried_below_the_numbers() -> None:
    """POSITION AND CONTENT TOGETHER, which is what her option actually specified.

    Part 6 shipped the position with our wording; Part 6b shipped her wording. A
    test asserting only presence would pass with the guidance rendered after the
    metric lines -- which is the arrangement she declined.
    """
    lines = _crossed().template_text.splitlines()
    header = next(
        index
        for index, line in enumerate(lines)
        if line.startswith("Metrics for project")
    )
    guidance = next(
        index for index, line in enumerate(lines) if NEDA_ACTIONABLE in line
    )
    assert guidance < header, "the guidance must precede the metrics header"
    values = next(
        index for index, line in enumerate(lines) if line.startswith("Computed from")
    )
    assert guidance < values, "the guidance must precede the numbers"


@pytest.mark.parametrize(
    "overrides",
    [
        {"solve_state": solve_state(determinable=False)},
        {"solve_state": solve_state(determinable=True)},
        {"solve_state": unavailable("not_exposed_by_pyaedt")},
        {"solve_state": unavailable("no_solution")},
    ],
    ids=[
        "real-adapter-shape",
        "fake-shape",
        "absent-not-exposed",
        "absent-no-solution",
    ],
)
def test_both_freshness_arms_carry_her_guidance(overrides: dict[str, object]) -> None:
    """BOTH ARMS, because the gate has two and only one was obvious.

    The solve-state arm is the one a reader thinks of. The absence arm reaches a
    user just as often -- a never-solved design is the ordinary case (ADR-28) --
    and its wording was written separately, so nothing but this parametrisation
    keeps the two from drifting apart.
    """
    finding = freshness_gate.evaluate(snapshot(**overrides))
    assert finding.outcome == "insufficient_evidence"
    assert NEDA_GUIDANCE in finding.reason_flagged


def test_the_guidance_lives_in_the_field_the_caveat_block_renders() -> None:
    """WHICH FIELD, pinned -- because three of the Finding's fields do not travel.

    Traced rather than assumed: W-7's caveat block renders ``rule_id``,
    ``outcome`` and ``reason_flagged``, and nothing else. Moving her guidance to
    ``limitations_and_assumptions`` would leave every assertion about the gate
    green while the user saw none of it, which is precisely the state Part 6b
    found and fixed.
    """
    finding = freshness_gate.evaluate(snapshot())
    assert NEDA_GUIDANCE in finding.reason_flagged
    # And it is NOT duplicated into the field that does not travel -- two homes for
    # one fact is the drift this codebase refuses everywhere else.
    assert NEDA_ACTIONABLE not in finding.limitations_and_assumptions


# --- the refusing arm: the same seam, the opposite verdict --------------------
#
# WHY THIS SECTION EXISTS, and it is the same shape of gap the file's own docstring
# describes one arm over. Step 2.6b's done-bar claims metrics "refuses to compute
# when a gate fails, VERIFIED END TO END", and nothing verified it end to end:
# every ``MetricsRefused`` assertion in the repo lives in ``tests/metrics``, which
# HAND-BUILDS its ``Finding``s and never imports ``hfss_agent.gating`` at all,
# while the one seam test here hard-asserted the caveated arm. A hand-built finding
# proves the ROUTER refuses an outcome; it cannot prove any real gate ever PRODUCES
# that outcome. Each half was being tested against the other's absence.
#
# ONLY ``fail`` IS REACHABLE HERE, AND THE SCOPE LIMIT IS STATED RATHER THAN LEFT
# TO BE INFERRED. ``_route_gates``' refusing remainder is ``FindingOutcome`` minus
# ``pass`` minus ``GATE_OUTCOMES_THAT_QUALIFY_COMPUTATION`` -- exactly ``fail`` and
# ``not_evaluated``. NO GATE IN THIS PACKAGE EMITS ``not_evaluated`` ON ANY INPUT:
# ``test_not_evaluated_is_unreachable_across_every_gate_and_input_shape``
# enumerates that over every snapshot shape the suite can build, and
# ``target_coverage`` -- the last candidate -- emits ``insufficient_evidence``
# instead under Neda's ruling. So the ``not_evaluated`` limb CANNOT be crossed from
# this end without hand-building a Finding, which is precisely what this file
# refuses to do, and asserting it here would mean asserting it against a fixture.
# It is covered where it can be covered honestly:
# ``tests/metrics/test_metrics_assembly.py``'s
# ``test_a_failing_or_unrun_gate_still_refuses`` parametrises both members over
# constructed findings. What THIS section adds is the half that was missing --
# that a real gate reaches the refusal at all -- and the day E-2 or a fifth gate
# gives ``not_evaluated`` a producer, its shape belongs in the table below.

# THE TWO REAL ROUTES TO A ``fail``, one per gate that can emit one. Both are
# ordinary designs rather than contrived ones: a selected setup that was never
# solved, and a question asked at a frequency the sweep does not reach.
_REFUSING_ROUTES = {
    "solution-does-not-exist": (
        "gate.solution_exists",
        2.4e9,
        {"solve_state": solve_state(entries=[matching_entry(exists=False)])},
    ),
    "target-outside-the-sweep": ("gate.target_coverage", 9.9e9, {}),
}


@pytest.mark.parametrize("route", sorted(_REFUSING_ROUTES))
def test_a_real_failing_gate_refuses_metrics_across_the_seam(route: str) -> None:
    """THE DONE-BAR CLAUSE, AS BEHAVIOUR: gates fail, so no numbers are produced.

    The refusing gate is identified by ``rule_id`` and its outcome is asserted to
    be ``fail`` specifically -- not merely "non-passing" -- because
    ``insufficient_evidence`` is also non-passing and QUALIFIES rather than
    refuses. A test that accepted any non-passing outcome here would still pass on
    the day a routing bug moved the ``fail`` into the caveated arm.
    """
    rule_id, target, overrides = _REFUSING_ROUTES[route]
    result = _refused(target, **overrides)

    assert result.outcome == "gates_failed"
    failed = [
        finding for finding in result.failing_gates if finding.rule_id == rule_id
    ]
    assert len(failed) == 1, [f.rule_id for f in result.failing_gates]
    assert failed[0].outcome == "fail"
    # "refused, but here are numbers anyway" is UNCONSTRUCTIBLE -- the arm has no
    # ``metrics`` field at all, which is the structural half of the same claim.
    assert not hasattr(result, "metrics")


@pytest.mark.parametrize("route", sorted(_REFUSING_ROUTES))
def test_the_refusal_reports_no_metric_value_of_any_kind(route: str) -> None:
    """No numbers reach the RENDERED text either, not just the typed field.

    ``template_text`` is what a user reads, and it is the one place a computed
    value could survive a refusal -- the refusal path is reached before any formula
    runs, so a metric name appearing here would mean the routing had been
    bypassed. Names rather than digits: the refusal text legitimately quotes the
    frequencies a gate's ``reason_flagged`` names, so asserting "no digits" would
    be asserting against the disclosure that makes the refusal useful.
    """
    rule_id, target, overrides = _REFUSING_ROUTES[route]
    text = _refused(target, **overrides).template_text
    for metric_name in (
        "s11_min",
        "resonant_frequency",
        "minus_10db_bandwidth",
        "s11_at_target",
        "vswr_at_target",
        "impedance_at_target",
    ):
        assert metric_name not in text, f"{metric_name} survived a refusal"
    assert "no metrics were computed and no numbers are reported" in text


def test_one_input_decides_between_numbers_and_a_refusal() -> None:
    """THE DIFFERENTIAL, without which either arm could be a fixture artefact.

    Same solved data, same provenance, same intent, same snapshot -- the ONLY thing
    that differs between these two calls is the target frequency handed to the
    gates. One lands inside the swept range and numbers are returned under Neda's
    caveat; one lands outside it and the whole result is a refusal. That is what
    shows the refusal is caused by the GATE OUTCOME rather than by anything else in
    the fixture, which neither arm asserted on its own.
    """
    computed = _crossed()  # target 2.4e9, inside the 2.3-2.5 GHz sweep
    refused = _refused(9.9e9)  # the same snapshot, asked about 9.9 GHz

    assert computed.metrics, "the covered target must still produce numbers"
    assert refused.outcome == "gates_failed"
    # And the refusal names the gate that changed, not some unrelated one.
    assert [finding.rule_id for finding in refused.failing_gates if
            finding.outcome == "fail"] == ["gate.target_coverage"]


def test_refusal_wins_over_qualification_and_the_hedger_still_travels() -> None:
    """BOTH non-passing gates arrive, which is the documented refusal behaviour.

    ``_route_gates`` echoes EVERY non-passing gate into ``failing_gates`` when it
    refuses, not only the refusing ones -- seeing the ``fail`` without also seeing
    that freshness could not vouch for currency tells a reader less. Freshness
    returns ``insufficient_evidence`` on every real design, so this pairing is the
    ordinary case rather than a contrived one, and it is the case where the
    field-name misnomer the contract admits to is actually visible.

    Her guidance still travels -- but as a reported gate outcome, NOT as a caveat
    over numbers, because there are none to caveat.
    """
    result = _refused(9.9e9)
    outcomes = {
        finding.rule_id: finding.outcome for finding in result.failing_gates
    }
    assert outcomes == {
        "gate.target_coverage": "fail",
        "gate.freshness": "insufficient_evidence",
    }
    assert NEDA_GUIDANCE in result.template_text
    assert "READ THIS BEFORE TRUSTING THE NUMBERS BELOW" not in result.template_text
