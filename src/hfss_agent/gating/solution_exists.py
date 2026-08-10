"""Gate 1 of 4: does a solution exist for the SELECTED setup/sweep/variation?

Keyed to the selection, not to the design (``SolutionExists``' own docstring):
"the design as a whole having *some* solution is not the question". So this gate
matches ``solve_state.solution_exists`` against ``selection`` and reads the
matched entry's ``exists`` flag; a populated list with nothing matching is not an
answer.

TWO OF THE FIVE OUTCOMES CANNOT BE EMITTED HERE, and each absence is deliberate.
This prose is the only record of them -- an unlisted omission is
indistinguishable from an unconsidered one (ADR-29 dec. 4):

  * ``warning`` -- CANNOT EMIT, because ``SolutionExists.exists`` is a ``bool``
    and there is no hedged state between "a solution exists" and "it does not".
    The consequence is not cosmetic: ``warning`` is a member of
    ``GATE_OUTCOMES_THAT_QUALIFY_COMPUTATION``, so emitting one would let W-7
    compute numbers from a solve this gate had just declined to confirm existed.
  * ``not_evaluated`` -- CANNOT EMIT, because this gate has no precondition that
    can be absent. ``selection`` is required on every ``DesignSnapshot`` and
    ``solve_state`` is present in one arm or the other, so there is always
    something to read. Contrast the target-coverage gate, which genuinely can be
    handed no target at all; that is the one gate for which ``not_evaluated`` is
    reachable.

THE ABSENCE-ARM MAPPING IS EXHAUSTIVE OVER THE PINNED LITERAL SET, BY LOOKUP AND
WITH NO DEFAULT -- see ``_ABSENCE_OUTCOMES``.
"""

from __future__ import annotations

from hfss_agent.contract import (
    DesignSnapshot,
    Finding,
    FindingOutcome,
    SolveDataUnavailable,
    SolveState,
)
from hfss_agent.gating.common import (
    CLASSIFICATION_BY_OUTCOME,
    GATE_SEVERITY,
    GATE_SOURCE,
    applicability,
    finding_id,
    gate_provenance,
)

GATE_NAME = "solution_exists"
RULE_ID = f"gate.{GATE_NAME}"
CALCULATION_REF = f"hfss_agent.gating.{GATE_NAME}:evaluate"

# ``rule_version`` MOVES WHEN THIS GATE'S DECISION LOGIC WOULD PRODUCE A DIFFERENT
# ``outcome`` FOR A SNAPSHOT IT PREVIOUSLY JUDGED. Major on a changed outcome for
# an existing input; minor on a newly-reachable outcome for an input previously
# unhandled; patch for wording of ``reason_flagged`` or ``template_text`` alone.
# DELIBERATELY NOT TIED to the package version or to ``CONTRACT_VERSION``: a gate
# is a rule, ``Finding.rule_version`` is documented as the version of the rule that
# PRODUCED a finding, and tying it to a release would make every release claim
# every gate had changed. ``"1.0.0"`` is the starting value both existing fixtures
# already use.
RULE_VERSION = "1.0.0"

# Verbatim from ``tests/schemas/conftest.py``'s gate fixture, which fixed this
# wording before any gate existed. Following it rather than rephrasing keeps the
# fixture and the producer from drifting.
RULE_PURPOSE = "Confirms a solution exists for the selected setup/sweep/variation."

LIMITATIONS = (
    "Assumes PyAEDT reported solution presence accurately for the selection. "
    "Reports on the one setup/sweep/variation the session selected; the design "
    "as a whole having some other solution is not the question this gate asks."
)

# EXHAUSTIVE OVER ``SolveDataUnavailableReason``, AS A LOOKUP WITH NO DEFAULT.
# A missing member raises ``KeyError`` loudly rather than falling through to a
# permissive branch -- there is no type checker in this project, so an ``else``
# would be the only thing standing between a new Literal member and a silently
# wrong outcome. ``test_absence_mapping_covers_every_reason`` pins this table
# against ``get_args`` by SET EQUALITY in both directions.
#
# ``no_solution`` IS THE ONLY MEMBER THAT FAILS, and it is the only one that is a
# NEGATIVE OBSERVATION rather than an absent one: the adapter's "no solved data"
# refusal means it looked and there was none, which is exactly this gate's
# question answered. The other three mean the wrapper could not obtain the fact,
# which is not an answer.
#
# SCOPED UNREACHABILITY NOTE, AND IT DOES NOT GENERALISE. ``no_solution`` is not
# reachable ON THE FIELD ``solve_state`` today: ``contract/common.py`` records that
# a never-solved design's ``solve_state`` comes back ``not_exposed_by_pyaedt``,
# because the adapter's convergence read refuses before ``setup.is_solved`` is ever
# consulted. THAT STATEMENT IS SCOPED TO THIS ONE LITERAL ON THIS ONE FIELD. It
# does NOT extend to ``no_solution`` on ``solved_data`` (which IS reachable, via the
# "no solved data" refusal, and is the target-coverage gate's input), and it does
# NOT extend to the other three members, all of which are reachable on both fields.
# No code below may assume any branch here is dead, and the ``fail`` arm is
# implemented and tested exactly as if it were live.
_ABSENCE_OUTCOMES: dict[str, FindingOutcome] = {
    "no_solution": "fail",
    "not_exposed_by_pyaedt": "insufficient_evidence",
    "not_found_in_design": "insufficient_evidence",
    "unrecognised_by_wrapper": "insufficient_evidence",
}


def evaluate(snapshot: DesignSnapshot) -> Finding:
    """Judge whether the selected combination has a solution.

    Takes the WHOLE snapshot and narrows internally, rather than receiving a
    pre-narrowed arm. The provenance argument is what decides it: every gate must
    stamp nine fields sourced from ``selection``, ``snapshot_id``,
    ``contract_version`` and ``environment`` -- none of which live on either arm --
    so the snapshot has to be passed regardless. Narrowing once in the aggregator
    would mean passing BOTH the narrowed arm and the snapshot, which is strictly
    more parameters for no gain. The three gates that narrow ``solve_state`` also
    map its reasons DIFFERENTLY, so the repeated ``isinstance`` is not duplicated
    logic: it is the one place they legitimately disagree.

    Args:
        snapshot: the artifact to judge. Never mutated; nothing is fetched.

    Returns:
        One ``Finding`` with ``source="gate"``. Never raises for a well-formed
        snapshot -- a state this gate cannot judge becomes an outcome, not an
        exception.
    """
    solve_state = snapshot.solve_state
    if isinstance(solve_state, SolveState):
        return _from_solve_state(snapshot, solve_state)
    return _from_absence(snapshot, solve_state)


def _from_solve_state(snapshot: DesignSnapshot, solve_state: SolveState) -> Finding:
    """The arm where a solve state was read, so the flags can be matched."""
    selection = snapshot.selection
    # Full ``Variation`` equality, not hash-only: ``Variation`` is a pydantic model
    # so ``==`` compares both fields, and its docstring states equality is the one
    # operation the hash supports. Comparing the whole key is the stricter reading
    # and costs nothing -- the real adapter builds each entry FROM this selection.
    matching = [
        entry
        for entry in solve_state.solution_exists
        if entry.setup == selection.setup
        and entry.sweep == selection.sweep
        and entry.variation == selection.variation
    ]
    observed: dict[str, object] = {
        "entries_reported": len(solve_state.solution_exists),
        "matching_entries": len(matching),
    }
    inspected = [
        "solve_state.solution_exists",
        "selection.setup",
        "selection.sweep",
        "selection.variation",
    ]

    # NOT EXACTLY ONE MATCH -> insufficient_evidence, never ``fail``. An empty or
    # non-matching list means the adapter reported on nothing relevant to the
    # selection: that is the ABSENCE OF AN OBSERVATION, not a negative one, and
    # ``fail`` would assert "there is no solution here" on evidence we do not hold.
    # This is the same distinction ADR-28 draws structurally between a validator
    # that RAN and reported nothing and one that could not run.
    #
    # ``!= 1`` rather than ``not matching`` so a DUPLICATE match is caught too --
    # two entries claiming the same selection disagree about something, and picking
    # the first would hide it.
    #
    # NEITHER ADAPTER CAN PRODUCE AN EMPTY LIST: the real one builds a
    # single-element list from the selection itself, and the fake hard-codes one
    # entry. The fake CAN produce a mismatch, because its setup/sweep names are
    # hard-coded rather than derived -- so a test that selects anything else lands
    # here. That is the second reason not to ``fail``: it would surface a fixture
    # mistake as a product finding about the user's design.
    if len(matching) != 1:
        conditions: dict[str, object] = {
            "solve_state_readable": True,
            "selection_matched": False,
        }
        return _build(
            snapshot,
            outcome="insufficient_evidence",
            inspected=inspected,
            observed_values=observed,
            reason_flagged=(
                f"The solve state reported {len(solve_state.solution_exists)} "
                f"solution-existence flag(s), of which {len(matching)} match the "
                "selected setup/sweep/variation. Exactly one match is needed to "
                "read a flag for this selection, so no determination was made."
            ),
            conditions=conditions,
        )

    exists = matching[0].exists
    observed["exists"] = exists
    return _build(
        snapshot,
        outcome="pass" if exists else "fail",
        inspected=inspected,
        observed_values=observed,
        reason_flagged=(
            "A solution exists for the selected combination."
            if exists
            else "No solution exists for the selected setup/sweep/variation."
        ),
        conditions={"solve_state_readable": True, "selection_matched": True},
    )


def _from_absence(
    snapshot: DesignSnapshot, solve_state: SolveDataUnavailable
) -> Finding:
    """The arm where no solve state was read; the reason decides the outcome."""
    outcome = _ABSENCE_OUTCOMES[solve_state.reason]
    return _build(
        snapshot,
        outcome=outcome,
        # Only the two absence fields were consumed by the JUDGMENT. ``selection``
        # is read for the provenance stamp, which is a different job and is not
        # what ``inspected`` records.
        inspected=["solve_state.reason", "solve_state.limitation"],
        observed_values={
            "reason": solve_state.reason,
            "limitation": solve_state.limitation,
        },
        reason_flagged=(
            "The snapshot carries no solve state, and the reason reported is "
            f"{solve_state.reason!r}: {solve_state.limitation}"
        ),
        conditions={"solve_state_readable": False, "selection_matched": False},
    )


def _build(
    snapshot: DesignSnapshot,
    *,
    outcome: FindingOutcome,
    inspected: list[str],
    observed_values: dict[str, object],
    reason_flagged: str,
    conditions: dict[str, object],
) -> Finding:
    """Assemble the sixteen required fields; only five vary between the arms.

    ``held`` is derived by ``common.applicability`` rather than passed in; see that
    function for the rule and for why a gate does not get to assert it. This gate
    is the source of one of the two combinations that rule exists to explain: on
    the ``no_solution`` absence arm the outcome is ``fail`` while ``held`` is
    ``False``. Both are true -- the solve state could not be read, so the gate's
    applicability conditions did not hold, AND the reason it could not be read is
    itself the answer to this gate's question.
    """
    return Finding(
        finding_id=finding_id(GATE_NAME, outcome),
        source=GATE_SOURCE,
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        rule_purpose=RULE_PURPOSE,
        inspected=inspected,
        observed_values=observed_values,
        calculation_ref=CALCULATION_REF,
        reason_flagged=reason_flagged,
        outcome=outcome,
        classification=CLASSIFICATION_BY_OUTCOME[outcome],
        severity=GATE_SEVERITY,
        limitations_and_assumptions=LIMITATIONS,
        applicability=applicability(conditions),
        provenance=gate_provenance(snapshot),
        # The ``[gate] <name>: <outcome>`` prefix is fixed by both existing
        # fixtures; the evidence sentence after it is this gate's own. Rendered
        # from data the finding already carries, so the text and the typed fields
        # cannot disagree.
        template_text=f"[gate] {GATE_NAME}: {outcome}. {reason_flagged}",
    )
