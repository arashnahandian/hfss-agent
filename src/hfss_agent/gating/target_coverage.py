"""Gate 4 of 4: does the target frequency lie inside the solved frequency range?

THE ONLY GATE TAKING A SECOND PARAMETER, and the only one reading ``solved_data``
rather than ``solve_state``. Both differences are real rather than incidental: the
question this gate asks is about a frequency the CALLER names, tested against the
sweep that was actually solved, and neither of those lives where the other three
gates look.

ONE OF THE FIVE OUTCOMES CANNOT BE EMITTED HERE (ADR-29 dec. 4 -- an unlisted
omission is indistinguishable from an unconsidered one):

  * ``warning`` -- CANNOT EMIT. Coverage is containment on a closed interval and
    has no hedged state: a frequency is inside ``[min, max]`` or it is not. The two
    tempting candidates are both inventions. "Near the edge" would need a margin,
    and a manufactured cutoff is exactly what ADR-30 dec. 6 refuses for delta-S --
    no one has specified one and this package does not own the rule. "Falls between
    two samples" is not a hedge at all: interpolation is the ordinary case, which
    ``sparams`` already handles, and the sweep's step size is disclosed in this
    gate's limitations rather than being converted into a verdict.

``not_evaluated`` IS ALSO UNREACHABLE HERE, and this gate is why the package-wide
record of that exists -- see ``common.NOT_EVALUATED_IS_UNREACHABLE_IN_GATING``.
This was the last candidate: no target from either source is the one case in the
whole gate set where "the check did not run" was the honest English. Neda ruled it
shows numbers, so it emits ``insufficient_evidence``. The reasoning is in that
constant rather than here, because the fact it records is about all four gates.

NEDA'S RULING GOVERNS THE NO-TARGET CASE. She was given two options and chose the
first, verbatim: "she believes option A is the fine call here." Option A as she
read it:

    "Show the numbers we can compute -- deepest match, where it resonates,
    bandwidth -- and say plainly that we couldn't check anything at a specific
    frequency because none was given."

``insufficient_evidence`` is what implements that: it is a member of
``GATE_OUTCOMES_THAT_QUALIFY_COMPUTATION``, so W-7 still computes the three
whole-sweep metrics (``s11_min``, ``resonant_frequency``, ``minus_10db_bandwidth``)
and attaches this finding as the caveat. The four at-target metrics are omitted
separately by W-7's own ``NO_INTENT_REASON``, which already refuses to compute
against an assumed frequency. So her two clauses land in two different places and
both are honoured.

WHY NOT ``not_evaluated`` PLUS A WIDER ALLOW-LIST -- the load-bearing call of this
step, recorded because the alternative is the one a reader would reach for:

  * WIDENING IS GLOBAL AND ONLY ONE PRODUCER NEEDS IT. ADR-30 dec. 10 excluded
    ``not_evaluated`` because "a gate that did not run produced no evidence, so
    there is nothing for it to qualify a number WITH, and listing it as a caveat
    would assert that we looked", and because "an unruled state refuses by
    default". Neda ruled on ONE case of that. Adding ``not_evaluated`` to the
    allow-list would license EVERY future gate's ``not_evaluated`` to permit
    numbers, contained only by "no other gate emits one today" -- the
    unreachable-because-X reasoning that already bit this build once.
  * THE SHAPE IS ALREADY ESTABLISHED, TWICE. An applicability condition does not
    hold, so no determination is reachable, so ``insufficient_evidence``. That is
    exactly what ``solution_exists`` does when no flag matches the selection, and
    what ``freshness`` does when the determination is unreadable. This gate is the
    third instance of a pattern, not a new one -- and unlike freshness, whose
    blocking condition is a structural constant, this one is an ordinary per-input
    check that genuinely holds whenever a target is supplied.
  * IT COSTS NO VERSION EVENT. Widening ``GATE_OUTCOMES_THAT_QUALIFY_COMPUTATION``
    is breaking for a tool-surface consumer, so the PACKAGE version would move
    mid-step. ``CONTRACT_VERSION`` would not -- ``tool_io`` is not reachable FROM
    ``DesignSnapshot`` or ``Finding`` (ADR-30 dec. 15) -- but a package bump for a
    change one gate could make locally is the wrong trade.

TARGET PRECEDENCE: THE EXPLICIT PARAMETER WINS, then ``snapshot.intent``. The
parameter is a per-call question and is the more specific expression of what the
caller wants to know; an intent is a standing preference. A user asking "is 3 GHz
inside the sweep?" about a design whose stated intent is 2.4 GHz is asking an
ordinary exploratory question, not stating a contradiction, so a disagreement does
not refuse. BOTH VALUES TRAVEL whenever both exist, so the disagreement is
recoverable from the finding alone -- a ``Finding`` is rendered without the
snapshot beside it, and a reader who cannot see the intent cannot otherwise tell
that the parameter overrode one.

THE ABSENCE ARM IS ``solved_data``'s, NOT ``solve_state``'s. The two are
independent fields that happen to share the ``SolveDataUnavailable`` type, and
nothing may assume a gate's absence row carries over from a sibling: this gate's
row is derived from what ``solved_data`` can be missing for, not copied.
"""

from __future__ import annotations

from hfss_agent.contract import (
    DesignSnapshot,
    Finding,
    FindingOutcome,
    SolveDataUnavailable,
    SolvedData,
)
from hfss_agent.gating.common import (
    CLASSIFICATION_BY_OUTCOME,
    GATE_SEVERITY,
    GATE_SOURCE,
    applicability,
    finding_id,
    gate_provenance,
)

GATE_NAME = "target_coverage"
RULE_ID = f"gate.{GATE_NAME}"
CALCULATION_REF = f"hfss_agent.gating.{GATE_NAME}:evaluate"

# See ``solution_exists.RULE_VERSION`` for what moves this.
RULE_VERSION = "1.0.0"

RULE_PURPOSE = (
    "Confirms the target frequency lies inside the solved frequency range."
)

LIMITATIONS = (
    "The bounds are the lowest and highest SWEPT frequencies, so coverage is "
    "bounded by the sweep's extent and not by its step size. A target inside the "
    "range but between two samples IS covered; the value at it is interpolated by "
    "the metric formulas, and this gate makes no judgment about interpolation "
    "distance -- no edge margin is applied, because none has been specified and "
    "inventing one would manufacture rule content. A target is never assumed or "
    "defaulted: when none is supplied by the caller and none is carried by the "
    "design intent, this gate reports that it could not check rather than "
    "checking against a guess."
)

# THE TWO SOURCE LABELS. Recorded in ``observed_values`` so a reader can tell WHICH
# frequency was tested without the snapshot beside them -- the parameter and the
# intent name the same quantity, and a finding that reported only the number would
# leave a caller unable to tell whether their explicit argument had been honoured.
SOURCE_PARAMETER = "parameter"
SOURCE_INTENT = "intent"

# EXHAUSTIVE OVER ``SolveDataUnavailableReason``, AS A LOOKUP WITH NO DEFAULT.
# DERIVED FOR ``solved_data``, NOT COPIED FROM A SIBLING. The three other gates
# narrow ``solve_state``; this one narrows ``solved_data``, and the two are
# independent fields that merely share an absence TYPE. Every member maps to
# ``insufficient_evidence`` here, and the reason it is uniform is different from
# the reason freshness's row is uniform:
#
# There is no swept frequency range to test containment against under ANY of the
# four reasons, so no verdict is reachable -- and crucially, none of them is a
# negative observation about COVERAGE. ``no_solution`` is the one to check rather
# than assume: on ``solution_exists`` it means "the adapter looked and there is no
# solution", which IS that gate's question answered, so it fails there. Here it
# means only that no series arrived; it says nothing about whether a frequency
# would have been inside a range that does not exist. Mapping it to ``fail`` would
# report "your target is outside the sweep" when no sweep was read at all.
_ABSENCE_OUTCOMES: dict[str, FindingOutcome] = {
    "no_solution": "insufficient_evidence",
    "not_exposed_by_pyaedt": "insufficient_evidence",
    "not_found_in_design": "insufficient_evidence",
    "unrecognised_by_wrapper": "insufficient_evidence",
}


def evaluate(
    snapshot: DesignSnapshot, target_frequency_hz: float | None = None
) -> Finding:
    """Judge whether the target frequency is inside the solved sweep.

    THE SECOND PARAMETER IS THIS GATE'S ALONE, and the three siblings deliberately
    did NOT grow an ignored one for uniformity. A parameter a function never reads
    is the "declared-but-empty slot [that] still asserts the slot exists" shape
    ``NativeValidationProvenance`` refuses in as many words and ADR-30 dec. 3
    generalises: a caller writing ``convergence.evaluate(snap, target)`` would
    reasonably expect the argument to matter, and nothing in the signature would
    tell them it does not. The cost lands entirely in the caller --
    ``evaluate_gates`` dispatches this one explicitly -- which is one named place
    rather than three silent lies.

    Args:
        snapshot: the artifact to judge. Never mutated; nothing is fetched.
        target_frequency_hz: the frequency to test, if the caller names one.
            Takes precedence over ``snapshot.intent.target_frequency_hz``; see the
            module docstring for why, and for what happens when they disagree.

    Returns:
        One ``Finding`` with ``source="gate"``. Never raises for a well-formed
        snapshot -- a state this gate cannot judge becomes an outcome.
    """
    intent_target = (
        None if snapshot.intent is None else snapshot.intent.target_frequency_hz
    )
    # PRECEDENCE, IN ONE EXPRESSION so it cannot drift between the branches below.
    # ``is not None`` rather than truthiness: 0.0 Hz is a nonsensical target but it
    # is a SUPPLIED one, and silently falling through to the intent because the
    # caller passed a falsy float would be the wrong kind of helpful.
    if target_frequency_hz is not None:
        target, source = target_frequency_hz, SOURCE_PARAMETER
    elif intent_target is not None:
        target, source = intent_target, SOURCE_INTENT
    else:
        target, source = None, None

    solved_data = snapshot.solved_data
    if isinstance(solved_data, SolvedData):
        return _from_solved_data(
            snapshot, solved_data, target, source, intent_target
        )
    return _from_absence(snapshot, solved_data, target, source, intent_target)


def _target_evidence(
    target: float | None, source: str | None, intent_target: float | None
) -> dict[str, object]:
    """The target half of ``observed_values``, shared by both arms.

    ``intent_target_frequency_hz`` TRAVELS WHENEVER BOTH SOURCES EXIST, not only
    when they disagree. Recording it only on disagreement would make the field's
    ABSENCE ambiguous -- a reader could not tell "there was no intent" from "the
    intent agreed" -- and the first is a fact about the design while the second is
    a fact about the call.
    """
    evidence: dict[str, object] = {}
    if target is not None:
        evidence["target_frequency_hz"] = target
        evidence["target_source"] = source
        if source == SOURCE_PARAMETER and intent_target is not None:
            evidence["intent_target_frequency_hz"] = intent_target
    return evidence


def _from_solved_data(
    snapshot: DesignSnapshot,
    solved_data: SolvedData,
    target: float | None,
    source: str | None,
    intent_target: float | None,
) -> Finding:
    """The arm where a series was read. Three outcomes are reachable here."""
    frequencies = solved_data.frequencies
    inspected = ["solved_data.frequencies"]
    if source == SOURCE_INTENT:
        # Named ONLY when the intent was the source actually used, so ``inspected``
        # records what the judgment rested on rather than everything glanced at.
        inspected.append("intent.target_frequency_hz")

    observed = _target_evidence(target, source, intent_target)
    observed["sample_count"] = len(frequencies)
    conditions: dict[str, object] = {
        "solved_data_readable": True,
        "sweep_non_empty": bool(frequencies),
        "target_supplied": target is not None,
    }

    # ``min``/``max`` are builtins; no ``math`` import is needed or wanted here,
    # and the gate set's import union stays at three roots because of it.
    if frequencies:
        lowest, highest = min(frequencies), max(frequencies)
        observed["lowest_swept_hz"] = lowest
        observed["highest_swept_hz"] = highest
    else:
        lowest = highest = None

    if not frequencies:
        return _build(
            snapshot,
            outcome="insufficient_evidence",
            inspected=inspected,
            observed_values=observed,
            reason_flagged=(
                "The solved data carries no swept frequencies, so there is no "
                "range to test a target against."
            ),
            conditions=conditions,
        )

    if target is None:
        # NEDA'S CASE. Not ``not_evaluated`` -- see the module docstring.
        return _build(
            snapshot,
            outcome="insufficient_evidence",
            inspected=inspected,
            observed_values=observed,
            reason_flagged=(
                "No target frequency was supplied by the caller and the design "
                "carries no intent, so nothing could be checked at a specific "
                f"frequency. The solved sweep runs from {lowest!r} Hz to "
                f"{highest!r} Hz across {len(frequencies)} sample(s). A target is "
                "never assumed or defaulted."
            ),
            conditions=conditions,
        )

    covered = lowest <= target <= highest
    return _build(
        snapshot,
        outcome="pass" if covered else "fail",
        inspected=inspected,
        observed_values=observed,
        reason_flagged=(
            f"The target frequency {target!r} Hz (from the {source}) lies "
            f"{'inside' if covered else 'OUTSIDE'} the solved sweep, which runs "
            f"from {lowest!r} Hz to {highest!r} Hz across {len(frequencies)} "
            "sample(s)."
        ),
        conditions=conditions,
    )


def _from_absence(
    snapshot: DesignSnapshot,
    solved_data: SolveDataUnavailable,
    target: float | None,
    source: str | None,
    intent_target: float | None,
) -> Finding:
    """The arm where no solved data was read; there is no range at all."""
    outcome = _ABSENCE_OUTCOMES[solved_data.reason]
    observed = _target_evidence(target, source, intent_target)
    observed["reason"] = solved_data.reason
    observed["limitation"] = solved_data.limitation
    return _build(
        snapshot,
        outcome=outcome,
        inspected=["solved_data.reason", "solved_data.limitation"],
        observed_values=observed,
        reason_flagged=(
            "The snapshot carries no solved data, so there is no swept frequency "
            "range to test a target against. The reason given is "
            f"{solved_data.reason!r}: {solved_data.limitation}"
        ),
        conditions={
            "solved_data_readable": False,
            "sweep_non_empty": False,
            "target_supplied": target is not None,
        },
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
    """Assemble the sixteen required fields; five vary between the cases.

    ``held`` is derived by ``common.applicability``; see that function for the
    rule. This gate reaches ``held=True`` only on the two verdict cases, because
    ``target_supplied`` and ``sweep_non_empty`` are exactly the conditions a
    containment test needs.
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
        template_text=f"[gate] {GATE_NAME}: {outcome}. {reason_flagged}",
    )
