"""W-6 assembly: the ``NativeValidationBlock`` builder (System Design §1.1, ADR-23).

Layer 4 (§5): imports ``broker`` and ``contract`` ONLY. The adapter is held by
the session and the session by the broker, so the one legal data path is
``adapter -> session -> broker -> W-6``, exactly as ADR-20 decision 1 fixed it
for W-5. Nothing here touches HFSS, the filesystem, or the network; everything
arrives through ``Broker.dispatch``.

THREE NAMES, TWO OF WHICH COLLIDE — stated plainly, because W-5 set the
precedent of disclosing this rather than renaming around it:

  * ``validate_native`` BELOW is W-6's entry point: a plain module-level
    function, deliberately NOT a registered capability. It does not appear in
    ``session_routed_specs`` and must not be added there. Registering it would
    put a second, differently-shaped ``validate_native`` in the registry and
    audit an assembly step as if it were a tool call.
  * ``"validate_native"`` as a REGISTERED CAPABILITY is the ``validate_native``
    entry in ``session_routed_specs``, whose handler is the bound
    ``Session.validate_native``. That is the name this module dispatches, and
    the only ``validate_native`` the broker knows about.
  * ``validate_setup`` is the TOOL (§3 ``ValidateSetupRequest`` /
    ``ValidateSetupResult``), and it does not exist yet — Step 3.3 builds it on
    top of this module. A reader looking for a tool named ``validate_native``
    should stop looking: there is none. The collision here is milder than
    W-5's, where the tool name is a third use of the same spelling.

WHAT ASSEMBLY MEANS HERE. The session's success arm is the RAW
``NativeValidation`` — HFSS's message list and its ``source`` attribution, with
no provenance attached. This module adds exactly one thing and judges nothing:
it pairs that list with a ``NativeValidationProvenance`` for the run, inside a
``NativeValidationBlock``. It does not rephrase, filter, rank, reorder, or
interpret the messages, and reads nothing inside them.

Note what is NOT on that list: ordering and completeness, which are W-5's other
two jobs, have no counterpart here. There is no canonical order to impose — the
order is HFSS's own and re-imposing one would be ranking — and nothing can be
missing from a message list, because the list IS the result. An empty
``raw_output`` is a completed run that reported nothing, never an incomplete
one.

WHERE ``template_text`` ACTUALLY LIVES — a correction worth stating, because
ADR-23 decision 15 and the runbook both describe "W-6's template_text" as
though it were a field on this module's output. It is not, and cannot be:
``NativeValidationBlock`` declares exactly ``validation`` and ``provenance``
under ``extra="forbid"``, so a third key raises. ``template_text`` is a field on
``ValidationReport``, whose other two fields are ``findings`` and
``engine_status`` — it is the text for the WHOLE validate_setup response, and
that response is Step 3.3's.

So the native wording lives here as ``native_template_text``: a pure
``block -> str`` function, deterministic, public, and Step 3.3's to compose with
the findings paragraph and the engine notice. It is here rather than in Step 3.3
because the commitments it has to keep — the unconditional sanitization
statement, the rule against branching on untrusted content, the framing of
messages as data — are properties of the native block, and this is the module
that owns it and has the six-fixture ledger to test against. It is called only
by this module's tests until Step 3.3 lands; that is a deliberate trade, not an
oversight.

THE THREE-CALL ORDER, AND WHY THE ENVIRONMENT COMES LAST. One logical
validation issues TWO dispatches — the run, then ``get_session_status`` for the
selection context provenance needs — so it produces two audit records, the same
acknowledged cost W-5 carries. The order is fixed:

  1. ``validate_native`` dispatch — the run;
  2. ``get_session_status`` dispatch — project/design for the stamp;
  3. ``Broker.require_environment()`` — the version fields.

Step 3 is last because it doubles as a FREE sentinel for "the session ended
between the run and the stamp", at zero audit cost: it is not dispatchable, so
it appends no record, and a session that ended constructs fresh internal state
WITHOUT the attach-time environment, so the accessor raises.

``validated_under_aedt_version`` matters MORE here than its W-5 counterpart
does, and the difference is worth knowing: ValidateDesign's BEHAVIOUR is
version-dependent in a way that reading a design's structure is not — a
different AEDT version may emit different messages for the same design — so the
version is part of what makes the messages interpretable at all. It remains a
PRODUCT version and never a rule version; nothing here may present it as one.

RESIDUAL GAP, NAMED RATHER THAN ENGINEERED AROUND. An UNOBSERVED process death
between the run and the stamp cannot be detected in-process: both
``get_session_status`` and ``get_environment`` are pure reads of the session's
own internal state, so a process that died silently still reports ATTACHED with
its attach-time environment intact. The sentinel above catches only a death the
session has already OBSERVED. What the record claims stays narrowly true
regardless — ``validated_at`` is when the validator ran, and
``validated_under_aedt_version`` is the version of the process it ran on.

NEVER A FABRICATED PROVENANCE VALUE. There is no default, sentinel, "unknown",
empty string, or cached environment anywhere below. A missing source raises
``NativeValidationAssemblyError`` (with the underlying cause chained) and the
messages are discarded with it — an unstamped or half-stamped validation is not
a thing this module can return.
"""

from __future__ import annotations

from datetime import datetime, timezone

from hfss_agent.broker import (
    AuditFailure,
    Broker,
    DispatchRefused,
    NoAttachedSessionError,
    UnknownCapability,
)
from hfss_agent.contract import (
    CONTRACT_VERSION,
    Environment,
    NativeValidation,
    NativeValidationProvenance,
)
from hfss_agent.contract.tool_io import (
    CannotEvaluate,
    NativeValidationBlock,
    SelectionRefused,
    SessionStatus,
)

# The REGISTERED capability names this module dispatches — the session-routed
# specs' names, not W-6's own (see the module docstring's naming note). Named
# once here so a registry rename surfaces as one edit rather than two string
# literals drifting apart.
_VALIDATE_CAPABILITY = "validate_native"
_STATUS_CAPABILITY = "get_session_status"

# The zero-message line. It exists because silence would be read as a verdict:
# a run that reported nothing is a COMPLETED run, and a reader who sees only
# "0 message(s)" will supply "so the design is fine" on their own. ADR-23 names
# this the misread most worth guarding, so the text refuses the inference out
# loud instead of leaving room for it.
_NO_MESSAGES_NOTICE = (
    "The validator ran and returned no messages. That is what it reported; the "
    "wrapper draws no conclusion from it."
)

_MESSAGES_HEADING = "Messages, in the order HFSS emitted them:"

# CONSOLIDATED FROM THREE SENTENCES TO TWO, deliberately. Five paragraphs of
# disclaimer wrapped around one line of content teaches a reader to skip the
# disclaimer, which costs more honesty than the extra words buy. Every
# substantive commitment survives the trim: unmodified passthrough, the
# sanitization statement, the marker's non-authenticity, the
# presentation-is-not-structure warning, and the attribution of judgment.
#
# WHY THE SANITIZATION STATEMENT IS UNCONDITIONAL — the reasoning lives here, at
# whatever length it needs, rather than in the rendered text. Nothing in this
# module computes whether stripping or truncation actually took effect on this
# payload, and nothing may: our truncation marker is NOT authenticatable.
# Instruction-like text passes through unrewritten (the sanitizer neutralizes
# hostile content by framing and typing it, never by rewriting it), so an HFSS
# message can contain the marker's exact wording. A conditional notice would
# therefore have to branch on untrusted content to decide what to say about
# itself — letting an attacker-writable string steer the wrapper's own
# disclosure, which is exactly what ADR-9 forbids. Stating it every time costs
# one clause and cannot be gamed.
#
# The cap's NUMERIC value is deliberately absent. ``MAX_UNTRUSTED_STR_LEN``
# lives in ``hfss_agent.adapter.sanitize``, which this layer may not import
# (Layer 4 reaches the adapter only through the broker), and hardcoding 10 000
# here would let the text drift silently the day the cap moves. Naming a number
# we cannot read would be worse than not naming it.
_PASSTHROUGH_NOTICE = (
    "The wrapper passes HFSS's messages through unchanged and reads nothing "
    "inside them; on every result, control characters other than tab and "
    "newline are stripped and each message is individually length-capped with "
    "a visible truncation marker, which proves nothing on its own because a "
    "message can contain that wording verbatim."
)

# WHY THE PRESENTATION WARNING EXISTS — the numbering and quoting are SPOOFABLE,
# and no delimiter fixes that. Tab and newline survive sanitization (they are
# real structure in a multi-line solver message), so ONE hostile message can
# contain a newline followed by a convincing '[2] "..."' and render as two
# apparent entries; a message containing a double quote breaks the quoting the
# same way. There is no delimiter safe against arbitrary text, and inventing an
# escaping scheme would mean rewriting HFSS's output, which this module does not
# do. The honest fix is to say plainly that the rendered shape is presentation,
# and to point at what is authoritative instead: the count on the first line and
# ``raw_output`` itself. A test pins this with a message that fakes an entry.
_PRESENTATION_NOTICE = (
    "Message numbering and quoting are presentation only, not a parseable "
    "structure — raw_output is the machine-readable list — and any judgment in "
    "a message is HFSS's, not the wrapper's, which makes no assessment of this "
    "design."
)


class NativeValidationAssemblyError(Exception):
    """Assembly could not complete honestly, so nothing is reported.

    RAISED, NOT RETURNED, and forced by the contract rather than chosen. The
    three arms ``validate_native`` can return are a complete
    ``NativeValidationBlock``, a ``CannotEvaluate`` ("PyAEDT could not evaluate
    this") and a ``SelectionRefused`` ("a session gate declined before PyAEDT
    was reached"). None of them can say "the validation ran, but its provenance
    cannot be vouched for". Borrowing ``CannotEvaluate`` would blame the solver
    for a wrapper-side problem — the exact misattribution ADR-16 narrowed that
    type to prevent.

    Every raise site DISCARDS the messages it was holding. A block with an
    absent, defaulted, or stale provenance stamp is not a lesser result to fall
    back on; it is a record asserting something nobody verified.

    A DELIBERATE DUPLICATE OF ``InspectionAssemblyError``, and the duplication
    is not an oversight to be cleaned up later. Four reasons, in order:

      1. Sharing is structurally impossible. W-6 may not import
         ``hfss_agent.inspect`` — the import audits forbid it in both
         directions, because two Layer-4 siblings are peers and neither may
         depend on the other.
      2. There is no legal shared home. The only root both may import is
         ``contract``, and an assembler-domain exception is not a contract
         schema: the contract subpackage carries no behaviour beyond validation
         (W-12) and is closed at its current version. ``broker`` is worse — the
         broker must not know its consumers exist.
      3. The messages must differ materially. W-5's say "no read-out is
         reported"; these must say no VALIDATION RESULT is reported, and must
         never call the run a "read".
      4. Catching one must not catch the other. Step 3.3 composes findings over
         W-6, and ``export_diagnostics_bundle`` later composes ``inspect`` AND
         ``validate_native`` in one operation; a caller holding both needs to
         know which assembly failed, and a shared base class would let one bare
         ``except`` swallow the wrong one.

    A future maintainer tempted to unify the two must first find a package both
    may legally import. Today there is none.
    """


def validate_native(
    broker: Broker,
) -> NativeValidationBlock | CannotEvaluate | SelectionRefused:
    """Run HFSS's own validation and pair its messages with the provenance of
    the run.

    Takes the ``Broker`` EXPLICITLY rather than reaching for a module-level or
    otherwise ambient one: the broker owns the session whose selection and
    environment this stamps, so a caller handing in a different broker than the
    run came from would stamp one session's versions onto another session's
    messages. Passing it makes that pairing visible at every call site.

    Returns a ``NativeValidationBlock`` on success, or passes the session's
    ``CannotEvaluate`` / ``SelectionRefused`` back VERBATIM. Raises
    ``NativeValidationAssemblyError`` when assembly cannot be completed
    honestly.

    Takes no request argument. ``ValidateSetupRequest``'s one field,
    ``include_supplemental``, governs whether ENGINE and GATE findings join the
    report — W-6 produces no findings at all (ADR-23), so the flag is
    meaningless here and belongs to Step 3.3.
    """
    # --- 1. the run ----------------------------------------------------------
    result = broker.dispatch(_VALIDATE_CAPABILITY, {})
    # Stamped HERE, not after the second dispatch: the contract defines
    # validated_at as the instant the validation call RETURNED, so the stamp
    # must not drift by the cost of the get_session_status round trip that
    # follows.
    validated_at = datetime.now(timezone.utc)
    # NARROWING (1 of 2). ``dispatch`` is typed ``-> object``, so the arms are
    # checked, never assumed. The two contract arms pass straight through
    # untouched (below); everything else — UnknownCapability, DispatchRefused,
    # AuditFailure, or any unexpected type — is a DISPATCH-BOUNDARY failure and
    # raises. It is deliberately not folded into CannotEvaluate: none of those
    # is PyAEDT declining to evaluate anything.
    if isinstance(result, (CannotEvaluate, SelectionRefused)):
        # Verbatim, with NO assembly: a refusal or a failed run has no messages
        # to carry and no honest provenance to stamp — a stamp on a run that did
        # not happen asserts a project, design, instant and AEDT version for an
        # event that never occurred. Routed on TYPE, never on which refusal tag
        # was set: the session emits two of the three tags today, and a
        # tag-enumerating branch here would need editing (and would fail
        # silently, by falling through to assembly) the day a gate learns a
        # third.
        return result
    if not isinstance(result, NativeValidation):
        raise _dispatch_boundary_error(_VALIDATE_CAPABILITY, result)

    # --- 2. selection context, for provenance --------------------------------
    status = broker.dispatch(_STATUS_CAPABILITY)
    # NARROWING (2 of 2). The SAME boundary as above and treated the same way,
    # so an unexpected value raises as what it is — a dispatch-boundary problem
    # — instead of falling through to _build_provenance's project/design check
    # and being reported as a selection-chain wiring bug.
    if not isinstance(status, SessionStatus):
        raise _dispatch_boundary_error(_STATUS_CAPABILITY, status)

    # --- 3. versions, and the between-calls sentinel -------------------------
    try:
        environment = broker.require_environment()
    except NoAttachedSessionError as exc:
        raise NativeValidationAssemblyError(
            "HFSS validated the design, but the AEDT session ended before the "
            "run's provenance could be stamped, so the wrapper and AEDT "
            "versions it ran under are no longer available. The messages are "
            "discarded rather than reported with a missing or stale stamp; "
            "re-attach and validate again."
        ) from exc

    return NativeValidationBlock(
        validation=result,
        provenance=_build_provenance(status, environment, validated_at),
    )


def native_template_text(block: NativeValidationBlock) -> str:
    """The deterministic native paragraph (§3): complete without any LLM.

    A pure function of the block — see the module docstring for why this is a
    function here rather than a field on ``NativeValidationBlock``, and why
    Step 3.3 rather than W-6 owns the ``ValidationReport.template_text`` it
    will become part of.

    BYTE-DETERMINISTIC AND TIMESTAMP-FREE, both deliberately, following W-5.
    The same block rendered twice produces identical bytes, so tests can pin the
    wording and a diff between two results shows only what HFSS actually said
    differently. ``validated_at`` is never echoed here: the instant lives in
    ``provenance.validated_at``, typed and machine-readable, which is the right
    home for it. Determinism holds structurally — ``raw_output`` is an ordered
    list, iterated in order, with no sort, dedup, set, or dict iteration
    anywhere on this path.

    THE MESSAGES ARE RENDERED, and that is the deliberate resolution of this
    module's central asymmetry: W-5 does not judge AND its content does not
    judge, whereas W-6 does not judge but ITS CONTENT IS HFSS'S JUDGMENT.
    Omitting the messages would make the text a receipt for content it withholds
    — §3 requires the deterministic text to be complete without an LLM, and the
    messages ARE this tool's content. They are untrusted, so they are rendered
    the way ADR-9 §6.6 prescribes untrusted text be rendered: inside explicit
    delimiters, individually quoted, numbered, under a label attributing them to
    HFSS. Framing is ADR-9's remedy; censorship is not — the sanitizer itself
    states that hostile content is neutralized by typing and framing, never by
    rewriting.

    THERE IS NO LENGTH CAP ON THIS RENDERING. Capping would require choosing
    which messages to drop, which is ranking, which this module does not do. The
    length is bounded only by what HFSS emitted and by the sanitizer's
    per-message cap.

    ONLY A TOTAL COUNT IS RENDERED — ``N message(s)``, never "0 errors" or "2
    warnings". ``len(raw_output)`` is a property of the LIST, computable with
    every message sealed; a severity count would require classifying each
    message by reading its text, which is where passing output through stops and
    judging it begins. (``NativeValidationProvenance`` forbids any such count as
    a FIELD for that reason and for one more: provenance describes the run,
    while a count describes the payload the block already carries in full.)
    """
    messages = block.validation.raw_output
    parts = [
        f'Native HFSS validation for project "{block.provenance.project}", '
        f'design "{block.provenance.design}": HFSS\'s own validator returned '
        f"{len(messages)} message(s)."
    ]
    if messages:
        parts.append(_MESSAGES_HEADING)
        # Numbering is wrapper-added structure derived from LIST POSITION, never
        # from content — and it earns its keep, because a sanitized message may
        # itself contain newlines, so line breaks alone cannot delimit entries.
        parts.extend(
            f'[{index}] "{message}"' for index, message in enumerate(messages, 1)
        )
    else:
        parts.append(_NO_MESSAGES_NOTICE)
    parts.append(_PASSTHROUGH_NOTICE)
    parts.append(_PRESENTATION_NOTICE)
    # Newline-joined, not space-joined as W-5's is: a message list IS a list, and
    # flattening it onto one line would misrepresent its shape.
    return "\n".join(parts)


def _build_provenance(
    status: SessionStatus,
    environment: Environment,
    validated_at: datetime,
) -> NativeValidationProvenance:
    """The six-field honest stamp for one native validation run (ADR-23).

    Three sources, each the only honest one for its fields, none substitutable:

      * the SESSION'S OWN CHAIN (via ``get_session_status``) — ``project`` and
        ``design``, the two selections the run was scoped to;
      * the ATTACH-TIME ``Environment`` (via the broker's read-through
        accessor) — ``wrapper_version``, and ``aedt_version`` as
        ``validated_under_aedt_version``, honest precisely because the accessor
        re-reads it from the live session rather than caching it;
      * the contract's own ``CONTRACT_VERSION`` — the schema version that
        shaped this record.

    ``validated_at`` is passed in rather than taken here, because the honest
    instant is when the RUN returned, not when the stamp was assembled.

    ONE RECORD PER RUN, NEVER PER MESSAGE — and that is structural, not a rule
    to remember: ``NativeValidationBlock`` has a single ``provenance`` field and
    ``NativeValidation`` has none, so a per-message stamp is unconstructible.

    A chain that no longer names both a project and a design raises. The run
    could not have happened without both (the session's own selection gate), so
    their absence means the selection changed between the run and this stamp —
    and there is no truthful value to substitute: the last-known name might no
    longer be what was validated, and the current chain never was.
    """
    project = status.selection.project
    design = status.selection.design
    if project is None or design is None:
        missing = " and ".join(
            name
            for name, value in (("project", project), ("design", design))
            if value is None
        )
        raise NativeValidationAssemblyError(
            "HFSS validated the design, but the session's selection chain no "
            f"longer names a {missing}, so the messages cannot be attributed to "
            "what they were produced from. The selection must have changed "
            "between the run and the stamp. The messages are discarded rather "
            "than attributed to a guess; re-select and validate again."
        )
    return NativeValidationProvenance(
        project=project.name,
        design=design,
        validated_at=validated_at,
        contract_version=CONTRACT_VERSION,
        wrapper_version=environment.wrapper_version,
        validated_under_aedt_version=environment.aedt_version,
    )


def _dispatch_boundary_error(
    capability: str, result: object
) -> NativeValidationAssemblyError:
    """The error for a dispatch that did not return what its capability is
    declared to return — built for BOTH dispatches, so the two boundaries can
    never drift into reporting the same problem two different ways.

    Each broker-domain outcome is named specifically rather than collapsed into
    "unexpected value": these are distinguishable conditions with distinguishable
    fixes (a registry missing a capability, a tier gate refusing, a sink that
    could not write), and an assembly failure a maintainer cannot diagnose from
    its message is a failure twice.
    """
    if isinstance(result, UnknownCapability):
        detail = (
            f"the broker's registry holds no capability named "
            f"'{result.name}'. W-6 requires a broker built with the "
            "session-routed capabilities"
        )
    elif isinstance(result, DispatchRefused):
        detail = (
            f"the dispatch was refused at the {result.tier}-tier gate before "
            f"the handler ran: {result.reason}"
        )
    elif isinstance(result, AuditFailure):
        detail = (
            "the call completed but its audit record could not be written, so "
            f"the broker withheld the result ({result.detail}). An unaudited "
            "call is not reported as a clean one"
        )
    else:
        detail = (
            f"the dispatch returned a {type(result).__name__}, which is not a "
            "result type this capability is declared to return"
        )
    return NativeValidationAssemblyError(
        f"dispatching '{capability}' did not produce a usable result: "
        f"{detail}. No validation result is reported: this is a "
        "dispatch-boundary problem, not a PyAEDT limitation, and reporting it "
        "as one would misattribute a wrapper-side failure to the solver."
    )
