"""The entry point: two streams in, one receipt out, with the source claim checked.

TWO SEPARATE PARAMETERS RATHER THAN ONE MERGED LIST, and the reason is the whole
security argument of this module. Handed one already-merged sequence, a finding
claiming ``source="gate"`` that actually came from the engine is UNDETECTABLE --
there is nothing to check the claim against, so the merge would be trusting a
label. Handed two, the claim is checkable against the stream it arrived on, and
the wrapper's own gate output is the trusted reference for what a genuine
``"gate"`` looks like.

That is the same attack class ADR-23 dec. 1 refused one label over, and the
direction matters more than it looks:

  * a source-keyed EXEMPTION -- what ADR-23 forbids -- RELAXES a requirement for
    one source, so a finding wearing the right label bypasses the gate;
  * a source VERIFICATION -- what this module adds -- imposes one IDENTICAL
    requirement on every source, so a finding wearing the wrong label is caught.

They run in opposite directions. The receipt gate itself stays unconditional: no
accept-or-refuse decision in ``receipt.validate_finding`` branches on a source
value, so there is no source for which its requirement could be relaxed and no
call site that could forget one. This module is where a source value IS branched
on -- once, in ``_source_mismatch`` -- and it applies that one branch to every
finding on both streams.

STATED AS A PROPERTY OF BRANCHING RATHER THAN OF THE TEXT, deliberately, and
``receipt.validate_finding``'s docstring records why at length: an earlier
wording claimed the string ``source`` did not appear in that function, which was
false the moment it was written (``FindingSource`` contains it and is in the
signature). Whoever writes Part 3's AST check should check the operands of
branches, not the spelling of identifiers.
"""

from __future__ import annotations

from collections.abc import Sequence

from hfss_agent.contract import Finding, FindingSource
from hfss_agent.findings.receipt import validate_finding
from hfss_agent.findings.results import FindingReceipt, RejectedFinding

# The two streams, named once so the merge and the refusal records cannot spell
# them differently. These are ``FindingSource`` members, annotated with the
# Literal rather than left bare ``str`` so a typo is a contract violation at the
# annotation -- the convention ``gating/common.py``'s ``GATE_SOURCE`` set.
GATE_STREAM: FindingSource = "gate"
ENGINE_STREAM: FindingSource = "engine_rule"


def merge_findings(
    *,
    gate_findings: Sequence[Finding],
    engine_findings: Sequence[Finding],
) -> FindingReceipt:
    """Merge the two finding streams, refusing anything that fails receipt.

    Args:
        gate_findings: what ``gating.evaluate_gates`` returned for this snapshot.
        engine_findings: what the engine returned, or an empty sequence when no
            engine is installed. REQUIRED AND UNDEFAULTED, like
            ``metrics.compute_metrics``' ``gate_findings`` and for the same
            reason: a default buys nothing except letting a caller omit the
            argument by accident. Whoever composes the response knows whether an
            engine is present, so passing ``()`` explicitly makes ABSENCE A
            STATEMENT AT THE CALL SITE rather than a silence.

    Returns:
        A ``FindingReceipt``. Never raises for any element shape.

    KEYWORD-ONLY, following ADR-29's finding on ``assemble_snapshot``: two
    adjacent parameters that can hold the same type transpose silently, and a
    transposition that validates is worse than one that fails. Seven parameters
    forced the issue there; two of identical type are enough here.

    THE MEASURED DANGER IS SMALLER THAN THE PRECEDENT'S, AND THE GUARD IS KEPT
    ANYWAY -- recorded because the difference is easy to get backwards. Because
    this module verifies the source claim, a transposition is LOUD whenever
    EITHER stream is non-empty: swapped, every gate finding arrives on the engine
    stream still claiming ``"gate"``, and every engine finding arrives on the
    gate stream still claiming ``"engine_rule"``, so each one refuses as a
    ``source_mismatch``. The only silent transposition is the both-empty case,
    which is a no-op. So the verification would in fact catch what the keyword
    guard prevents.
    THE GUARD STILL EARNS ITS PLACE, for a reason that is not about how loud the
    failure is: relying on a runtime check to cover a signature defect means the
    correctness of the call depends on a check that a later edit could narrow.
    Keyword-only makes the mistake UNCONSTRUCTIBLE, which is how this package
    handles dangerous states everywhere else, and it costs one character.

    THE ORDERING GUARANTEE, WHICH THIS PART MAKES AND EARLIER PARTS DECLINED TO.
    ``accepted`` carries the surviving gate findings first, then the surviving
    engine findings, and WITHIN each stream the order the caller supplied. A
    refusal removes its own element and shifts nothing else. Two merges of equal
    inputs therefore produce equal receipts, byte for byte.

    WHAT THIS IS NOT: it is not a restatement of ``evaluate_gates``' own order.
    That guarantee -- four findings in ``GATE_NAMES`` order -- is W-9's, and it is
    already pinned there twice (``test_evaluate_gates_always_returns_four_in_order``
    and ``test_the_aggregator_order_matches_the_contract_fixtures_spelling``).
    Re-asserting it here would be two sources for one fact. What is claimed here is
    strictly about THIS function's behaviour: that it CONCATENATES rather than
    interleaving, sorting or reordering, whatever order it was handed.

    TWO REASONS, AND THE SECOND IS THE LOAD-BEARING ONE:

      * DIFFABILITY. The same reason W-5 and W-6 make their ``template_text``
        byte-deterministic: a diff between two receipts should show what changed
        in the design, not what changed in iteration order.
      * ``RejectedFinding.position`` MEANS NOTHING WITHOUT IT. That field is an
        index into the stream as the caller passed it, and it is the only identity
        total over every input shape. A caller correlating a refusal -- or an
        accepted finding -- against what they handed in can only do so if this
        function preserves relative order. The receipt's own identity mechanism
        depends on the guarantee, which makes it internal rather than a courtesy
        to a hypothetical renderer.

    IDENTITY ANOMALIES ARE RECORDED, NOT REFUSED. A ``finding_id`` that clashes
    with another, or that is blank, is reported on the receipt rather than costing
    a finding its place -- see ``FindingReceipt.id_collisions`` and
    ``.unidentified`` for the argument, and ``_id_anomalies`` for the derivation.

    THE ELEMENTS ARE UNTRUSTED; THE CONTAINERS ARE THE CALLER'S. Every element is
    treated as an object of unknown provenance, whatever the annotation says --
    that is what ``receipt.validate_finding`` is for. The two SEQUENCES
    themselves are not guarded: a non-iterable passed here raises, and that is
    correct, because it is a wrapper-side bug at the call site rather than
    anything the engine can cause on its own. Whether the engine returning a
    non-list at all is caught before this point is the concern of whoever obtains
    that value, which is the composition step and not this one.
    """
    accepted: list[Finding] = []
    rejected: list[RejectedFinding] = []

    for arrived_on, stream in (
        (GATE_STREAM, gate_findings),
        (ENGINE_STREAM, engine_findings),
    ):
        # ELEMENT BY ELEMENT, SO ONE MALFORMED FINDING REFUSES ALONE. Validating
        # a whole stream as ``list[Finding]`` in one call would have been shorter
        # and is wrong: pydantic's list validation is all-or-nothing, so a single
        # bad engine finding would discard every good one beside it -- including
        # all four of the wrapper's own gate results.
        for position, candidate in enumerate(stream):
            outcome = validate_finding(
                candidate, arrived_on=arrived_on, position=position
            )
            if isinstance(outcome, RejectedFinding):
                rejected.append(outcome)
                continue
            mismatch = _source_mismatch(
                outcome, arrived_on=arrived_on, position=position
            )
            if mismatch is not None:
                rejected.append(mismatch)
                continue
            accepted.append(outcome)

    survivors = tuple(accepted)
    collisions, unidentified = _id_anomalies(survivors)
    return FindingReceipt(
        accepted=survivors,
        rejected=tuple(rejected),
        id_collisions=collisions,
        unidentified=unidentified,
    )


def _id_anomalies(
    accepted: tuple[Finding, ...],
) -> tuple[tuple[tuple[int, ...], ...], tuple[int, ...]]:
    """Which accepted findings cannot be told apart, and which cannot be named.

    RUN OVER THE SURVIVORS ONLY, which is the whole point of running it here
    rather than inside the loop. A refused finding is not handed on, so it cannot
    make an accepted one ambiguous; grouping before the refusals were known would
    report clashes with objects nobody will ever see.

    DETERMINISTIC BY CONSTRUCTION. Groups come out in first-occurrence order
    because ``dict`` preserves insertion order, and the indices inside each group
    are ascending because ``enumerate`` produces them that way. No sort is applied
    and none is needed -- which matters, because a sort over engine-authored id
    strings would make the output depend on their content.

    GROUPING BY AN UNTRUSTED VALUE IS NOT BRANCHING ON ONE, and the distinction is
    worth stating because the id is engine-authored. ADR-9 forbids untrusted text
    influencing CONTROL FLOW -- tool routing, tier decisions, file paths. Nothing
    of that kind happens here: no code path is selected, no capability is chosen,
    and the same statements execute whatever the ids hold. The id is used as a
    dictionary key exactly as ``Counter`` would use it, and the result is data.

    SANITIZING ``finding_id`` BEFORE THIS PASS WAS CONSIDERED AT PART 4 AND IS
    DELIBERATELY NOT DONE. It is written here because this is where the next
    person will be tempted, and because the arguments FOR it are good enough that
    dropping them would look like nobody had thought of it. Measured, both ways:

      * two ids differing only in control characters -- ``"rule-a\\x1b"`` and
        ``"rule-a\\x07"`` -- are DISTINCT today and would COLLIDE if stripped;
      * an id made only of control characters is NON-BLANK today (``str.strip``
        removes whitespace, and a control character is not whitespace, so it
        survives) and would become ``unidentified`` if stripped.

    Both changes are arguably improvements, and that is the point: two ids that
    render identically to a reader ARE indistinguishable, which is exactly what
    ``id_collisions`` means, and a name made only of invisible characters cannot
    be referred to.

    THE ARGUMENT AGAINST IS THE ONE THAT WINS, AND IT IS ABOUT CORRESPONDENCE
    RATHER THAN ABOUT SAFETY. ``RejectedFinding.position`` and the indices in
    ``id_collisions`` and ``unidentified`` exist so a caller can correlate what
    this module reports against what it handed in -- that is the whole reason
    ``merge_findings`` commits to preserving order. The identity W-10 reports must
    therefore be the identity the PRODUCER emitted; changing the value silently
    breaks the correspondence, and a caller looking for the id it sent would not
    find it. Two ids that a reader cannot tell apart is a real problem, but it is
    a RENDERING problem, and ``render.py`` is where it is addressed -- by framing
    the value as data, not by editing it. That is the same rule
    ``adapter/sanitize`` states for hostile content generally: neutralize by
    framing and typing, never by rewriting.

    W-10 COULD NOT DO IT EVEN IF THE ARGUMENT RAN THE OTHER WAY. ``sanitize_str``
    and ``MAX_UNTRUSTED_STR_LEN`` live in ``hfss_agent.adapter.sanitize``, which
    Layer 6 may not import; a hand-rolled second stripper here would be a second
    enforcement point for one rule, drifting from the adapter's the day either
    moves.

    Returns:
        ``(collisions, unidentified)`` -- groups of indices sharing one non-blank
        id, and the indices whose id is blank. Blank ids never appear in the first
        (see ``FindingReceipt.unidentified`` for why the absence of a name is not
        a shared name). "Blank" means blank AFTER WHITESPACE STRIPPING ONLY, and
        that is narrower than a reader expects: ``str.strip`` removes what Python
        calls whitespace, so a newline-only id IS blank, while an id of control
        characters, of U+200B ZERO WIDTH SPACE, or of U+202E RIGHT-TO-LEFT
        OVERRIDE is reported as NAMED -- all measured at Part 5. Such an id is
        invisible or misleading to every reader downstream and cannot be spoken,
        typed, or referred to, yet it is a name as far as this function is
        concerned. See ``FindingReceipt.id_collisions`` for the matching bound on
        the grouping half.
    """
    positions_by_id: dict[str, list[int]] = {}
    unidentified: list[int] = []
    for index, finding in enumerate(accepted):
        if not finding.finding_id.strip():
            unidentified.append(index)
            continue
        positions_by_id.setdefault(finding.finding_id, []).append(index)

    collisions = tuple(
        tuple(positions)
        for positions in positions_by_id.values()
        if len(positions) > 1
    )
    return collisions, tuple(unidentified)


def _source_mismatch(
    finding: Finding, *, arrived_on: FindingSource, position: int
) -> RejectedFinding | None:
    """Refuse a finding whose claimed source is not the stream it arrived on.

    RUN ON AN ALREADY-VALIDATED FINDING, WHICH IS WHY IT IS SAFE TO READ
    ``.source`` AT ALL. Before the receipt gate, ``source`` might be absent, hold
    a non-string, or raise on access; afterwards it is guaranteed to be one of
    ``FindingSource``'s two members. Doing this check first would mean reading an
    attribute off an object of unknown provenance to make a decision, which is
    precisely what ADR-9 forbids untrusted data from doing.

    A MISMATCH IS A REFUSAL, NOT A CORRECTION AND NOT A RAISE. Rewriting
    ``source`` to the stream's value was rejected for the reason
    ``adapter/sanitize`` states about hostile content generally -- we neutralize
    by framing and typing, never by rewriting -- and because it would destroy the
    evidence that the two disagreed. Raising was rejected because a malformed
    finding is a normal, representable outcome in this package, and because one
    bad element would then take the whole merge with it.

    THE GATE STREAM IS NOT EXEMPT. ``evaluate_gates`` sets every finding's source
    from one constant, so a mismatch there would mean wrapper-side corruption
    rather than an engine claim -- still refused, by this same code, with no
    branch distinguishing the two. That is the uniformity the Done bar asks for:
    the check is identical in both directions, and only the labels in the record
    differ.

    Both values in ``detail`` are ``FindingSource`` members, so nothing
    engine-authored reaches that wrapper-authored field.
    """
    if finding.source == arrived_on:
        return None
    return RejectedFinding(
        arrived_on=arrived_on,
        position=position,
        reason="source_mismatch",
        detail=(
            f"the finding claims source {finding.source!r} but arrived on the "
            f"{arrived_on!r} stream, so its stated origin cannot be vouched for."
        ),
        claimed_finding_id=finding.finding_id,
    )
