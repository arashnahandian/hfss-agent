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
#   * ``source_mismatch`` -- it validates cleanly, and it claims a ``source`` it
#     did not arrive on. A separate member because the finding is not malformed
#     in any way a schema can see: every field is present and well-typed, and the
#     only thing wrong is a claim about origin that the merge can check and the
#     schema cannot.
#
# EVERY MEMBER HAS A PRODUCER, which is ADR-28 dec. 4's rule applied to a local
# type rather than a contract one. ``evidence_incomplete`` was deliberately NOT
# declared at Part 1, when it had none; it is declared here, at the part that
# builds its gate.
RejectionReason = Literal[
    "not_a_finding",
    "schema_invalid",
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
    # carry more than one defect at once -- blank evidence AND a mislabelled
    # source is the reachable pair -- and exactly one is reported, decided by the
    # precedence written at ``receipt.validate_finding``. A consumer must not read
    # this as an exhaustive diagnosis: fixing the reason named here can reveal
    # another underneath it.
    #
    # SINGULAR RATHER THAN A TUPLE, DELIBERATELY. Reporting every defect was
    # considered and is not proposed, on two grounds. The reasons are mostly
    # SEQUENTIAL PRECONDITIONS rather than independent axes -- an object that is
    # not a Finding cannot be schema-checked, and one that fails the schema cannot
    # have its evidence read -- so "all defects" is only ever meaningful for the
    # single evidence/source pair, which is a small return for a shape change on a
    # type Step 3.3 will consume. And every sibling refusal type in this package
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
