"""W-10's own result types: the receipt, and the record of one refusal.

LOCAL TYPES, NOT CONTRACT TYPES, AND THAT IS THE STEP'S CENTRAL DECISION rather
than a convenience. W-10's output is not a tool response. The tool response is
``tool_io.ValidationReport``, which nothing in ``src/`` constructs today and
which Step 3.3 owns -- see this package's ``__init__`` for the full statement and
for who owns surfacing a rejection to a user.

Adding a rejection field to ``ValidationReport`` at this step would have been a
version event on a type with NO producer at all, which is the shape ADR-30
dec. 3 condemns ("the slot then advertises a capability that does not exist")
one level further out than usual: there, no producer could fill a field; here,
no producer fills the type.

THE TWO SHAPES FOLLOWED, NEITHER OF THEM INVENTED HERE:

  * ``broker/audit/reader.py``'s ``AuditReadResult`` -- a frozen dataclass
    carrying the surviving payload beside the machine-readable statement of what
    did not survive. That module shipped at Step 1.4 carrying ``torn_tail`` and
    ``corrupt_lines`` on a local dataclass while ``AuditLog`` had no field for
    either; the contract caught up a full step later, at the amendment that
    surfaced them on the response. This module is at the same point in that arc.
  * ``metrics/sparams.py``'s ``Minus10dBBand`` / ``NoMinus10dBBand`` -- two
    independent frozen dataclasses rather than one type with a nullable field, so
    a caller must look at WHICH collection it took something from and cannot read
    an accepted finding off a refusal by accident.

FROZEN DATACLASSES, NOT PYDANTIC MODELS. A pydantic model would advertise a wire
shape, and nothing here crosses a wire: this is the in-process handoff from W-10
to whoever composes the response. Both precedents above are dataclasses for the
same reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from hfss_agent.contract import Finding, FindingSource

# WHY A FINDING WAS REFUSED. Three members, and they are three DIFFERENT FACTS
# rather than three severities of one -- which is why they are not collapsed into
# a single "malformed" with prose telling them apart.
#
#   * ``not_a_finding`` -- the object supplied was not a ``Finding`` instance at
#     all: a dict, a bare string, ``None``, or a class from somewhere else. The
#     engine seam is ``evaluate(DesignSnapshot) -> list[Finding]``, so this is the
#     seam itself being violated, and nothing about the object's CONTENT was ever
#     examined. Reporting it as ``schema_invalid`` would assert that a schema
#     check ran and failed, when no schema check was reachable.
#   * ``schema_invalid`` -- it WAS a ``Finding`` instance, and its validity could
#     not be established. A ``model_construct`` ghost missing required fields, a
#     field holding the wrong type, a nested ghost provenance, or a subclass
#     declaring an extra field that ``extra="forbid"`` refuses. The distinction
#     from the member above is exactly the distinction between "we could not look"
#     and "we looked and it failed", which this package draws everywhere else.
#     ONE MEMBER, THREE DETAILS, because the receipt gate has two stages and a
#     non-validation failure in either lands here -- see ``receipt.py``, where
#     each stage carries its own sentence. They are not three reasons: in all
#     three the object claimed to be a Finding and the claim could not be
#     established, which is one fact about one object. Splitting the member would
#     make a consumer route on the mechanism of our check rather than on what
#     happened to the finding.
#   * ``evidence_incomplete`` -- it satisfies the schema in every respect and
#     carries NO EVIDENCE in one or more of the fields whose whole purpose is to
#     carry some. A DIFFERENT FACT FROM ``schema_invalid``, NOT A SEVERITY OF IT,
#     and the difference is checkable rather than stylistic: ``schema_invalid``
#     means the object's SHAPE could not be established, so nothing about its
#     content was ever read; this one means the shape is perfect and the CONTENT
#     is absent. A ``Finding`` with ``reason_flagged=""`` validates cleanly --
#     measured, not assumed -- so no schema check can reach it, and folding the
#     two together would tell a reader "we could not parse this" about an object
#     that parsed perfectly. They also send a reader to different fixes: a schema
#     failure is a producer emitting the wrong shape, an evidence failure is a
#     producer emitting a judgment it cannot support.
#   * ``non_inert_value`` -- it satisfies the schema in every respect, and one of
#     its two ``Any``-typed fields carries an OBJECT where only a value may
#     travel: a ``pathlib.Path``, a callable, a live handle, a ``datetime``, a
#     ``str`` subclass carrying state. A FIFTH DIFFERENT FACT, and its difference
#     from each of the four above is checkable rather than stylistic:
#       - NOT ``schema_invalid``, because the schema VALIDATED this object.
#         ``observed_values`` and ``applicability.conditions`` are
#         ``dict[str, Any]`` and pydantic does not validate ``Any`` -- so unlike
#         every shape that member covers, nothing here failed a check. Measured
#         end to end: a ``Path`` planted in ``FreshnessEvidence.available_signals``
#         is copied by the real freshness gate into ``observed_values``, survives
#         the receipt gate's forcing pass intact, and reaches the finding's JSON
#         as a plain string carrying the operator's Windows account name.
#       - NOT ``evidence_incomplete``. That member means a field carries NOTHING;
#         this one means a field carries something that is not data. They are
#         opposite defects, and they send a producer to opposite fixes -- telling
#         a rule author its evidence is missing, when what it actually shipped was
#         a bound method, is the wrong instruction.
#       - NOT ``source_mismatch``, which is a property of the object's
#         RELATIONSHIP to the stream that carried it. This one is intrinsic: the
#         same finding carries the same object on either stream.
#       - NOT ``not_a_finding``: this object IS a ``Finding``, and its contents
#         were examined rather than being out of reach.
#
#     NAMED ``non_inert_value``, AND ``non_inert_evidence`` WAS THE FIRST
#     PROPOSAL AND WAS WRONG. The check covers two sites and only one of them is
#     evidence: ``finding.py`` groups ``inspected`` / ``observed_values`` /
#     ``calculation_ref`` / ``reason_flagged`` under "Evidence" and
#     ``limitations_and_assumptions`` / ``applicability`` under "Honesty", and
#     Part 2's ``EVIDENCE_FIELDS`` excludes ``applicability`` for exactly that
#     reason. So a bound method found in ``applicability.conditions`` and reported
#     as ``non_inert_evidence`` would be a true sentence under a false label --
#     the shape ``metrics/assembler.py`` has already renamed a constant over
#     (``_ONLY_PASS_PERMITS_NOTICE`` -> ``_REFUSAL_POLICY_NOTICE``, where
#     "the old name asserted the old policy, so leaving it would have left a true
#     sentence under a false label"). ``value`` is accurate at both sites, and it
#     is the word the allow-list itself is written in: what may travel is a value,
#     and what may not is an object.
#   * ``source_mismatch`` -- it validates cleanly, and it claims a ``source`` it
#     did not arrive on. A separate member because the finding is not malformed
#     in any way a schema can see: every field is present and well-typed, and the
#     only thing wrong is a claim about origin that the merge can check and the
#     schema cannot.
#
# EVERY MEMBER HAS A PRODUCER, which is ADR-28 dec. 4's rule applied to a local
# type rather than a contract one. ``evidence_incomplete`` was deliberately NOT
# declared at Part 1, when it had none; it is declared here, at the part that
# builds its gate. ``non_inert_value`` follows the same rule at Part 6: its
# producer is ``receipt.validate_finding``'s third stage, and the producer is
# reachable through real code rather than only through a fixture -- see the
# measurement named above.
RejectionReason = Literal[
    "not_a_finding",
    "schema_invalid",
    "non_inert_value",
    "evidence_incomplete",
    "source_mismatch",
]


@dataclass(frozen=True)
class RejectedFinding:
    """One finding that did not survive receipt, and why -- never the finding.

    THE OFFENDING OBJECT IS NOT CARRIED, and its absence is the point. Holding it
    would put an unvalidated object into the very result the gate exists to keep
    clean, and would give a downstream renderer something that looks findable to
    render.

    IDENTITY IS POSITIONAL FIRST. ``arrived_on`` and ``position`` are supplied by
    this wrapper and are total over every input shape; ``claimed_finding_id`` is
    read off an object of unknown provenance and is absent more often than not.
    Probe 4 of this step measured that: of ten input shapes, bare attribute
    access raised on six, and two more returned a value that was not a string.
    """

    # WHICH STREAM THIS ARRIVED ON -- an observation by the merge, never a claim
    # by the finding. Named ``arrived_on`` rather than ``source`` precisely
    # because ``Finding.source`` is the claim, and one of these records exists to
    # say the two disagreed; two fields called ``source`` would make the record
    # unreadable at exactly the moment it matters most.
    arrived_on: FindingSource
    # Index within that stream, 0-based. THE ONLY IDENTITY TOTAL OVER EVERY INPUT
    # SHAPE, because the wrapper already holds it and no read of the malformed
    # object is required to obtain it.
    position: int
    # THE FIRST FAILURE, NEVER THE COMPLETE LIST OF WHAT IS WRONG. A finding can
    # carry more than one defect at once -- a non-inert value, blank evidence and
    # a mislabelled source are mutually independent and all three are reachable on
    # one object -- and exactly one is reported, decided by the precedence written
    # at ``receipt.validate_finding``. A consumer must not read this as an
    # exhaustive diagnosis: fixing the reason named here can reveal another
    # underneath it.
    #
    # SINGULAR RATHER THAN A TUPLE, DELIBERATELY. Reporting every defect was
    # considered and is not proposed, on two grounds. The first two reasons are
    # SEQUENTIAL PRECONDITIONS rather than independent axes -- an object that is
    # not a Finding cannot be schema-checked, and one that fails the schema cannot
    # have its values walked or its evidence read -- so "all defects" is only ever
    # meaningful across the last three, which is a small return for a shape change
    # on a type Step 3.3 will consume. (Part 6 widened that group from two members
    # to three and did not change the conclusion; if it ever reaches a size where
    # a consumer genuinely needs the set, that is the moment to revisit, and this
    # sentence is here so the count is visible when it does.) And every sibling
    # refusal type in this package
    # (``SelectionRefused``, ``ExportRefused``, ``CannotEvaluate``) carries exactly
    # one outcome; a second convention for the same job would only make a reader
    # wonder which one means more.
    reason: RejectionReason
    # WRAPPER-AUTHORED, ALWAYS, and never a copy of the offending finding's own
    # prose. What may appear here is limited to: this module's own sentences,
    # pydantic's closed error-type vocabulary, ``Finding``'s own declared field
    # names, ``FindingSource``'s two members, and integers. In particular neither
    # the type name of a foreign object nor the name of an undeclared key reaches
    # this field -- both are chosen by whoever wrote the object, so echoing them
    # would put attacker-authored text into a wrapper-authored field. That is the
    # same discipline ``preflight/redaction.py``'s ``_tool_name`` applies when it
    # replaces a caller-controlled tool name with a constant.
    detail: str
    # THE ONE FIELD THAT CAN CARRY UNTRUSTED TEXT, best-effort and often absent.
    # ``None`` means "not readable as a string", which covers a shape that has no
    # such attribute, a dict without the key, an attribute holding a non-string,
    # and an object whose attribute access raised.
    #
    # NOT YET ENVELOPED. Part 4 owns the untrusted-string envelope, and until it
    # lands this field carries whatever was there, verbatim -- control characters
    # and instruction-shaped text included.
    # ``test_an_untrusted_finding_id_survives_verbatim_today`` asserts exactly
    # that, so Part 4 has a failing-to-passing transition to land against rather
    # than a comment to delete.
    claimed_finding_id: str | None


@dataclass(frozen=True)
class FindingReceipt:
    """What W-10 hands on: the findings that survived, and the refusals.

    TUPLES, NOT LISTS, for the reason ``metrics/assembler.py``'s ``_GateRouting``
    already states -- "so the routing cannot be edited after the decision is
    made; the frozen dataclass would otherwise hold a mutable payload and only
    look immutable". ``AuditReadResult`` makes the same choice for the same
    reason.

    ``accepted`` IS WHAT A COMPOSER RENDERS. Reaching ``rejected`` requires naming
    it, so a refused finding cannot be displayed by iterating the obvious thing.
    THE GUARANTEE IS HONESTLY BOUNDED, in the register ``ValidationReport``'s own
    docstring uses for its ordering guarantee: this states what W-10 hands on, and
    it cannot constrain what a downstream renderer chooses to do with either
    collection. Step 3.3 owns that decision.

    EVERY MEMBER OF ``accepted`` IS AN EXACT ``Finding`` -- ``type(x) is Finding``,
    not merely ``isinstance``. That holds by construction rather than by check:
    each one is the output of a fresh ``model_validate``, so a subclass carrying
    behaviour cannot be a member. See ``receipt.validate_finding``.
    """

    accepted: tuple[Finding, ...]
    rejected: tuple[RejectedFinding, ...]
    # --- identity anomalies among the ACCEPTED findings ----------------------
    #
    # RECORDED, NOT REFUSED, and that is the decision rather than the easy path.
    # A finding whose id clashes with another's, or whose id is blank, may be a
    # perfectly good judgment: full evidence, true source, every schema field
    # correct. Its only defect is its NAME. Refusing it would discard a judgment
    # over a labelling problem -- the same trade Part 1 refused when it normalized
    # a method-only subclass rather than rejecting it, and Part 2 refused when it
    # kept identity fields out of the evidence gate.
    #
    # AND THE OFFENCE IS NOT ATTRIBUTABLE TO ONE PARTY. Two findings share an id;
    # neither is "the offender". Refusing the second would make the verdict depend
    # on arrival order, which this module has just committed to as a stated
    # guarantee -- so a rule keyed on it would be arbitrary in a newly load-bearing
    # way. Refusing both would discard two judgments to punish one clash. The
    # precedent for recording instead is ``broker/audit/reader.py``'s
    # ``AuditReadResult``: surviving records are returned, and what is wrong with
    # the set is stated beside them.
    #
    # MEASURED FIRST: NOTHING KEYS, INDEXES, DEDUPES OR LOOKS UP BY ``finding_id``
    # anywhere in ``src/`` -- the only readers are the four gate construction sites
    # that mint it and this package, which uses it to LABEL a refusal. So a
    # collision corrupts no lookup and drops no record; the harm is narrower and
    # entirely real: two accepted findings a reader cannot tell apart.
    #
    # POSITIONS RATHER THAN IDS, so no new field carries untrusted text. An
    # engine-authored ``finding_id`` is unenveloped prose (Part 4 owns that), and
    # ``claimed_finding_id`` on a refusal is already the one field bearing it.
    # Indices cost a consumer one dereference into ``accepted`` -- where the id
    # lives anyway -- and keep the untrusted surface exactly where it was.
    #
    # EXACT-STRING GROUPING ONLY, AND THE BOUND IS NARROWER THAN THE HARM NAMED
    # ABOVE. Part 5 attacked this and the gap is real, so it is stated here rather
    # than left for a reader to discover: the harm recorded above is "two accepted
    # findings a reader cannot tell apart", and two ids can be indistinguishable
    # to a reader while being distinct strings. Measured, all three accepted with
    # ``id_collisions == ()``:
    #
    #   * ``"rule-a"`` beside ``"rule-a​"`` -- a trailing ZERO WIDTH SPACE.
    #     The two render identically and are not grouped.
    #   * an id carrying U+202E RIGHT-TO-LEFT OVERRIDE, which changes how a
    #     terminal displays it without changing a byte.
    #   * a Cyrillic homoglyph inside an otherwise-Latin id.
    #
    # NOT FIXED BY NORMALIZING, AND THE REASON IS THE ONE ``merge._id_anomalies``
    # RECORDS AT LENGTH: the identity reported here must be the identity the
    # PRODUCER emitted, because ``RejectedFinding.position`` and these indices
    # exist so a caller can correlate what it gets back against what it handed in.
    # Normalizing before grouping would break that correspondence, and it would
    # also require this package to own a Unicode confusability policy it has no
    # source for. ``render.py`` addresses the reader-facing half by framing the
    # value as data; nothing addresses the "looks the same" half, and no field
    # here claims to.
    #
    # SO A CONSUMER MAY READ THIS AS: these groups share an id EXACTLY. It may not
    # read an empty tuple as "every accepted finding is distinguishable".
    #
    # Groups of indices into ``accepted`` that share one non-blank id, in
    # first-occurrence order. Each group holds at least two entries; a lone id is
    # not a collision and is not listed.
    id_collisions: tuple[tuple[int, ...], ...] = ()
    # Indices into ``accepted`` whose ``finding_id`` is blank after stripping.
    #
    # A SEPARATE FACT FROM A COLLISION, not a degenerate case of one, and the two
    # are kept apart for the same reason ``RejectionReason``'s members are. A
    # collision says two findings cannot be told APART; a blank id says one finding
    # cannot be REFERRED TO at all, which is true of a single one with no partner.
    # Blank ids are therefore excluded from ``id_collisions`` rather than grouped
    # there: the absence of a name is not a shared name.
    #
    # ENGINE-ONLY IN PRACTICE, measured: ``gating.common.finding_id`` builds
    # ``f"gate-{name}-{outcome}"``, so the literal ``gate-`` prefix survives even
    # an empty gate name and no gate finding can carry a blank id on any snapshot
    # shape. This records a state only a separately-built producer can reach.
    unidentified: tuple[int, ...] = ()
