"""W-5 assembly: the ``InspectionResult`` builder (System Design §1.1, ADR-20).

Layer 4 (§5): imports ``broker`` and ``contract`` ONLY. The adapter is held by
the session and the session by the broker, so the one legal data path is
``adapter -> session -> broker -> W-5`` (ADR-20 decision 1). Nothing here
touches HFSS, the filesystem, or the network; everything arrives through
``Broker.dispatch``.

ENTRY POINT vs. CAPABILITY NAME — the one naming collision worth stating
plainly, because both things are spelled ``inspect_design``:

  * ``inspect_design`` BELOW is W-5's entry point: a plain module-level
    function, deliberately NOT a registered capability. It does not appear in
    ``session_routed_specs`` and must not be added there. Registering it would
    put a second, differently-shaped ``inspect_design`` in the registry and
    audit an assembly step as if it were a tool call.
  * ``"inspect_design"`` as a REGISTERED CAPABILITY is the ``inspect_design``
    entry in ``session_routed_specs``, whose handler is the bound
    ``Session.inspect``. That is the name this module dispatches, and the only
    ``inspect_design`` the broker knows about. (Named, not numbered: that tuple
    grows — a positional reference would quietly go stale.)

So: one registered capability (the session read), one unregistered assembler
(this module) that calls it. W-5 adds ordering, completeness, provenance and
deterministic text on top of a read it never performs itself.

WHAT ASSEMBLY MEANS HERE. The session's success arm is the RAW
``dict[InspectionSectionName, InspectionSection]`` — it holds no
``template_text`` and no provenance (ADR-20 decision 4). This module adds
exactly three things and judges nothing (W-5 "does not judge or validate
anything it reads"):

  1. ORDER + COMPLETENESS — every requested section is present in
     ``_CANONICAL_ORDER``, with an explicitly synthesized ``not_readable``
     entry for any the read-out omitted, so a section is never silently
     dropped (ADR-20 decision 8).
  2. PROVENANCE — a six-field ``InspectionProvenance`` (ADR-21 decision 9),
     the honest structural-read record: no solve, metric, or judgment field
     exists on it to fill.
  3. ``template_text`` — deterministic counts and section names, no evaluative
     language, with an explicit closing statement that no assessment is made.

THE THREE-CALL ORDER, AND WHY THE ENVIRONMENT COMES LAST. One logical
inspection issues TWO dispatches — the read, then ``get_session_status`` for
the selection context provenance needs — so it produces two audit records (the
self-referential-log wrinkle already noted for ``get_audit_log``). The order is
fixed:

  1. ``inspect_design`` dispatch — the read;
  2. ``get_session_status`` dispatch — project/design for the stamp;
  3. ``Broker.require_environment()`` — the version fields.

Step 3 is last because it doubles as a FREE sentinel for "the session ended
between the read and the stamp", at zero audit cost: it is not dispatchable, so
it appends no record, and a session that ended constructs fresh internal state
WITHOUT the attach-time environment (``_SessionState``'s preserve-on-replace /
drop-on-construct rule), so the accessor raises. Bracketing the read with a
second status check was considered and rejected: it costs a third audit record
on every call, and there is no contract arm for "the read succeeded but its
provenance cannot be vouched for" — detecting a condition you cannot honestly
express is worse than not detecting it.

RESIDUAL GAP, NAMED RATHER THAN ENGINEERED AROUND. An UNOBSERVED process death
between the read and the stamp cannot be detected in-process. Both
``get_session_status`` and ``get_environment`` are pure reads of the session's
own internal state — neither makes an adapter call — so a process that died
silently, with no operation having yet faulted, still reports ATTACHED with its
attach-time environment intact. The sentinel above catches only a death the
session has already OBSERVED. Closing the gap would require a liveness ping or
an extra adapter round-trip on every inspection; both are deliberately not
done. What the record then claims stays narrowly true regardless — ``read_at``
is when the read happened and ``read_under_aedt_version`` is the version of the
process it was read from — so the stamp does not become a lie, it merely cannot
witness the death.

NEVER A FABRICATED PROVENANCE VALUE. There is no default, sentinel, "unknown",
empty string, or cached environment anywhere below. A missing source raises
``InspectionAssemblyError`` (with the underlying cause chained) and the sections
are discarded with it — an unstamped or half-stamped read-out is not a thing
this module can return.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import get_args

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
    InspectionProvenance,
    InspectionSection,
)
from hfss_agent.contract.tool_io import (
    CannotEvaluate,
    InspectDesignResult,
    InspectionResult,
    InspectionSectionName,
    SelectionRefused,
    SessionStatus,
)

# The REGISTERED capability names this module dispatches — the session-routed
# specs' names, not W-5's own (see the module docstring's naming note). Named
# once here so a registry rename surfaces as one edit rather than two string
# literals drifting apart.
_INSPECT_CAPABILITY = "inspect_design"
_STATUS_CAPABILITY = "get_session_status"

# Build order, per spec Point 8 as recorded in ADR-20 decision 8: the stages
# downstream consumers need first (ports, setups, sweeps, variables), then the
# rest in the order DesignSnapshot.Inspection declares them. ONE tuple governs
# every result — a subset request is presented in CANONICAL order, never
# request order, so two callers asking for the same sections in different
# orders get byte-identical output. A test asserts this is a permutation of the
# eight contract section names, so a section can neither go missing nor be
# invented here.
_CANONICAL_ORDER: tuple[InspectionSectionName, ...] = (
    "excitations_ports",
    "setups",
    "sweeps",
    "variables",
    "objects",
    "materials",
    "boundaries",
    "available_results",
)

# The eight names as a membership set, derived from the contract Literal (never
# retyped) so an unknown requested name is caught here rather than surfacing as
# a pydantic key error after the read has already run.
_SECTION_NAMES = frozenset(get_args(InspectionSectionName))

# The limitation W-5 writes for a REQUESTED section the read-out did not carry.
# Deliberately distinguishable from an adapter-produced limitation (ADR-20
# decision 8): it says who synthesized it and refuses to claim a PyAEDT
# limitation nobody reported. The alternative — dropping the section — would
# make an incomplete read look like a complete one, which is the failure this
# whole module is shaped against.
_SYNTHESIZED_LIMITATION = (
    "This section was requested but the inspection read-out did not contain "
    "it. The wrapper (W-5) recorded it as not_readable rather than dropping "
    "it, so nothing requested goes unreported. No PyAEDT limitation was "
    "reported for it, so WHY it is absent is not known — this entry was "
    "synthesized by the wrapper, not read from HFSS."
)

# Closing line of every template. W-5 does not judge: the read-out states what
# was read, and says so explicitly rather than leaving a reader to infer that
# silence about problems means there are none.
_NO_ASSESSMENT_NOTICE = (
    "This is a structural read-out only: it reports what was read and makes "
    "no assessment of the design."
)


class InspectionAssemblyError(Exception):
    """Assembly could not complete honestly, so nothing is reported.

    RAISED, NOT RETURNED — and that is forced by the contract, not a
    preference. ``InspectDesignResult``'s three arms are a complete
    ``InspectionResult``, a ``CannotEvaluate`` ("PyAEDT could not evaluate
    this") and a ``SelectionRefused`` ("a session gate declined before PyAEDT
    was reached"). None of them can say "the read itself succeeded, but its
    provenance cannot be vouched for". Borrowing ``CannotEvaluate`` would blame
    the solver for a wrapper-side problem — the exact misattribution ADR-16
    narrowed that type to prevent — and the contract is closed at 0.1.0, so no
    fourth arm exists to add one to.

    Every raise site therefore DISCARDS the sections it was holding. A read-out
    with an absent, defaulted, or stale provenance stamp is not a lesser result
    to fall back on; it is a record asserting something nobody verified, which
    is worse than no record at all.

    Two failure classes reach here, both wiring-or-lifecycle rather than user
    error: a dispatch that did not return the type its capability is declared
    to return (see ``_dispatch_boundary_error``), and a provenance source that
    is missing at stamp time (a session that ended, or a chain that no longer
    names the project and design the read ran against). The originating
    exception, where there is one, is chained as ``__cause__``.
    """


def inspect_design(
    broker: Broker,
    sections: list[InspectionSectionName] | None = None,
) -> InspectDesignResult:
    """Assemble the full structured design read-out (all eight sections when
    ``sections`` is None, else that subset in canonical order).

    Takes the ``Broker`` EXPLICITLY rather than reaching for a module-level or
    otherwise ambient one: the broker owns the session whose selection and
    environment this stamps, so a caller handing in a different broker than the
    one the read came from would stamp one session's versions onto another
    session's data. Passing it makes that pairing visible at every call site.

    Returns an ``InspectionResult`` on success, or passes the session's
    ``CannotEvaluate`` / ``SelectionRefused`` back VERBATIM. Raises
    ``InspectionAssemblyError`` when assembly cannot be completed honestly.
    """
    requested = _requested_sections(sections)

    # --- 1. the read ---------------------------------------------------------
    read = broker.dispatch(_INSPECT_CAPABILITY, {"sections": sections})
    # Stamped HERE, not after the second dispatch: this is the closest
    # observable instant to the completed read, so the stamp never drifts by
    # the cost of the get_session_status round trip that follows.
    read_at = datetime.now(timezone.utc)
    # NARROWING (1 of 2). ``dispatch`` is typed ``-> object``, so the arms are
    # checked, never assumed. The two contract arms pass straight through
    # untouched (below); everything else — UnknownCapability, DispatchRefused,
    # AuditFailure, or any unexpected type — is a DISPATCH-BOUNDARY failure and
    # raises. It is deliberately not folded into CannotEvaluate: none of those
    # is PyAEDT declining to evaluate anything.
    if isinstance(read, (CannotEvaluate, SelectionRefused)):
        # Verbatim, with NO assembly: a refusal or a failed read has no
        # sections to order, nothing to be complete about, and no honest
        # provenance to carry. Re-wrapping it would only add wrapper text over
        # a message the session already worded correctly.
        return read
    if not isinstance(read, dict):
        raise _dispatch_boundary_error(_INSPECT_CAPABILITY, read)

    # --- 2. selection context, for provenance --------------------------------
    status = broker.dispatch(_STATUS_CAPABILITY)
    # NARROWING (2 of 2). The SAME boundary as above and treated the same way:
    # get_session_status can return UnknownCapability, DispatchRefused or
    # AuditFailure just as inspect_design can. Narrowed here so an unexpected
    # value raises as what it is — a dispatch-boundary problem — instead of
    # falling through to _build_provenance's project/design check and being
    # reported as a selection-chain wiring bug.
    if not isinstance(status, SessionStatus):
        raise _dispatch_boundary_error(_STATUS_CAPABILITY, status)

    # --- 3. versions, and the between-calls sentinel -------------------------
    try:
        environment = broker.require_environment()
    except NoAttachedSessionError as exc:
        raise InspectionAssemblyError(
            "the design was read, but the AEDT session ended before its "
            "provenance could be stamped, so the wrapper and AEDT versions "
            "the read ran under are no longer available. The read-out is "
            "discarded rather than reported with a missing or stale stamp; "
            "re-attach and inspect again."
        ) from exc

    provenance = _build_provenance(status, environment, read_at)
    ordered = _ordered_sections(read, requested)
    return InspectionResult(
        sections=ordered,
        provenance=provenance,
        template_text=_template_text(provenance, ordered),
    )


def _requested_sections(
    sections: list[InspectionSectionName] | None,
) -> tuple[InspectionSectionName, ...]:
    """The section names this call must account for: the caller's subset, or
    all eight when ``sections`` is None.

    An unknown name is rejected BEFORE the read runs. Checking after would mean
    either synthesizing a ``not_readable`` entry under a key the contract's
    Literal cannot hold (a pydantic error blaming the schema for a caller's
    typo) or dropping it silently — and dropping a requested section is exactly
    what the completeness pass exists to prevent.
    """
    if sections is None:
        return _CANONICAL_ORDER
    unknown = [name for name in sections if name not in _SECTION_NAMES]
    if unknown:
        raise InspectionAssemblyError(
            f"unknown inspection section name(s) requested: {sorted(unknown)}. "
            f"Valid sections: {sorted(_SECTION_NAMES)}."
        )
    return tuple(sections)


def _ordered_sections(
    read: dict[object, object],
    requested: tuple[InspectionSectionName, ...],
) -> dict[InspectionSectionName, InspectionSection]:
    """Every requested section, in ``_CANONICAL_ORDER``, with a synthesized
    ``not_readable`` entry for any the read-out omitted.

    Iteration is over the canonical tuple rather than over ``read``, which is
    what makes both guarantees fall out of one loop: the output order cannot
    depend on the adapter's dict order, and a missing key is impossible to
    overlook because the loop visits it regardless.

    Sections present in ``read`` but NOT requested are not reported. That is
    not a silent drop: the request defines the result, and when no subset was
    given the requested set IS all eight, so an extra key could only be a name
    outside the contract's Literal — which ``InspectionResult`` could not carry
    anyway.
    """
    wanted = set(requested)
    ordered: dict[InspectionSectionName, InspectionSection] = {}
    for name in _CANONICAL_ORDER:
        if name not in wanted:
            continue
        if name not in read:
            ordered[name] = InspectionSection(
                data=None,
                read_status="not_readable",
                limitation=_SYNTHESIZED_LIMITATION,
            )
            continue
        section = read[name]
        if not isinstance(section, InspectionSection):
            # A wrong-typed value is a wiring bug, not an unreadable section.
            # Synthesizing a not_readable here would quietly relabel a broken
            # read path as a PyAEDT gap and hide the bug in normal output.
            raise InspectionAssemblyError(
                f"the '{_INSPECT_CAPABILITY}' read-out carried a "
                f"{type(section).__name__} for section '{name}' where an "
                "InspectionSection was required; the read-out is discarded "
                "rather than reported around a value of unknown meaning."
            )
        ordered[name] = section
    return ordered


def _build_provenance(
    status: SessionStatus,
    environment: Environment,
    read_at: datetime,
) -> InspectionProvenance:
    """The six-field honest stamp for a structural read (ADR-21 decision 9).

    Three sources, each the only honest one for its fields, none of them
    substitutable:

      * the SESSION'S OWN CHAIN (via ``get_session_status``) — ``project`` and
        ``design``, the two selections the read was scoped to;
      * the ATTACH-TIME ``Environment`` (via the broker's read-through
        accessor) — ``wrapper_version``, and ``aedt_version`` as
        ``read_under_aedt_version``, which is honest precisely because the
        accessor re-reads it from the live session rather than caching it;
      * the contract's own ``CONTRACT_VERSION`` — the schema version that
        shaped this record.

    ``read_at`` is passed in rather than taken here, because the honest instant
    is when the READ happened, not when the stamp was assembled.

    A chain that no longer names both a project and a design raises. The read
    could not have run without both (the session's own selection gate), so
    their absence means the selection changed between the read and this stamp —
    and there is no truthful value to substitute: the last-known name might no
    longer be what was read, and the current chain never was.
    """
    project = status.selection.project
    design = status.selection.design
    if project is None or design is None:
        missing = " and ".join(
            name
            for name, value in (("project", project), ("design", design))
            if value is None
        )
        raise InspectionAssemblyError(
            "the design was read, but the session's selection chain no longer "
            f"names a {missing}, so the read-out cannot be attributed to what "
            "it was read from. The selection must have changed between the "
            "read and the stamp. The read-out is discarded rather than "
            "attributed to a guess; re-select and inspect again."
        )
    return InspectionProvenance(
        project=project.name,
        design=design,
        read_at=read_at,
        contract_version=CONTRACT_VERSION,
        wrapper_version=environment.wrapper_version,
        read_under_aedt_version=environment.aedt_version,
    )


def _template_text(
    provenance: InspectionProvenance,
    sections: dict[InspectionSectionName, InspectionSection],
) -> str:
    """The deterministic core text (§3): complete without any LLM.

    BYTE-DETERMINISTIC AND TIMESTAMP-FREE, both deliberately. The same read
    rendered twice must produce identical bytes, so tests can pin the wording
    and a diff between two read-outs shows only what actually changed in the
    design — a ``read_at`` echoed here would make every pair of read-outs
    differ. The instant is not lost: it lives in ``provenance.read_at``, typed
    and machine-readable, which is the right home for it. Determinism holds
    because ``sections`` arrives in canonical order, so both name lists below
    are ordered by construction rather than by dict insertion luck.

    NO EVALUATIVE LANGUAGE (W-5 does not judge). Counts and section names only:
    nothing here calls a design fine, complete, healthy, or problematic, and
    the closing notice states outright that no assessment was made — so silence
    about problems is never mistaken for a clean bill of health.

    ``project`` and ``design`` are untrusted HFSS-sourced strings (pre-sanitized
    at the adapter, ADR-9) and are rendered inside quotes as data, never in an
    instruction position (§6.6).
    """
    read = [name for name, section in sections.items() if section.read_status == "ok"]
    not_readable = [
        name for name, section in sections.items() if section.read_status != "ok"
    ]
    parts = [
        f'Inspection read-out for project "{provenance.project}", design '
        f'"{provenance.design}": {len(sections)} section(s) requested, '
        f'{len(read)} with read_status "ok", {len(not_readable)} '
        '"not_readable".'
    ]
    if read:
        parts.append("Read: " + _quoted(read) + ".")
    if not_readable:
        parts.append(
            "Not readable: "
            + _quoted(not_readable)
            + ". Each names its own limitation."
        )
    parts.append(_NO_ASSESSMENT_NOTICE)
    return " ".join(parts)


def _quoted(names: list[InspectionSectionName]) -> str:
    """Section names as quoted, comma-separated data. These are wrapper-owned
    contract literals, not untrusted input; the quoting is for legibility and
    for consistency with how the untrusted names beside them are framed."""
    return ", ".join(f'"{name}"' for name in names)


def _dispatch_boundary_error(
    capability: str, result: object
) -> InspectionAssemblyError:
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
            f"'{result.name}'. W-5 requires a broker built with the "
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
            "read is not reported as a clean one"
        )
    else:
        detail = (
            f"the dispatch returned a {type(result).__name__}, which is not a "
            "result type this capability is declared to return"
        )
    return InspectionAssemblyError(
        f"dispatching '{capability}' did not produce a usable result: "
        f"{detail}. No read-out is reported: this is a dispatch-boundary "
        "problem, not a PyAEDT limitation, and reporting it as one would "
        "misattribute a wrapper-side failure to the solver."
    )
