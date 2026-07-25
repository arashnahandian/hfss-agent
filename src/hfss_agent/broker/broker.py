"""W-4 · Broker — the dispatch pipeline: tier gate -> confirmation -> handler
-> audit.

Every tool-level capability invocation flows through ``Broker.dispatch``. The
broker holds the ``Session`` — the only holder above Layer 2 — and the session
holds the adapter, so every adapter call is *caused by* a broker dispatch even
though the session drives the adapter directly (ADR-18 decision 4; ADR-19
routing reading).

File-I/O boundary (approved plan §13): the dispatch pipeline itself performs
no file I/O. Every file operation lives in ``broker/files`` (Part 3) and is
reached only through the write primitives there — via the intent capabilities
and the export write primitive below — while audit records leave through the
injected ``AuditSink`` protocol and nowhere else (Part 4 implements it as the
real append-only JSONL writer; tests inject an in-memory recorder).

The locked dispatch order:

  1. registry lookup — an unknown name is a typed ``UnknownCapability`` and IS
     audited (gap 9, amended): one record with ``risk_tier=None`` and
     ``outcome="unknown_capability"``, under ``tool_name`` = the SANITIZED
     attempted name. Previously this path appended nothing, because
     ``AuditRecord.risk_tier`` was required and the schema could not express "a
     capability that isn't registered was requested" — while fabricating a tier
     would have been worse ("safe" is a false claim about an unknown thing;
     "high" would pollute the high-tier refusal trail). The amendment makes the
     absent tier representable instead, so the log no longer carries a silent
     exception to "every dispatch attempt is audited". That matters because an
     unregistered-name dispatch is exactly what a bypass attempt or a wiring
     bug looks like — the one thing you most want on the record. Unreachable
     over MCP (Step 2.8 exposes only registered tools); the path exists for
     in-process callers.
  2. HIGH tier: refused unconditionally, before the confirmer is consulted and
     before the handler is reachable. ADR-5 requires the tier's full guard set
     at the enforcement point, and the high tier's guards include a pre-change
     snapshot + rollback path (ADR-6) whose snapshot provider does not exist
     in the MVP. Tier 2.3 cannot ship a high-tier tool without wiring that
     provider in here — a relocation of the guard's inputs, not a retrofit.
  3. MEDIUM tier: per-action confirmation; refusal never reaches the handler.
  4. Selection state is captured BEFORE the handler runs — the audit records
     the state the call ran under, not the state it produced.
  5. The handler runs under ``time.perf_counter`` timing. ``duration``
     measures HANDLER EXECUTION ONLY, in seconds (the unit is pinned here,
     not by the contract — gap 4): 0.0 on a refusal record means the handler
     never ran. Confirmation latency is deliberately NOT captured — accurate
     today only because ``RefuseAllConfirmer`` returns instantly. When Tier
     2.3 introduces a confirmation channel a human can sit on for minutes,
     whether ``duration`` should include that wait needs an explicit decision
     (flagged for Tier 2.3), not a silent change of the field's meaning.
  6. The outcome is classified (total classifier), the ``AuditRecord`` is
     handed to the sink, and the result is returned. A sink failure fails
     closed: the result is withheld and a loud ``AuditFailure`` returned.

Gap 8 (amended): a ``select`` whose adapter call faulted returns a
``SessionStatus`` — a normal response shape — and therefore still audits
``outcome="ok"``. What used to make that indistinguishable from a clean select
was that the record carried no health signal at all; it now carries
``session_degraded``, a DELTA over the health rank taken before and after the
handler (see ``_health_rank``). A clean select records ``False``, a select that
drove the session SUSPECT records ``True``, and the outcome field is left
meaning exactly what it always meant.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import ClassVar, Protocol

from hfss_agent.adapter.sanitize import sanitize_result, sanitize_str
from hfss_agent.broker.audit.reader import read_audit_records
from hfss_agent.broker.audit.writer import AuditLogWriter
from hfss_agent.broker.confirmation import ConfirmationRequest, Confirmer
from hfss_agent.broker.files.intent_store import IntentStore
from hfss_agent.broker.files.locations import default_audit_log_path
from hfss_agent.broker.files.paths import validate_export_path
from hfss_agent.broker.files.writes import atomic_replace_write, exclusive_create_write
from hfss_agent.broker.registry import CapabilityRegistry, CapabilitySpec
from hfss_agent.contract import (
    AuditOutcome,
    AuditRecord,
    Environment,
    IntentObject,
    RiskTier,
)
from hfss_agent.contract.tool_io import (
    AuditLog,
    AuditLogRange,
    CannotEvaluate,
    DesignIntentState,
    ExportRefused,
    ExportWritten,
    MetricsRefused,
    SelectionChain,
    SelectionRefused,
    SessionStatus,
)
from hfss_agent.session import Session

# Why high tier cannot run in the MVP (revision 1 of the approved plan). Names
# the ADRs and the missing artifact so the refusal is self-explaining.
_HIGH_TIER_REFUSAL = (
    "high-tier capabilities are refused unconditionally in the MVP. ADR-5 "
    "requires the tier's full guard set at its enforcement point, and the "
    "high tier's guards include a pre-change snapshot and rollback path "
    "(ADR-6) whose snapshot provider does not exist yet. No confirmation can "
    "override this refusal; Tier 2.3 must wire a snapshot provider into the "
    "dispatch before a high-tier capability can run."
)


class AuditSink(Protocol):
    """Where dispatch audit records go — their ONLY exit (Part 2 holds no
    file I/O anywhere). Part 4's append-only JSONL writer implements this;
    tests inject an in-memory recorder."""

    def append(self, record: AuditRecord) -> None: ...


# --- broker-domain outcomes ---------------------------------------------------
# Deliberately NOT contract schemas, mirroring the adapter's outcome types
# (adapter/results.py): they carry dispatch semantics the wrapper->engine
# contract does not model and never travel to the engine.


@dataclass(frozen=True)
class BrokerOutcome:
    """Base marker for the broker's own "not the handler's result" outcomes.

    ``status`` is a per-class discriminator carried as a ``ClassVar`` (not an
    instance field) so it never participates in dataclass field ordering.
    """

    status: ClassVar[str]


@dataclass(frozen=True)
class UnknownCapability(BrokerOutcome):
    """Dispatch of a name the registry does not hold — a programming error (or
    a bypass attempt) at the call site, not a user refusal.

    AUDITED since the gap-9 amendment, as ``outcome="unknown_capability"`` with
    ``risk_tier=None`` — the schema can now say "an unregistered capability was
    requested" without inventing a tier for it. See module docstring point 1.
    The echoed name is caller-supplied, so it is sanitized before it lands in a
    rendered message OR in the log."""

    status: ClassVar[str] = "unknown_capability"
    name: str


@dataclass(frozen=True)
class DispatchRefused(BrokerOutcome):
    """The dispatch refused to run the handler: the unconditional high-tier
    refusal, or a medium-tier confirmation that was not granted. Audited as
    ``refused_by_gate`` under the documented broadened reading — "refused by a
    wrapper gate or guard" (ADR-19; plan §10 decision 2)."""

    status: ClassVar[str] = "refused"
    capability: str
    tier: RiskTier
    reason: str


@dataclass(frozen=True)
class AuditFailure(BrokerOutcome):
    """The sink could not write the audit record AFTER the dispatch already
    completed. Returned INSTEAD of the result — the fail-closed stance of plan
    §7: an operation that cannot be audited is never reported as a clean one,
    and ``notice`` states plainly what did and did not happen."""

    status: ClassVar[str] = "audit_failed"
    capability: str
    unaudited_outcome: AuditOutcome
    detail: str
    notice: str


class NoAttachedSessionError(Exception):
    """Attach-established metadata was asked for while no session is attached —
    never attached, or the session was lost.

    RAISED, not returned as a ``BrokerOutcome``: the outcome types above travel
    back through ``dispatch``, which audits and classifies them. The control-plane
    accessor that raises this is deliberately NOT dispatchable, so it has no
    audited result arm to carry a refusal through — an exception is the honest
    shape. Broker-domain like ``BrokerFileError`` (and named the same way: the
    domain that failed, stated plainly), never a contract type — the
    wrapper->engine contract does not model broker access errors, and it is
    closed at 0.1.0.

    WHY RAISE RATHER THAN RETURN ``None``: the invariant is not "the version may
    or may not exist"; it is "the version exists whenever we are connected, and
    asking while disconnected is an invalid call". An Optional flattens those two
    into one shape and quietly invites a caller to stamp a missing version onto a
    record. Raising models the invariant as it actually is.
    """

    def __init__(self) -> None:
        super().__init__(
            "no AEDT session is attached, so there is no attach-time environment "
            "to report; attach to a running AEDT process first"
        )


def classify_outcome(result: object) -> AuditOutcome:
    """Map a dispatch result onto the pinned ``AuditOutcome`` enum. Total —
    every possible value classifies.

    ``refused_by_gate`` carries the documented broadened reading "refused by a
    wrapper gate or guard" (ADR-19; plan §10 decision 2). The reasoning:
    ADR-18 decision 6's precedent is that a knowing, documented mislabelling
    is recoverable in-band while ambiguity is not — and ``ok`` would hide a
    refusal, the one thing this log must never do (a refused overwrite must
    never look like a completed write).

    Broker-domain FAILURES surface as exceptions and are audited
    ``typed_error`` on the dispatcher's exception path; the ``BrokerOutcome``
    arm below is a defensive totality backstop should one ever be audited as a
    returned value.
    """
    if isinstance(result, CannotEvaluate):
        return "cannot_evaluate"
    # ORDER MATTERS (gap 9): UnknownCapability IS a BrokerOutcome, so this arm
    # must precede the backstop below — which is precisely where it used to be
    # caught, classifying an unregistered-name dispatch as typed_error. Moved
    # ahead of it, not merged into it: "the name isn't registered" and "a
    # broker-domain failure occurred" are different facts, and only the first
    # one is allowed to carry risk_tier=None (AuditRecord's both-or-neither
    # validator). Pinned by the totality test in test_dispatch.
    if isinstance(result, UnknownCapability):
        return "unknown_capability"
    # SelectionRefused sits with the other refusals, NOT with cannot_evaluate:
    # a session gate declined before PyAEDT was reached, which is precisely the
    # "refused by a wrapper gate or guard" reading. ``CannotEvaluate`` is checked
    # first only because it is the narrower, non-refusal claim — the two types are
    # disjoint, so this pair's order is documentation, not a correctness
    # dependency (unlike the BrokerOutcome ordering below, which is).
    if isinstance(
        result, (ExportRefused, MetricsRefused, SelectionRefused, DispatchRefused)
    ):
        return "refused_by_gate"
    # ORDER MATTERS: DispatchRefused IS a BrokerOutcome, so the refusal arm
    # above must precede this one — swapped, every refusal would silently
    # reclassify as typed_error and a refused overwrite would stop looking
    # like a refusal. Pinned by
    # test_classifier_is_total_including_broker_domain_backstop (test_dispatch).
    if isinstance(result, BrokerOutcome):
        return "typed_error"
    return "ok"


def _health_rank(status: SessionStatus) -> int:
    """Rank a session's health so "did this call worsen it" is a comparison
    (gap 8): clean(0) < suspect(1) < lost(2).

    Derived from the CONTRACT status, not the session's private ``_Health``, so
    the broker stays on the public surface. ``lost_cause`` is the exact LOST
    discriminator: ``build_status`` sets it only under LOST, while LOST and
    DETACHED both flatten to ``connection_health="disconnected"`` — so ranking
    on ``connection_health`` would score a never-attached session as badly as a
    dead one and mark every call on it degraded.

    DETACHED ranks 0 with ATTACHED deliberately: "no session" is not a degraded
    session, and a dispatch against one has nothing to worsen.
    """
    if status.lost_cause is not None:
        return 2
    if status.suspect:
        return 1
    return 0


class Broker:
    """The capability broker (W-4): sole gateway for every capability.

    Holds the session, registry, audit sink, and confirmer — all
    constructor-injected (the ``Session(adapter)`` pattern), so tests
    substitute any of them. The audit sink defaults to the REAL append-only
    JSONL writer under ``data_dir`` when none is injected.

    COMPOSITION CONTRACT: the registry's session-routed handlers must be bound
    to the SAME ``Session`` instance injected here (build them with
    ``session_routed_specs(session)``). The broker captures per-call selection
    state from its session; a mismatched pair would audit one session's state
    against another session's operations.
    """

    def __init__(
        self,
        *,
        session: Session,
        registry: CapabilityRegistry,
        audit_sink: AuditSink | None = None,
        confirmer: Confirmer,
        data_dir: str | None = None,
    ) -> None:
        self._session = session
        self._registry = registry
        self._confirmer = confirmer
        # ``data_dir`` (the Part 3 deferred item, wired now that the writer
        # consumes it) governs ONLY the default audit writer built here when
        # no sink is injected. The IntentStore keeps its own explicit path
        # injection: at composition (Step 2.8) both derive from the SAME
        # data_dir — ``IntentStore(default_intent_path(data_dir))`` alongside
        # ``Broker(data_dir=data_dir)`` — while tests point each at tmp_path.
        # An explicitly injected ``audit_sink`` wins and ``data_dir`` is then
        # unused.
        if audit_sink is None:
            audit_sink = AuditLogWriter(default_audit_log_path(data_dir))
        self._audit_sink = audit_sink

    def dispatch(
        self, name: str, arguments: dict[str, object] | None = None
    ) -> object:
        """Run capability ``name`` through the locked pipeline (module
        docstring); returns the handler's result or a typed broker outcome.

        The handler receives ``arguments`` EXACTLY as given: sanitization is
        applied to what the audit log and the confirmer render (ADR-9 reuse),
        never to what the capability computes on — the session and adapter own
        their own boundaries, and silently rewriting a caller's argument would
        make the executed call differ from the requested one.
        """
        args = dict(arguments) if arguments is not None else {}
        started = datetime.now(timezone.utc)
        sanitized = sanitize_result(args)
        # Capture-before: the state the call RAN UNDER, not the state it
        # produced. A pure read, never an adapter call: get_session_status is
        # undecorated in session.py and exempt from @reconnect_guarded (the
        # _EXEMPT list in tests/session/test_guard.py), precisely so it reads
        # internal state without triggering a verify cycle — so this line can
        # never fault or transition the session, even on a refusal path that
        # runs no handler. A DETACHED session honestly yields the empty chain.
        # The WHOLE status is kept, not just the chain: its health is the
        # before-half of the gap-8 ``session_degraded`` delta, free here.
        before = self._session.get_session_status()
        selection = before.selection.model_dump()

        # The capture above deliberately precedes the registry lookup so an
        # unregistered name is audited with the same fields every other record
        # carries (gap 9) — the state the attempted call would have run under.
        spec = self._registry.get(name)
        if spec is None:
            # duration=0.0 and session_degraded=None for the same reason as a
            # tier refusal: no handler ran, so there was neither execution to
            # time nor anything that could have worsened the session. The name
            # is sanitized once and used for BOTH the returned value and the
            # record — an unregistered name is caller-supplied, and the log is
            # a rendering surface too.
            attempted = sanitize_str(name)
            return self._audit_and_return(
                tool_name=attempted,
                risk_tier=None,
                started=started,
                sanitized=sanitized,
                selection=selection,
                duration=0.0,
                session_degraded=None,
                result=UnknownCapability(name=attempted),
            )

        if spec.tier == "high":
            # Unconditional — the confirmer is deliberately NOT consulted, so
            # no approval path exists until the ADR-6 snapshot provider does.
            # duration=0.0: the handler never ran; zero is the honest value.
            refusal = DispatchRefused(
                capability=spec.name, tier=spec.tier, reason=_HIGH_TIER_REFUSAL
            )
            return self._audit_and_return(
                tool_name=spec.name,
                risk_tier=spec.tier,
                started=started,
                sanitized=sanitized,
                selection=selection,
                duration=0.0,
                session_degraded=None,  # no handler ran — nothing to worsen it
                result=refusal,
            )

        if spec.tier == "medium":
            request = ConfirmationRequest(
                capability=spec.name,
                tier=spec.tier,
                description=spec.description,
                sanitized_arguments=sanitized,
            )
            if not self._confirmer.confirm(request):
                refusal = DispatchRefused(
                    capability=spec.name,
                    tier=spec.tier,
                    reason=(
                        f"confirmation for '{spec.name}' was not granted; "
                        "medium-tier actions require explicit per-action user "
                        "confirmation (§6.1). Tier 1's default confirmer "
                        "refuses everything (deny-by-default)."
                    ),
                )
                return self._audit_and_return(
                    tool_name=spec.name,
                    risk_tier=spec.tier,
                    started=started,
                    sanitized=sanitized,
                    selection=selection,
                    duration=0.0,
                    session_degraded=None,  # no handler ran
                    result=refusal,
                )
        # safe proceeds directly; the confirmer is never consulted for it.

        clock_start = time.perf_counter()
        try:
            result = spec.handler(**args)
        except Exception:
            # Audited as typed_error, then SURFACED — never swallowed. Should
            # the sink ALSO fail here, its exception propagates instead with
            # this one chained as __context__: nothing is swallowed either way.
            # session_degraded IS applicable here: the handler ran, and a
            # handler that raised is exactly one that may have left the session
            # suspect — a raise is no reason to stop recording health.
            duration = time.perf_counter() - clock_start
            self._audit_sink.append(
                self._build_record(
                    tool_name=spec.name,
                    risk_tier=spec.tier,
                    started=started,
                    sanitized=sanitized,
                    selection=selection,
                    duration=duration,
                    session_degraded=self._degraded_since(before),
                    outcome="typed_error",
                )
            )
            raise
        duration = time.perf_counter() - clock_start
        return self._audit_and_return(
            tool_name=spec.name,
            risk_tier=spec.tier,
            started=started,
            sanitized=sanitized,
            selection=selection,
            duration=duration,
            session_degraded=self._degraded_since(before),
            result=result,
        )

    # --- audit assembly -------------------------------------------------------

    def _degraded_since(self, before: SessionStatus) -> bool:
        """The gap-8 ``session_degraded`` value: did THIS call worsen the
        session? A rank DELTA, never a reading of the post-state alone.

        Call this only AFTER the handler — the whole point is to compare
        against the capture-before state, so passing the pre-state as the post
        would answer "no" to everything. The post read is the same pure,
        verify-exempt ``get_session_status`` the capture-before uses, so
        observing health here cannot itself change it.

        Two consequences worth stating, both intended. A call that runs against
        an ALREADY-lost session and is refused scores 2 -> 2 = False: it did not
        worsen anything, and that it met a dead session is already recorded as
        its ``refused_by_gate`` outcome. A SUSPECT -> LOST transition scores
        1 -> 2 = True, which a plain boolean of the post-state would have
        missed — that miss is the reason this is a rank and not a bool.
        """
        return _health_rank(self._session.get_session_status()) > _health_rank(before)

    def _audit_and_return(
        self,
        *,
        tool_name: str,
        risk_tier: RiskTier | None,
        started: datetime,
        sanitized: dict[str, object],
        selection: dict[str, object],
        duration: float,
        session_degraded: bool | None,
        result: object,
    ) -> object:
        """Classify ``result``, append its audit record, and return it — or,
        when the sink fails, withhold the result and return a loud
        ``AuditFailure`` (plan §7: fail closed, misreport nothing).

        Takes ``tool_name``/``risk_tier`` rather than a ``CapabilitySpec``
        because the unregistered-name path (gap 9) has no spec to pass — there
        is no registered capability, which is the entire fact being audited.
        """
        outcome = classify_outcome(result)
        record = self._build_record(
            tool_name=tool_name,
            risk_tier=risk_tier,
            started=started,
            sanitized=sanitized,
            selection=selection,
            duration=duration,
            session_degraded=session_degraded,
            outcome=outcome,
        )
        try:
            self._audit_sink.append(record)
        except Exception as exc:  # deliberately broad: ANY sink failure fails closed
            if outcome == "refused_by_gate":
                action = "the dispatch was refused"
            elif outcome == "unknown_capability":
                action = "the capability name was not registered, so nothing ran"
            else:
                action = f"the capability ran to outcome '{outcome}'"
            return AuditFailure(
                capability=tool_name,
                unaudited_outcome=outcome,
                detail=f"{type(exc).__name__}: {exc}",
                notice=(
                    f"{action}, but the audit record could not be written, so "
                    "the audit log is missing this call. The result is "
                    "withheld: an unaudited operation is never reported as a "
                    "clean one."
                ),
            )
        return result

    def _build_record(
        self,
        *,
        tool_name: str,
        risk_tier: RiskTier | None,
        started: datetime,
        sanitized: dict[str, object],
        selection: dict[str, object],
        duration: float,
        session_degraded: bool | None,
        outcome: AuditOutcome,
    ) -> AuditRecord:
        # snapshot_id is None for every Part 2 capability: nothing on this
        # surface emits a snapshot until Phase 2. risk_tier is None ONLY for an
        # unregistered name, and AuditRecord's both-or-neither validator will
        # reject the record loudly if that ever drifts out of step with
        # outcome — so a tier can neither go unrecorded nor be invented here.
        return AuditRecord(
            timestamp=started,
            tool_name=tool_name,
            sanitized_arguments=sanitized,
            selection_state=selection,
            risk_tier=risk_tier,
            outcome=outcome,
            duration=duration,
            snapshot_id=None,
            session_degraded=session_degraded,
        )

    # --- file surface (Part 3): the guarded export write primitive ------------

    def write_export(
        self, path: str, payload: str | bytes, *, overwrite: bool = False
    ) -> ExportWritten | ExportRefused:
        """The guarded export WRITE PRIMITIVE (plan §2): accepts
        already-formatted text or bytes and writes them. The broker computes
        nothing domain-specific, so touchstone/csv/bundle FORMATTING belongs
        to the Phase 2 callers (export_results / export_diagnostics_bundle
        assembly), which will also register the tool capabilities and map
        outcomes into ``ExportResult``. Not itself a registered capability.

        ``overwrite=False`` -> exclusive create: refusing an existing path is
        kernel-atomic (no TOCTOU window). ``overwrite=True`` ->
        temp-then-replace, so the user's PRE-EXISTING file is never torn; a
        failed overwrite leaves an orphaned temp IN THE USER'S OWN DIRECTORY,
        named by the raised ``BrokerFileError`` (ADR-19 correction).
        Path-validation refusals and write failures raise ``BrokerFileError``
        — contract gap 2: no ``ExportResult`` arm exists for them yet.
        """
        validate_export_path(path)
        if not overwrite:
            try:
                written = exclusive_create_write(path, payload)
            except FileExistsError:
                return ExportRefused(
                    outcome="refused_existing_path",
                    path=path,
                    reason=(
                        "the path already exists and overwrite was not set; "
                        "pass overwrite=true to replace it"
                    ),
                    template_text=(
                        f'Refused: "{path}" already exists and overwrite was '
                        "not set. No file was modified."
                    ),
                )
        else:
            written = atomic_replace_write(path, payload)
        return ExportWritten(
            path=path,
            bytes_written=written,
            template_text=f'Exported {written} bytes to "{path}".',
        )

    # --- control-plane accessors (non-dispatchable) ---------------------------
    #
    # THE RULE, stated once here so this does not become an escape hatch:
    # non-dispatchable broker accessors may expose immutable lifecycle and
    # environment metadata established by the broker or its session. They must
    # not expose the session itself, perform domain operations, or provide an
    # alternate route around capability dispatch.
    #
    # What that implies, concretely — an accessor added below must be ALL of:
    # read-only; describing lifecycle/environment state rather than domain data
    # (a design read is domain data and is a capability, not an accessor);
    # returning an immutable value, never the session object or anything holding
    # capabilities; triggering no external-program work (no AEDT, no disk, no
    # network); and performing no mutation, no dispatch, and no lazy expensive
    # read. Anything failing one of those tests is a capability and belongs in the
    # registry, where the tier gate, confirmation and audit apply to it.
    #
    # ``write_export`` above is the precedent for a broker method that is "not
    # itself a registered capability" — but it is a guarded WRITE PRIMITIVE for
    # the capabilities that will call it, not an accessor, and this rule does not
    # stretch to cover it.

    def require_environment(self) -> Environment:
        """The attached session's environment identity block (AEDT, PyAEDT,
        Python and wrapper versions) — the provenance stamp's only source of
        those versions. Raises ``NoAttachedSessionError`` when nothing is
        attached. Not registered, not in ``session_routed_specs``, not
        dispatchable: it is a control-plane accessor under the rule above.

        READ-THROUGH ON EVERY CALL, NEVER CACHED HERE. The session owns the
        lifecycle and can go LOST, or be re-attached to a DIFFERENT process,
        without notifying the broker — so a copy held on the broker would outlive
        the process it describes and let a record claim an AEDT version read from
        a superseded one. That lying stamp is the exact failure this accessor
        exists to prevent, so the read stays live.
        """
        environment = self._session.get_environment()
        if environment is None:
            raise NoAttachedSessionError()
        return environment


def session_routed_specs(session: Session) -> tuple[CapabilitySpec, ...]:
    """The five session-routed capabilities (approved plan §2), all safe tier.

    Thin delegation ONLY: each handler is the corresponding bound ``Session``
    method — selection order, prerequisites, and fault-to-lifecycle
    reconciliation stay the session's alone (ADR-18 decision 4). Build these
    from the SAME session the ``Broker`` is constructed with (composition
    contract on ``Broker``).
    """
    return (
        CapabilitySpec(
            name="attach",
            tier="safe",
            handler=session.attach,
            description="Attach (attach-only) to a running AEDT process.",
        ),
        CapabilitySpec(
            name="list_selection_options",
            tier="safe",
            handler=session.list_selection_options,
            description="List the choices for a selection stage.",
        ),
        CapabilitySpec(
            name="select",
            tier="safe",
            handler=session.select,
            description=(
                "Select a project/design/setup/sweep/variation into the "
                "session's selection chain."
            ),
        ),
        CapabilitySpec(
            name="get_session_status",
            tier="safe",
            handler=session.get_session_status,
            description="Report session health, selection chain, and suspect flag.",
        ),
        CapabilitySpec(
            name="inspect_design",
            tier="safe",
            handler=session.inspect,
            description=(
                "Read the requested design inspection sections (all when "
                "unspecified)."
            ),
        ),
    )


def intent_capabilities(
    store: IntentStore, session: Session
) -> tuple[CapabilitySpec, ...]:
    """The three broker-owned design-intent capabilities (plan §2), all safe
    tier. Handlers close over the injected store and session; build them with
    the SAME session the ``Broker`` holds (composition contract) — set-time
    selection capture uses the same exempt-from-verify pure read dispatch
    uses.

    set_design_intent's request is the ``IntentObject`` itself (§3: reused
    as-is, no wrapper), so the handler takes its three fields and lets the
    pydantic constructor validate — an invalid request fails loudly and
    audits ``typed_error`` via the dispatch exception path.
    """

    def set_design_intent(
        target_frequency_hz: float, threshold_type: str, threshold_value: float
    ) -> DesignIntentState:
        intent = IntentObject(
            target_frequency_hz=target_frequency_hz,
            threshold_type=threshold_type,  # type: ignore[arg-type]
            threshold_value=threshold_value,
        )
        selection = session.get_session_status().selection
        store.write(intent, selection)
        return DesignIntentState(
            intent=intent,
            template_text=(
                f"Design intent set: {_intent_summary(intent)}. Selection at "
                f"set-time: {_chain_summary(selection)}."
            ),
        )

    def get_design_intent() -> DesignIntentState:
        envelope = store.read()
        if envelope is None or envelope.intent is None:
            return DesignIntentState(
                intent=None, template_text="No design intent is set."
            )
        return DesignIntentState(
            intent=envelope.intent,
            template_text=(
                f"Design intent: {_intent_summary(envelope.intent)}. It was "
                "SET while the selection was: "
                f"{_chain_summary(envelope.selection_at_write)}. If the "
                "current selection differs, this intent may describe a "
                "different design than the one now selected."
            ),
        )

    def clear_design_intent() -> DesignIntentState:
        selection = session.get_session_status().selection
        store.write(None, selection)
        return DesignIntentState(
            intent=None,
            template_text=(
                "Design intent cleared: the empty state was written in place "
                "(nothing was deleted)."
            ),
        )

    return (
        CapabilitySpec(
            name="set_design_intent",
            tier="safe",
            handler=set_design_intent,
            description=(
                "Persist the design intent (target frequency plus one "
                "S11-or-VSWR threshold), replacing any previous intent."
            ),
        ),
        CapabilitySpec(
            name="get_design_intent",
            tier="safe",
            handler=get_design_intent,
            description="Read the persisted design intent and its set-time context.",
        ),
        CapabilitySpec(
            name="clear_design_intent",
            tier="safe",
            handler=clear_design_intent,
            description="Clear the persisted design intent (tombstone write).",
        ),
    )


def audit_capabilities(log_path: str) -> tuple[CapabilitySpec, ...]:
    """The broker-owned audit-log read capability (plan §2), safe tier.

    ``log_path`` must be the SAME path the broker's audit writer appends to
    (composition contract, like ``session_routed_specs``' session identity):
    ``default_audit_log_path(data_dir)`` resolves deterministically, so
    composition passes the same ``data_dir`` to both.
    """

    def get_audit_log(
        range: AuditLogRange | dict[str, object] | None = None,  # noqa: A002
    ) -> AuditLog:
        # The request's one field is literally named "range" (§3
        # GetAuditLogRequest), so the dispatch kwarg must carry that name.
        log_range: AuditLogRange | None = None
        if range is not None:
            log_range = (
                range
                if isinstance(range, AuditLogRange)
                else AuditLogRange.model_validate(range)
            )
        result = read_audit_records(log_path, log_range)
        # Self-referential wrinkle, stated rather than engineered around:
        # dispatching get_audit_log itself appends a record AFTER this handler
        # returns, so the call is visible in subsequent reads but never in its
        # own result.
        #
        # Gap 10 (amended): AuditLog now carries ``torn_tail`` and
        # ``corrupt_lines``, so the reader's two incompleteness signals — which
        # it always computed and this handler used to discard — reach the
        # consumer STRUCTURALLY. The prose below is kept exactly as it was and
        # complements them: a human reading history needs the distinction
        # spelled out (interior corruption is alarming, a torn tail is benign —
        # reader.py), and a machine should not have to string-match to find it.
        template = f"Audit log: {len(result.records)} record(s) returned."
        if result.corrupt_lines:
            numbers = ", ".join(str(number) for number in result.corrupt_lines)
            template += (
                f" WARNING: line(s) {numbers} of the log are corrupt and "
                "unreadable. Treat this log as INCOMPLETE — the surviving "
                "records are returned, but completeness cannot be vouched "
                "for."
            )
        if result.torn_tail:
            template += (
                " The final line is incomplete — the last record was still "
                "mid-write when something stopped (e.g. a crash); that "
                "partial entry is unreadable and not included."
            )
        return AuditLog(
            records=list(result.records),
            template_text=template,
            torn_tail=result.torn_tail,
            corrupt_lines=result.corrupt_lines,
        )

    return (
        CapabilitySpec(
            name="get_audit_log",
            tier="safe",
            handler=get_audit_log,
            description="Read the append-only audit log (optionally range-filtered).",
        ),
    )


def _intent_summary(intent: IntentObject) -> str:
    """Deterministic intent wording. The Hz unit is rendered alongside the
    number because a bare number invites misreading; the unit is no longer
    merely an assumption stated here — the schema pins it in the field name
    (gap 6, amended)."""
    return (
        f"target_frequency_hz={intent.target_frequency_hz} Hz, "
        f'threshold_type="{intent.threshold_type}"'
        f", threshold_value={intent.threshold_value}"
    )


def _chain_summary(chain: SelectionChain) -> str:
    """Data-framed selection summary for the intent templates. Untrusted,
    HFSS-sourced names arrive pre-sanitized (ADR-9) and are rendered inside
    quotes as data, never instruction-positioned (§6.6)."""
    parts: list[str] = []
    if chain.process_id is not None:
        parts.append(f"process={chain.process_id}")
    if chain.project is not None:
        parts.append(f'project="{chain.project.name}"')
    if chain.design is not None:
        parts.append(f'design="{chain.design}"')
    if chain.solution_type is not None:
        parts.append(f'solution_type="{chain.solution_type}"')
    if chain.setup is not None:
        parts.append(f'setup="{chain.setup}"')
    if chain.sweep is not None:
        parts.append(f'sweep="{chain.sweep}"')
    if chain.variation is not None:
        parts.append(f"variation={chain.variation.variation_hash}")
    if not parts:
        return "no selection (no session attached)"
    return ", ".join(parts)
