"""Gate 2 of 4: did the adaptive solve converge, or stop short of its criterion?

NEDA'S RULING GOVERNS THIS GATE (ADR-30 dec. 6), in her own words:

    "there should be a warning that solution didn't converge because result
    maybe wrong"

and, asked how HFSS itself behaves (spelling normalised, no word changed --
four keyboard slips, five characters: ``doesnt`` -> ``doesn't``, ``poping`` ->
``popping``, ``didnt`` -> ``didn't``, ``foesnt`` -> ``doesn't``):

    "during the solve if it doesn't reach convergence there is a warning in AEDT
    message manager window popping warning that solution didn't converge this
    doesn't stop it though, it go to the frequency sweep"

Translated into this codebase's vocabulary -- the translation is OURS and is
labelled as such -- ``stopped`` emits ``warning``, and ``warning`` no longer
refuses. SHE GAVE NO DELTA-S MAGNITUDE THRESHOLD AND NONE MAY BE INVENTED: HFSS
warns identically at 0.021 and at 0.15, and manufacturing a cutoff would be
inventing rule content this package does not own. Nothing below reads a delta-S
value to make a decision; the series is reported as evidence and never compared.
The absence of any arithmetic here is the enforcement.

TWO OF THE FIVE OUTCOMES CANNOT BE EMITTED HERE, and each absence is deliberate.
This prose is the only record of them (ADR-29 dec. 4):

  * ``fail`` -- CANNOT EMIT, because ``ConvergenceStatus`` has exactly two members
    and the ruling above assigns the non-converged one to ``warning``. There is no
    third status left to map to ``fail``, and deriving one from delta-S magnitude
    is precisely the threshold she did not give. A ``fail`` here would also refuse
    all metrics on a solve that AEDT itself proceeds from into the frequency
    sweep, which is the behaviour the ruling exists to mirror rather than exceed.
  * ``not_evaluated`` -- CANNOT EMIT, because this gate has no precondition that
    can be absent. ``convergence_status`` is required on ``SolveState``, and the
    other arm is a reported absence rather than a missing input. Contrast the
    target-coverage gate, which genuinely can be handed no target.

THE ABSENCE-ARM MAPPING IS EXHAUSTIVE OVER THE PINNED LITERAL SET, BY LOOKUP AND
WITH NO DEFAULT -- and so is the status mapping. See both tables below.
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

GATE_NAME = "convergence"
RULE_ID = f"gate.{GATE_NAME}"
CALCULATION_REF = f"hfss_agent.gating.{GATE_NAME}:evaluate"

# See ``solution_exists.RULE_VERSION`` for what moves this and why it is tied to
# neither the package version nor ``CONTRACT_VERSION``.
RULE_VERSION = "1.0.0"

RULE_PURPOSE = (
    "Reports whether the adaptive solve converged or stopped short of its "
    "convergence criterion."
)

LIMITATIONS = (
    "Reports the solver's own converged/stopped status as read. NO DELTA-S "
    "MAGNITUDE THRESHOLD IS APPLIED: HFSS warns identically at any non-converged "
    "delta-S, and no threshold has been specified for this wrapper, so the "
    "progression is reported as evidence and never compared against a cutoff. "
    "The row shape of adaptive_pass_history is an unverified assumption about "
    "what PyAEDT returns (mock-only; live-verify Phase 5.2), so only its length "
    "is reported and nothing inside a row is read."
)

# EXHAUSTIVE OVER ``ConvergenceStatus``, AS A LOOKUP WITH NO DEFAULT. Two members
# today; a third added later raises ``KeyError`` here rather than falling through
# to a permissive branch. ``test_status_mapping_covers_every_convergence_status``
# pins it against ``get_args`` by set equality in both directions.
#
# ``stopped -> warning`` IS THE RULING, not a judgment made here, and it is
# unconditional on delta-S. ``warning`` is a member of
# ``GATE_OUTCOMES_THAT_QUALIFY_COMPUTATION``, so this is the mapping that lets W-7
# return numbers beside the caveat rather than refusing -- which is the whole point
# of ADR-30 dec. 6 and of the fourth ``compute_metrics`` arm.
_STATUS_OUTCOMES: dict[str, FindingOutcome] = {
    "converged": "pass",
    "stopped": "warning",
}

# EXHAUSTIVE OVER ``SolveDataUnavailableReason``, AS A LOOKUP WITH NO DEFAULT.
# ALL FOUR MAP TO ``insufficient_evidence``, INCLUDING ``no_solution``, and the
# uniformity is a decision rather than a shortcut: this gate asks whether the
# adaptive solve converged, and "there is no solved data" is not a convergence
# failure -- it is the absence of a solve to have an opinion about. Routing
# ``no_solution`` to ``fail`` here would report a never-run solve as a
# non-converged one, which is a different and worse claim. The solution-existence
# gate is the one that owns that member, and it is the only gate that fails on it.
_ABSENCE_OUTCOMES: dict[str, FindingOutcome] = {
    "no_solution": "insufficient_evidence",
    "not_exposed_by_pyaedt": "insufficient_evidence",
    "not_found_in_design": "insufficient_evidence",
    "unrecognised_by_wrapper": "insufficient_evidence",
}


def evaluate(snapshot: DesignSnapshot) -> Finding:
    """Judge the adaptive solve's convergence, without judging its delta-S.

    Takes the whole snapshot and narrows internally; see
    ``solution_exists.evaluate`` for why that is the shape rather than receiving a
    pre-narrowed arm.

    Args:
        snapshot: the artifact to judge. Never mutated; nothing is fetched.

    Returns:
        One ``Finding`` with ``source="gate"``. Never raises for a well-formed
        snapshot.
    """
    solve_state = snapshot.solve_state
    if isinstance(solve_state, SolveState):
        return _from_solve_state(snapshot, solve_state)
    return _from_absence(snapshot, solve_state)


def _from_solve_state(snapshot: DesignSnapshot, solve_state: SolveState) -> Finding:
    """The arm where a status was read. The status alone decides the outcome."""
    status = solve_state.convergence_status
    outcome = _STATUS_OUTCOMES[status]
    pass_count = len(solve_state.adaptive_pass_history)
    return _build(
        snapshot,
        outcome=outcome,
        inspected=[
            "solve_state.convergence_status",
            "solve_state.delta_s_progression",
            "solve_state.adaptive_pass_history",
        ],
        observed_values={
            "convergence_status": status,
            # The progression travels whole, as EVIDENCE. Nothing here compares it
            # to anything; a reader (or Neda) can look at the numbers, which is
            # exactly the use the ruling leaves open.
            "delta_s_progression": list(solve_state.delta_s_progression),
            # THE LENGTH, NEVER THE ROWS. ``adaptive_pass_history`` is typed
            # ``list[Any]`` and its row shape is mock-only, so reaching inside one
            # would branch on an unverified assumption. A count is readable from
            # any shape.
            "adaptive_pass_count": pass_count,
        },
        reason_flagged=(
            f"The solver reported convergence status {status!r} after "
            f"{pass_count} adaptive pass(es)."
            + (
                ""
                if outcome == "pass"
                else " The solve stopped without meeting its convergence "
                "criterion, so results may be wrong; AEDT itself warns and "
                "proceeds into the frequency sweep rather than withholding them."
            )
        ),
        conditions={"solve_state_readable": True},
    )


def _from_absence(
    snapshot: DesignSnapshot, solve_state: SolveDataUnavailable
) -> Finding:
    """The arm where no solve state was read; no status exists to report."""
    outcome = _ABSENCE_OUTCOMES[solve_state.reason]
    return _build(
        snapshot,
        outcome=outcome,
        inspected=["solve_state.reason", "solve_state.limitation"],
        observed_values={
            "reason": solve_state.reason,
            "limitation": solve_state.limitation,
        },
        reason_flagged=(
            "The snapshot carries no solve state, so no convergence status "
            f"exists to report. The reason given is {solve_state.reason!r}: "
            f"{solve_state.limitation}"
        ),
        conditions={"solve_state_readable": False},
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

    ``held`` is derived by ``common.applicability``; see that function for the rule.
    This gate is the source of the SECOND combination that rule exists to explain:
    on ``stopped`` the outcome is ``warning`` while ``held`` is ``True``. The rule
    applied cleanly and returned a hedge, and a hedge is a result rather than a
    failure to apply. Unlike the solution-existence gate, this one has no case where
    ``held`` is ``False`` while a determination was still reached -- every absence
    reason here yields ``insufficient_evidence``.
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
