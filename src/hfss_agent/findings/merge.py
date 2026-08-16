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

    ORDERING IS NOT A COMMITMENT AT THIS PART. Gate findings are processed before
    engine findings and each stream keeps its own order, but nothing here states
    that as a guarantee and no test pins it yet -- the merge's ordering rule, and
    what to do about a ``finding_id`` colliding across the two streams, are the
    next part's. What IS committed here is that every element of both streams is
    put through the identical receipt gate.

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

    return FindingReceipt(accepted=tuple(accepted), rejected=tuple(rejected))


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
