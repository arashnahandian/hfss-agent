"""Gate 3 of 4: can the results be confirmed current with respect to the design?

THIS GATE HAS EXACTLY ONE LEGAL OUTCOME -- ``insufficient_evidence`` -- AND THAT
IS A DESIGN DECISION, NOT AN UNFINISHED IMPLEMENTATION. Anyone reading
``return insufficient_evidence`` below and concluding the gate is a stub should
read this docstring first; it exists so the decision is not reopened from scratch.

THREE OF THE FIVE OUTCOMES ARE ILLEGAL HERE, and one sentence of the contract is
what makes two of them so. ``FreshnessEvidence`` says, verbatim:

    "Consumers must treat this as evidence to render, keyed by whatever the
    producer chose, and must never branch on a key name -- ``determinable`` is
    the field to branch on, which is why it is separate."

That single line is the whole reason ``pass`` and ``fail`` cannot be emitted:

  * ``pass`` -- CANNOT EMIT. Concluding "the results ARE current" requires reading
    the determination, and the determination lives inside ``available_signals``
    under a key. The line above forbids branching on a key name. ``determinable``
    is the only field that may be branched on, and it does not carry the answer --
    the same type's docstring says so in as many words: it is "deliberately not
    collapsed into a plain freshness boolean". ``determinable=True`` means the
    answer was OBTAINABLE, not that the answer was "current".
  * ``fail`` -- CANNOT EMIT, for the identical reason in the other direction.
    Concluding "the results are STALE" is the same forbidden read. The type has no
    field able to express "determinable AND stale", so a producer that could
    observe staleness has nowhere to put it and this gate has nothing to read.
  * ``warning`` -- CANNOT EMIT, because no ruling covers a hedged freshness state.
    Neda was given three options (ADR-30 dec. 7) and chose show-the-numbers-under-
    a-notice, which is ``insufficient_evidence``; she described no fourth, weaker
    state. Inventing one would be inventing rule content this package does not own
    -- the same objection that forbids a delta-S threshold in the convergence gate.
  * ``not_evaluated`` -- CANNOT EMIT. This gate has no precondition that can be
    absent: ``freshness_evidence`` is required on ``SolveState``, and the other arm
    is a REPORTED ABSENCE rather than a missing input. Contrast the target-coverage
    gate, which genuinely can be handed no target; that is the one gate for which
    ``not_evaluated`` is reachable.

THE DECISION AND WHY THE ALTERNATIVES LOST (Arash's call, Step 2.6b Part 3b).
The governing fact is that ``real_adapter.py:575-577`` constructs
``FreshnessEvidence(available_signals={}, determinable=False)`` as a literal inside
a single ``return`` expression, with no branch above it and no branch structurally
possible. So this gate returns ``insufficient_evidence`` on every real design under
EVERY option that was on the table. The options differ only in what they do to a
fixture:

  * AMENDING THE TYPE to carry a machine-readable verdict (``is_current: bool |
    None``) -- REJECTED, and worse than neutral. It changes zero production
    behaviour, because no producer can fill the new field; it would be a slot
    advertising a capability that does not exist, which is verbatim the shape
    ADR-30 dec. 3 condemns and the reason three sibling provenance types DROP their
    equivalents rather than optionalising them. ADR-28 dec. 4's rule -- every
    member derived from a real producer -- refuses it independently.
  * RESERVING ONE KEY NAME in ``available_signals`` and permitting a branch on it
    -- REJECTED. The only candidate name is the FAKE's invention
    (``design_modified_since_solve``), which names the exact signal the real
    adapter states it cannot obtain. Blessing it as vocabulary would tell a reader
    this package has a design-modified signal, which ADR-4 recorded that it does
    not. It also makes a branch reachable only against a fixture.
  * RULING THAT THE DOCSTRING IS WRONG and reading ``determinable=True`` as "is
    current" -- REJECTED, because the docstring is RIGHT. It is the TYPE that
    cannot express three states, not the prose that is inaccurate. Rewriting the
    prose to match a convenient reading would leave the type unable to say "stale"
    while now claiming it could.

  * SHIPPING THE SINGLE-OUTCOME GATE WITH THE DISCLOSURE -- CHOSEN. Decisively,
    NEDA ALREADY RULED ON EXACTLY THIS WORLD. ADR-30 dec. 7 records that her ruling
    was needed BECAUSE freshness is undeterminable unconditionally, and her chosen
    text -- "We could not confirm these results are current -- we cannot tell
    whether this design was changed after it was solved" -- is a ruling about a gate
    that NEVER can tell. Emitting ``insufficient_evidence`` unconditionally
    IMPLEMENTS her decision rather than working around it, and
    ``insufficient_evidence`` is in ``GATE_OUTCOMES_THAT_QUALIFY_COMPUTATION``, so
    the numbers still reach the user under the notice she asked for.

THE ACCEPTED RISK, WRITTEN DOWN RATHER THAN GLOSSED: a design that is genuinely
STALE is reported as ``insufficient_evidence``, not as stale. This is LATENT
today -- no producer can emit a staleness signal, so there is no case where the
wrapper knew and stayed quiet -- and it becomes LIVE the day a real signal exists.

THE REVISIT TRIGGER is the queued PyAEDT probe for the two signals the domain
expert identified: the AEDT Message Manager warning, and the cross beside each
report under Results in the Project Manager. This repo has zero coverage of either,
in code or in ``docs/pyaedt-coverage.md``. WHEN THAT PROBE FINDS A SIGNAL, THE
ORDER IS TYPE FIRST, THEN PRODUCER: amend ``FreshnessEvidence`` so staleness is
expressible, THEN teach the adapter to fill it, THEN make ``pass``/``fail``
reachable here. Doing it in the other order recreates the field-with-no-producer
this decision exists to refuse.

THE ABSENCE-ARM MAPPING IS EXHAUSTIVE OVER THE PINNED LITERAL SET, BY LOOKUP AND
WITH NO DEFAULT -- see ``_ABSENCE_OUTCOMES``. All four members map to the same
outcome, and the table is written out member by member anyway: a collapsed
"whatever the reason, return insufficient_evidence" would go silently wrong the
day a fifth member arrives with a different right answer.
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

GATE_NAME = "freshness"
RULE_ID = f"gate.{GATE_NAME}"
CALCULATION_REF = f"hfss_agent.gating.{GATE_NAME}:evaluate"

# See ``solution_exists.RULE_VERSION`` for what moves this. The trigger named in
# the docstring above -- the type gaining a staleness field -- is exactly the
# change that would make a different outcome reachable, so it is a MAJOR bump here
# rather than a patch.
RULE_VERSION = "1.0.0"

RULE_PURPOSE = (
    "Reports whether the results can be confirmed current with respect to the "
    "design as it now stands."
)

# NEDA'S WORDING, LIFTED FROM THE OPTION SHE CHOSE (ADR-30 dec. 7) AND NOT
# PARAPHRASED. ADR-30 dec. 22's standing rule is that a domain expert must be
# addressed in HFSS terms rather than in this codebase's vocabulary; the same rule
# applies in reverse when her answer becomes user-facing text. "Check the Message
# Manager and the report icons in the Project Manager" is the practically useful
# half of her ruling -- it tells an engineer WHERE TO LOOK in AEDT, which no
# wording of ours was going to reproduce.
#
# WHY IT LIVES IN ``reason_flagged`` AND NOWHERE ELSE. Traced end to end rather
# than assumed: W-7's caveat block renders exactly three fields of a qualifying
# Finding -- ``rule_id``, ``outcome`` and ``reason_flagged``.
# ``limitations_and_assumptions``, the Finding's own ``template_text``,
# ``rule_purpose``, ``calculation_ref`` and ``finding_id`` do NOT reach that
# surface. Putting her guidance in ``limitations_and_assumptions`` as well would
# be two homes for one fact, and the one a user actually reads is this one.
#
# THE ONE ADAPTATION, stated because a quote should be flagged when it is not
# byte-exact: her em-dash is rendered as ASCII ``--``. Measured, not assumed --
# there are zero em-dashes and five ASCII ``--`` in the runtime strings of
# ``gating`` and ``metrics``, so this follows the convention of the text it will
# be rendered beside. No word is changed.
_CURRENCY_NOTICE = (
    "We could not confirm these results are current -- we cannot tell whether "
    "this design was changed after it was solved. Check the Message Manager and "
    "the report icons in the Project Manager before trusting these."
)

LIMITATIONS = (
    "The decision rests on FreshnessEvidence.determinable ALONE. "
    "available_signals has no key vocabulary -- the contract states that "
    "consumers must never branch on a key name -- so it is reported here as "
    "evidence and is never read to decide anything. The real adapter returns "
    "determinable=False unconditionally, with no branch above it, so this gate "
    "returns insufficient_evidence on any live design; determinable=True is "
    "reachable only against the fake adapter used in CI. CONSEQUENTLY A PRODUCER "
    "THAT COULD REPORT A DESIGN AS MODIFIED SINCE ITS SOLVE HAS NO FIELD TO SAY "
    "SO, AND THIS GATE CANNOT REPORT STALENESS: a genuinely stale design is "
    "reported as not-confirmable, not as stale. Treat an insufficient_evidence "
    "here as 'currency was not confirmed', never as 'the results are current'."
)

# THE STRUCTURAL CONDITION THAT NEVER HOLDS, and the reason this gate's outcome is
# constant. It is listed as an applicability condition rather than buried in prose
# so the machine-readable block states WHY no determination was reached, not merely
# that none was.
#
# IT IS ALSO THE SEAM. When the revisit trigger fires and the type gains a field
# able to express staleness, this constant becomes a real per-snapshot check and
# flips to True -- at which point ``pass`` and ``fail`` become reachable without
# restructuring anything else in this module. Marking that here is what keeps the
# future change a one-line edit at a named place rather than a redesign.
_DETERMINATION_IS_READABLE = False

# EXHAUSTIVE OVER ``SolveDataUnavailableReason``, AS A LOOKUP WITH NO DEFAULT.
# ALL FOUR MAP TO THE SAME OUTCOME, and they are still written out one by one. A
# collapsed "return insufficient_evidence whatever the reason" reads identically
# today and goes silently wrong the day a fifth member arrives whose right answer
# differs -- which is the whole reason the sibling gates use a lookup instead of an
# ``if``. ``test_absence_mapping_covers_every_reason`` pins this by set equality in
# both directions.
_ABSENCE_OUTCOMES: dict[str, FindingOutcome] = {
    "no_solution": "insufficient_evidence",
    "not_exposed_by_pyaedt": "insufficient_evidence",
    "not_found_in_design": "insufficient_evidence",
    "unrecognised_by_wrapper": "insufficient_evidence",
}


def evaluate(snapshot: DesignSnapshot) -> Finding:
    """Report whether currency could be confirmed. It never can -- see the module.

    STILL NARROWS BOTH ARMS, AND STILL BUILDS DIFFERENT EVIDENCE PER ARM, even
    though the outcome is constant. The ``Finding`` differs between the arms in
    three required fields -- ``inspected``, ``observed_values`` and
    ``reason_flagged`` -- and only ``outcome`` is the same. Collapsing to one path
    would cost two real things: ``inspected`` would have to name paths that do not
    resolve on one of the arms (``solve_state.freshness_evidence`` does not exist
    on ``SolveDataUnavailable``), and ``observed_values`` could not carry
    ``determinable`` where there is no freshness evidence to read it from.

    Takes the whole snapshot and narrows internally; see
    ``solution_exists.evaluate`` for why that is the shape.

    Args:
        snapshot: the artifact to judge. Never mutated; nothing is fetched.

    Returns:
        One ``Finding`` with ``source="gate"`` and, today, always
        ``outcome="insufficient_evidence"``.
    """
    solve_state = snapshot.solve_state
    if isinstance(solve_state, SolveState):
        return _from_solve_state(snapshot, solve_state)
    return _from_absence(snapshot, solve_state)


def _from_solve_state(snapshot: DesignSnapshot, solve_state: SolveState) -> Finding:
    """The arm where freshness evidence exists -- and still cannot be read."""
    evidence = solve_state.freshness_evidence
    return _build(
        snapshot,
        outcome="insufficient_evidence",
        inspected=[
            "solve_state.freshness_evidence.determinable",
            "solve_state.freshness_evidence.available_signals",
        ],
        # BOTH FIELDS TRAVEL, and carrying them is the point of this arm. Step 3.4
        # must fill ``ProvenanceRecord.freshness_status`` -- a required field on
        # every MetricRecord -- and this is what lets it do so from the finding
        # alone, without reaching back into the snapshot. That is the obligation:
        # ENABLE the derivation. Choosing the status vocabulary is NOT this gate's
        # to make (ADR-30 dec. 16 declined a Literal for exactly the reason that
        # no src/ producer of ProvenanceRecord exists, so a vocabulary minted now
        # would be derived from three test fixtures).
        #
        # ``available_signals`` IS COPIED VERBATIM AND NEVER INSPECTED. No key is
        # read, tested, or named anywhere in this module.
        observed_values={
            "determinable": evidence.determinable,
            "available_signals": dict(evidence.available_signals),
        },
        # HER WORDS FIRST, our evidence detail demoted to a parenthetical after
        # them. The order is not cosmetic: this string is rendered as one line of
        # W-7's caveat block, and a reader who stops after the first sentence
        # should already have the actionable half.
        reason_flagged=(
            f"{_CURRENCY_NOTICE} (The snapshot reports "
            f"determinable={evidence.determinable} for freshness, and the "
            "wrapper has no field able to carry a design-modified-since-solve "
            "determination, so no currency verdict can be read from it. The "
            "signals are reported as evidence and were not interpreted.)"
        ),
        conditions={
            "solve_state_readable": True,
            "freshness_determinable": evidence.determinable,
            "determination_is_readable": _DETERMINATION_IS_READABLE,
        },
    )


def _from_absence(
    snapshot: DesignSnapshot, solve_state: SolveDataUnavailable
) -> Finding:
    """The arm where no solve state was read; there is no evidence at all."""
    outcome = _ABSENCE_OUTCOMES[solve_state.reason]
    return _build(
        snapshot,
        outcome=outcome,
        inspected=["solve_state.reason", "solve_state.limitation"],
        # No ``determinable`` key here, and its ABSENCE is the honest signal: there
        # is no freshness evidence on this arm to report one from. Step 3.4 derives
        # its freshness_status from the reason instead, which is why the reason
        # travels rather than being flattened into the prose.
        observed_values={
            "reason": solve_state.reason,
            "limitation": solve_state.limitation,
        },
        # HER WORDS ON THIS ARM TOO, and the fit is worth stating rather than
        # assuming. "We cannot tell whether this design was changed after it was
        # solved" is true here for a STRONGER reason than on the arm above: there
        # is no solve state at all, so there is not even evidence to be
        # undeterminable about. The guidance is identical either way -- the
        # Message Manager and the Project Manager report icons are where an
        # engineer looks in both cases -- so splitting the wording would give a
        # user two phrasings of one situation with no way to tell why.
        reason_flagged=(
            f"{_CURRENCY_NOTICE} (The snapshot carries no solve state, so there "
            "is no freshness evidence to read at all. The reason given is "
            f"{solve_state.reason!r}: {solve_state.limitation})"
        ),
        conditions={
            "solve_state_readable": False,
            "freshness_determinable": False,
            "determination_is_readable": _DETERMINATION_IS_READABLE,
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
    """Assemble the sixteen required fields; four vary between the arms.

    ``held`` is derived by ``common.applicability``; see that function for the rule
    it follows. Here it is ``False`` on both arms, because
    ``determination_is_readable`` never holds -- which is the machine-readable form
    of this gate's whole situation.
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
