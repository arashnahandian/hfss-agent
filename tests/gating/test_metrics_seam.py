"""The W-9 -> W-7 seam: gate findings crossing into a rendered metrics result.

THE END-TO-END TEST ADR-30's CONSEQUENCES NAME, and it is buildable today rather
than at Step 3.4. Step 3.4 owns the TOOL composition -- dispatching the solved-data
read and constructing ``SolutionValidityReport`` -- but ``evaluate_gates`` already
returns ``list[Finding]`` and ``compute_metrics`` already accepts one, so the seam
itself is wired and can be crossed in a test with data built here.

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
from gating_helpers import snapshot, solve_state, unavailable

from hfss_agent.contract import (
    CONTRACT_VERSION,
    ComplexSample,
    IntentObject,
    ProvenanceRecord,
    SolvedData,
    Variation,
)
from hfss_agent.contract.tool_io import MetricsComputedWithCaveats
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


def test_the_seam_carries_four_gates_into_a_caveated_metrics_result() -> None:
    """The seam itself: W-9's output is accepted by W-7 unchanged.

    ``MetricsComputedWithCaveats`` rather than ``MetricsComputed`` is the expected
    arm on EVERY real design, because the real adapter reports freshness
    undeterminable unconditionally. That is the consequence of Neda's two rulings
    compounding, and it is asserted here rather than left to be discovered.
    """
    result = _crossed()
    assert result.outcome == "metrics_with_caveats"
    assert result.metrics, "her ruling is that the numbers still appear"
    assert [finding.rule_id for finding in result.qualifying_gates] == [
        "gate.freshness"
    ]


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
