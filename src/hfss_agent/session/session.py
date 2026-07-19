"""W-2 · session — AEDT session lifecycle and selection state machine.

Layer 2: imports ``adapter`` and ``contract`` only — no broker, no file I/O, no
audit, no pyaedt. It owns the selection chain ``process -> project -> design ->
setup -> sweep -> variation``, enforces its order (the adapter deliberately does
not — Part 2a), reconciles adapter fault outcomes into a session lifecycle, and
re-verifies a suspect session before the next operation.

Two design decisions here diverge from written specs and are flagged, not
absorbed:

  * DIVERGENCE FROM ADR-10 / System Design §6.7 (verify-only recovery): §6.7 and
    ADR-10 say the next operation "forces a reconnect-and-verify cycle." We
    implement VERIFY-only: on a suspect session the next operation re-verifies the
    saved chain on the EXISTING adapter and NEVER auto-re-attaches. Reasons: (1) a
    second ``attach()`` on an already-attached adapter creates a stray second
    session handle — the predecessor project's named fragility (blocking check,
    Step 1.3); and (2) automatic re-attach is itself mildly contrary to attach-only
    (ADR-1 Axis B) — it has the agent re-establishing a session the user never
    asked it to. Reconnection is therefore a deliberate user action (call
    ``attach`` again). This must be recorded in ADR-18 and §6.7 edited to match.

  * DEVIATION FROM ADR-16 decision 5 (cannot_evaluate narrowing): ADR-16 narrowed
    ``cannot_evaluate`` to mean specifically "PyAEDT could not evaluate this", to
    avoid misattributing failures. The pinned two/three-arm unions ``SelectResult``
    (SessionStatus | CannotEvaluate) and ``ListSelectionOptionsResult``
    (SelectionOptions | CannotEvaluate) give no other typed arm for a refusal, so
    this module returns ``CannotEvaluate`` for several NON-PyAEDT outcomes:
    selection-order refusals, no-usable-session refusals, a session fault during a
    listing, and a surfaced post-verify internal error. Every such use states
    plainly in ``reason``/``limitation`` that PyAEDT was not reached/at fault. This
    is a knowing misattribution, chosen over the alternative — returning an
    unchanged ``SessionStatus`` — which ADR-16 decision 4 designed against because
    it makes a refusal indistinguishable from a success without parsing text.

Part 3 will test (matrix not built here): the reflection guard test; per-fault
transitions incl. escalation; attach success/fault; prerequisite refusals per
stage; LOST/DETACHED-on-operation; verify happy path, per-stage mismatch reset,
fault-during-verify terminal, empty-chain probe (data / fault / cannot_evaluate);
the disconnected+suspect impossibility; template determinism; single-source-of-
truth (session chain == adapter chain after drives).
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal, TypeVar

from hfss_agent.adapter import (
    Adapter,
    AdapterCannotEvaluate,
    AdapterCrash,
    AdapterDisconnect,
    AdapterInternalError,
    AdapterTimeout,
    SessionFault,
)
from hfss_agent.contract.tool_io import (
    AttachResult,
    CannotEvaluate,
    ListSelectionOptionsResult,
    SelectionChain,
    SelectionOption,
    SelectionOptions,
    SelectionStage,
    SelectResult,
    SessionStatus,
)
from hfss_agent.session.status import (
    _Health,
    _LostCause,
    _SessionState,
    build_status,
)

# The stage a stage requires selected before it. ``project`` requires only an
# attached session (checked separately). This is the guided-chain order the
# session enforces for BOTH select and list_selection_options — the adapter
# permits out-of-order calls, so the session is the sole order-enforcer.
_UPSTREAM: dict[SelectionStage, SelectionStage | None] = {
    "project": None,
    "design": "project",
    "setup": "design",
    "sweep": "setup",
    "variation": "sweep",
}

# Fields cleared when a chain is reset FROM a stage down (the stage itself plus
# everything below it). ``process_id`` is never cleared here — a from-stage reset
# keeps the session attached. ``solution_type`` travels with ``design``.
_CLEAR_FROM: dict[SelectionStage, tuple[str, ...]] = {
    "project": ("project", "design", "solution_type", "setup", "sweep", "variation"),
    "design": ("design", "solution_type", "setup", "sweep", "variation"),
    "setup": ("setup", "sweep", "variation"),
    "sweep": ("sweep", "variation"),
    "variation": ("variation",),
}

# The two fault-classification contexts (see Session._classify_fault). A fault
# during re-verification is terminal; a fault during a normal operation is
# recoverable. One classifier, two explicitly-named contexts.
_FaultContext = Literal["verify", "operation"]

_F = TypeVar("_F", bound=Callable[..., object])


def reconnect_guarded(method: _F) -> _F:
    """Wrap a public operation so a SUSPECT session is re-verified before it runs.

    This is the structural suspect guard (ADR-17 decision 2 pattern: the concrete
    public method wraps the guarded path). The ``__reconnect_guarded__`` marker
    lets a reflection test prove EVERY public adapter-touching method carries it —
    a new unguarded method added later fails that test rather than shipping. The
    exempt set (``attach`` re-establishes; ``get_session_status`` is a pure read)
    lives in the TEST file, so widening it shows up as a reviewable test diff.
    """

    @functools.wraps(method)
    def wrapper(self: Session, *args: object, **kwargs: object) -> object:
        if self._state.health is _Health.SUSPECT:
            # Verify on the existing adapter — never re-attach (see module docstring).
            self._verify()
            self._just_verified = True
        else:
            self._just_verified = False
        try:
            return method(self, *args, **kwargs)
        finally:
            self._just_verified = False

    wrapper.__reconnect_guarded__ = True  # type: ignore[attr-defined]
    return wrapper  # type: ignore[return-value]


@dataclass(frozen=True)
class _StageVerdict:
    """Outcome of re-verifying one chain stage: confirmed, a mismatch (with a
    reason), or a fault to propagate as terminal LOST."""

    ok: bool
    reason: str | None = None
    fault: SessionFault | None = None


class Session:
    """The AEDT session lifecycle + selection state machine (W-2).

    Holds one injected ``Adapter`` for its whole life (tests inject a
    ``FakeAdapter``). The session is the single source of truth for the selection
    chain and drives the adapter so the adapter's own ``_selection`` scoping cache
    can never diverge from it.

    No worker threads live here; the only threads are the adapter watchdog's,
    already ``daemon=True``.
    """

    def __init__(self, adapter: Adapter) -> None:
        self._adapter = adapter
        self._state = _SessionState()  # DETACHED
        # True only while an operation runs in the same guard invocation that just
        # re-verified — see the post-verify AdapterInternalError escalation.
        self._just_verified = False

    # --- public surface -------------------------------------------------------

    def attach(self, process_id: int) -> AttachResult:
        """Attach-only connect to a running AEDT process (also the re-attach /
        recovery entry point). Not reconnect-guarded: re-verify-first would be
        meaningless for the operation that re-establishes the session.

        Success -> ATTACHED with a fresh chain of just this process. Any fault ->
        DETACHED (a failed attach; "suspect"/"lost" presuppose a session that
        already existed). We never launch, retry, or take ownership (ADR-1 Axis B).
        """
        self._just_verified = False
        outcome = self._adapter.attach(process_id)
        if isinstance(outcome, AdapterCannotEvaluate):
            # adapter.attach does not produce this in practice; map faithfully.
            return self._map_adapter_cannot_evaluate(outcome)
        if isinstance(outcome, SessionFault):
            self._state = _SessionState(
                health=_Health.DETACHED,
                last_process_id=process_id,
                note=self._attach_failure_note(process_id, outcome),
            )
            return build_status(self._state)
        # Success: outcome is an Environment (identity block, surfaced elsewhere).
        self._state = _SessionState(
            health=_Health.ATTACHED,
            chain=SelectionChain(process_id=process_id),
            last_process_id=process_id,
        )
        return build_status(self._state)

    @reconnect_guarded
    def list_selection_options(
        self, stage: SelectionStage
    ) -> ListSelectionOptionsResult:
        """List the choices for a stage (order-enforced). Returns ``SelectionOptions``
        or a typed ``CannotEvaluate`` (see the ADR-16 deviation note)."""
        return self._do_list_options(stage)

    @reconnect_guarded
    def select(self, stage: SelectionStage, choice: str) -> SelectResult:
        """Select a stage into the chain (order-enforced). Success returns the
        updated ``SessionStatus``; a refusal returns a typed ``CannotEvaluate``."""
        return self._do_select(stage, choice)

    def get_session_status(self) -> SessionStatus:
        """Report current health, selection chain, and suspect flag. A pure read of
        internal state — makes no adapter call and does NOT trigger verify, so a
        suspect session is reported honestly as suspect rather than silently
        re-verified."""
        return build_status(self._state)

    # --- operation bodies -----------------------------------------------------

    def _do_select(self, stage: SelectionStage, choice: str) -> SelectResult:
        refusal = self._require_usable_session()
        if refusal is not None:
            return refusal
        if not self._prerequisite_met(stage):
            return self._prerequisite_refusal(stage)
        outcome = self._adapter.select(stage, choice)
        if isinstance(outcome, SessionFault):
            surfaced = self._classify_fault(outcome, context="operation")
            if surfaced is not None:
                return surfaced  # escalated post-verify internal error
            # suspect/lost transition applied; reflect the new state (select CAN
            # return a SessionStatus, unlike list_selection_options).
            return build_status(self._state)
        if isinstance(outcome, AdapterCannotEvaluate):
            return self._map_adapter_cannot_evaluate(outcome)
        # Success: the adapter returns its SelectionChain. Mirror it as the single
        # source of truth so the two chains cannot diverge; clear any stale note.
        self._state = replace(self._state, chain=outcome, note=None)
        return build_status(self._state)

    def _do_list_options(
        self, stage: SelectionStage
    ) -> ListSelectionOptionsResult:
        refusal = self._require_usable_session()
        if refusal is not None:
            return refusal
        if not self._prerequisite_met(stage):
            return self._prerequisite_refusal(stage)
        outcome = self._adapter.list_options(stage)
        if isinstance(outcome, SessionFault):
            surfaced = self._classify_fault(outcome, context="operation")
            if surfaced is not None:
                return surfaced  # escalated post-verify internal error
            # list_selection_options has no SessionStatus arm, so a fault must be
            # reported as a CannotEvaluate naming the new state (ADR-16 deviation).
            return self._session_fault_refusal()
        if isinstance(outcome, AdapterCannotEvaluate):
            return self._map_adapter_cannot_evaluate(outcome)
        return SelectionOptions(
            stage=stage,
            options=list(outcome),
            template_text=self._options_template(stage, outcome),
        )

    # --- reconnect-and-verify (no re-attach) ----------------------------------

    def _verify(self) -> None:
        """Re-verify a SUSPECT session by re-driving the saved chain on the EXISTING
        adapter — never re-attaching (module docstring). Confirms the chain still
        resolves to present, same-typed entities by comparing identity anchors.

        HONEST LIMITATION (in code, not just the ADR): this is NOT proof the design
        content is unchanged. Names are untrusted and reusable, and PyAEDT exposes
        no changed-since signal (freshness determinable=False), so a design edited
        in place — same names, same structure — is indistinguishable to verify. We
        never claim content equality, and there is no proactive mid-session-edit
        watcher.

        Two rules govern ambiguous outcomes:

          * PROOF OF LIFE: suspect clears / the session stays ATTACHED only once a
            read RETURNS DATA. The first such read is always list_options("project")
            — which also serves as the empty-chain liveness probe (addition (b)).
            A ``cannot_evaluate`` is never itself proof of life: before any data
            read it is terminal LOST (unverifiable); after it (a downstream stage)
            it is a mismatch, because the successful project read already proved the
            link alive and calling a responsive session LOST would be a false claim.

          * FAULT-DURING-VERIFY IS TERMINAL (addition (a)): any SessionFault raised
            inside verify goes straight to LOST, never SUSPECT. If a verify-time
            timeout produced SUSPECT, the next operation would re-enter verify and
            cycle unboundedly; making it terminal breaks that loop.

        Stopping rule: stop at the first fault (LOST), the first mismatch/
        unconfirmable stage (reset from that stage down, ATTACHED), or full success.
        """
        saved = self._state.chain

        # First read: the liveness probe (empty chain) and, if selected, the
        # project stage. This is the ONLY read whose cannot_evaluate is terminal.
        projects = self._adapter.list_options("project")
        if isinstance(projects, SessionFault):
            self._classify_fault(projects, context="verify")
            return
        if isinstance(projects, AdapterCannotEvaluate):
            # No proof of life yet — do not clear suspect on the adapter's word that
            # it is "responsive" (addition (b)). Terminal, non-transport LOST.
            self._to_lost(
                None, note="the liveness read could not list the open projects"
            )
            return
        # Data -> LIFE PROVEN.
        if saved.project is None:
            # Empty chain: liveness confirmed by a real read, nothing to re-verify.
            self._state = replace(self._state, health=_Health.ATTACHED, note=None)
            return

        option_values = [option.value for option in projects]
        if saved.project.name not in option_values:
            self._reset_from("project", "the project is no longer open")
            return
        sel = self._adapter.select("project", saved.project.name)
        if isinstance(sel, SessionFault):
            self._classify_fault(sel, context="verify")
            return
        if isinstance(sel, AdapterCannotEvaluate):
            self._reset_from("project", "the project could not be re-read")
            return
        if sel.project is None or sel.project.path != saved.project.path:
            self._reset_from("project", "the project path changed")
            return

        # Remaining set stages, in order. Life is proven, so a cannot_evaluate here
        # is a mismatch (reset that stage down), not LOST.
        for stage in ("design", "setup", "sweep", "variation"):
            if _saved_value(saved, stage) is None:
                break
            verdict = self._reverify_stage(stage, saved)
            if verdict.fault is not None:
                self._classify_fault(verdict.fault, context="verify")
                return
            if not verdict.ok:
                self._reset_from(stage, verdict.reason or "could not be re-verified")
                return

        # Every set stage re-confirmed with a matching identity anchor.
        self._state = replace(self._state, health=_Health.ATTACHED, note=None)

    def _reverify_stage(
        self, stage: SelectionStage, saved: SelectionChain
    ) -> _StageVerdict:
        """Re-verify one non-project stage: it must still be present, and its
        identity anchor must match. Reads are non-mutating (ADR-17 decision 9:
        ``_select`` records a choice and calls no active-selection setter), so
        re-driving changes nothing in AEDT."""
        options = self._adapter.list_options(stage)
        if isinstance(options, SessionFault):
            return _StageVerdict(ok=False, fault=options)
        if isinstance(options, AdapterCannotEvaluate):
            return _StageVerdict(
                ok=False, reason=f"the {stage} list could not be re-read"
            )
        choice = self._present_choice(stage, saved, options)
        if choice is None:
            return _StageVerdict(
                ok=False, reason=f"the selected {stage} is no longer present"
            )
        result = self._adapter.select(stage, choice)
        if isinstance(result, SessionFault):
            return _StageVerdict(ok=False, fault=result)
        if isinstance(result, AdapterCannotEvaluate):
            return _StageVerdict(ok=False, reason=f"the {stage} could not be re-read")
        if not self._select_anchor_ok(stage, saved, result):
            return _StageVerdict(
                ok=False, reason=f"the {stage} identity changed since selection"
            )
        return _StageVerdict(ok=True)

    @staticmethod
    def _present_choice(
        stage: SelectionStage, saved: SelectionChain, options: list[SelectionOption]
    ) -> str | None:
        """The choice token to re-select ``stage``, if the saved value is still
        among ``options`` by identity anchor — else None (a mismatch). For
        variation the anchor is the variation hash, and the matching option's
        value is the token to re-select with."""
        if stage == "design":
            return saved.design if saved.design in [o.value for o in options] else None
        if stage == "setup":
            return saved.setup if saved.setup in [o.value for o in options] else None
        if stage == "sweep":
            return saved.sweep if saved.sweep in [o.value for o in options] else None
        # variation
        if saved.variation is None:
            return None
        target = saved.variation.variation_hash
        for option in options:
            variation = option.variation
            if variation is not None and variation.variation_hash == target:
                return option.value
        return None

    @staticmethod
    def _select_anchor_ok(
        stage: SelectionStage, saved: SelectionChain, result: SelectionChain
    ) -> bool:
        """Whether the re-selected stage's identity anchor matches the saved one.
        Design -> solution_type; variation -> variation_hash; setup/sweep ->
        presence was the anchor (checked already), so the select only rebinds."""
        if stage == "design":
            return result.solution_type == saved.solution_type
        if stage == "variation":
            return (
                result.variation is not None
                and saved.variation is not None
                and result.variation.variation_hash == saved.variation.variation_hash
            )
        return True

    # --- state transitions ----------------------------------------------------

    def _classify_fault(
        self, fault: SessionFault, *, context: _FaultContext
    ) -> CannotEvaluate | None:
        """THE single fault classifier — every ``SessionFault`` flows through here.

        Deliberately TWO contexts, not one. The plan's idea of a single
        ``_adapter_call`` classifier could not stand, because a fault means
        different things depending on WHEN it happens — so this is the "explicit,
        commented reason for two" rather than two scattered inline paths:

          * ``"verify"`` — used by ``_verify``, ``_reverify_stage``, AND
            ``_resync_adapter``. Re-verification is under way, so a fault is
            TERMINAL -> LOST, never SUSPECT: going SUSPECT would make the next op
            re-enter verify and cycle unboundedly (rule 1a). Crash/disconnect keep
            their cause; a verify-time timeout/internal-error is non-transport, so
            it becomes an unverifiable LOST rather than a fabricated crash/disconnect.
            ``_resync_adapter`` uses THIS context precisely because resync is part
            of verify — a resync fault must not leave us ATTACHED with the two
            chains disagreeing.

          * ``"operation"`` — used by ``_do_select`` / ``_do_list_options``. A fault
            during a normal op is recoverable: timeout/internal-error -> SUSPECT (the
            next op re-verifies), disconnect/crash -> LOST. ESCALATION (plan change
            3): a post-verify ``AdapterInternalError`` is surfaced and does NOT go
            SUSPECT, so verify cannot "recover" the same bug forever.

        Returns a surfaced ``CannotEvaluate`` only in the escalation case, else None.
        """
        if context == "verify":
            if isinstance(fault, AdapterCrash):
                self._to_lost(_LostCause.CRASH)
            elif isinstance(fault, AdapterDisconnect):
                self._to_lost(_LostCause.DISCONNECT)
            else:  # timeout / internal error during verify -> unverifiable LOST
                self._to_lost(
                    None, note="a read timed out or errored during re-verification"
                )
            return None
        # context == "operation"
        if isinstance(fault, AdapterInternalError) and self._just_verified:
            return self._internal_error_refusal(fault)
        if isinstance(fault, (AdapterTimeout, AdapterInternalError)):
            self._state = replace(self._state, health=_Health.SUSPECT)
        elif isinstance(fault, AdapterDisconnect):
            self._to_lost(_LostCause.DISCONNECT)
        elif isinstance(fault, AdapterCrash):
            self._to_lost(_LostCause.CRASH)
        return None

    def _to_lost(self, cause: _LostCause | None, note: str | None = None) -> None:
        """Transition to LOST: reset the chain, keep ``last_process_id`` for the
        re-attach hint, record the cause (crash/disconnect) or a note (unverifiable)."""
        self._state = _SessionState(
            health=_Health.LOST,
            chain=SelectionChain(),
            last_process_id=self._state.last_process_id,
            lost_cause=cause,
            note=note,
        )

    def _reset_from(self, stage: SelectionStage, reason: str) -> None:
        """A verify mismatch: keep the confirmed upstream, clear ``stage`` and every
        stage below it, stay ATTACHED (life was proven), and say which stage failed
        and why."""
        cleared = self._state.chain.model_copy(
            update={field: None for field in _CLEAR_FROM[stage]}
        )
        self._state = replace(
            self._state,
            health=_Health.ATTACHED,
            chain=cleared,
            note=(
                f"Re-verification could not confirm '{stage}': {reason}. "
                f"'{stage}' and the selections below it were cleared; re-select to "
                "continue."
            ),
        )
        self._resync_adapter(cleared)

    def _resync_adapter(self, chain: SelectionChain) -> None:
        """Keep the adapter's scoping selection equal to ours (single source of
        truth). Reading a stage's anchor during verify requires ``select``, which
        can advance the adapter past the boundary the session retains on a mismatch;
        re-drive the retained prefix to bring the adapter back into agreement.

        MECHANISM + DEPENDENCY (do not remove without checking Part 2a): the adapter
        has NO un-select and re-attach is off the table, so we re-select the last
        valid upstream stage and rely on the adapter's ``downstream_reset``
        (``adapter/selection.py``, Step 1.3 Part 2a) to clear everything the adapter
        cached BELOW it. e.g. a ``design`` mismatch left the adapter at
        ``{project, design}``; re-selecting ``project`` here fires
        ``downstream_reset("project")``, dropping the stale ``design``. If a future
        change makes ``select`` stop clearing downstream, this reconciliation breaks
        SILENTLY — the two chains would diverge with no error — so that behavior is
        load-bearing here. (A retained chain never reaches ``variation``, the
        deepest stage a reset clears, so no variation token is needed.)

        FAULT HANDLING: resync makes real adapter calls that can fault. We must
        never end ATTACHED with the chains disagreeing, so this is treated as part
        of verify: a fault (or an anomalous cannot_evaluate on a stage we just
        confirmed) is terminal -> LOST, which resets our chain and defers adapter
        re-alignment to the next user re-attach. A successful ``select`` sets the
        adapter's ``_selection`` for that stage, so completing the loop guarantees
        the two chains agree; anything else drops us out of ATTACHED.
        """
        # Loop stops at ``sweep`` — there is deliberately no ``variation`` entry.
        # ``_resync_adapter`` runs ONLY from ``_reset_from``, which clears the
        # mismatched stage and everything below it; ``variation`` is the deepest
        # stage, so it is either the cleared mismatch stage or below a cleared one —
        # never retained. A retained chain therefore never reaches ``variation``, so
        # its opaque re-select token (recovered from options, not stored) is never
        # needed here. If a caller ever runs resync with variation retained, this
        # assumption breaks.
        for stage, value in (
            ("project", chain.project.name if chain.project is not None else None),
            ("design", chain.design),
            ("setup", chain.setup),
            ("sweep", chain.sweep),
        ):
            if value is None:
                break
            outcome = self._adapter.select(stage, value)
            if isinstance(outcome, SessionFault):
                # Link failed mid re-scope. Terminal (fault during verify, rule 1a);
                # overrides the ATTACHED just set by _reset_from.
                self._classify_fault(outcome, context="verify")
                return
            if isinstance(outcome, AdapterCannotEvaluate):
                # Anomalous: we are re-selecting a stage verify just confirmed. Do
                # not claim health with a possible divergence — drop to LOST.
                self._to_lost(
                    None, note="re-scoping the confirmed selection did not complete"
                )
                return

    # --- refusals & helpers ---------------------------------------------------

    def _require_usable_session(self) -> CannotEvaluate | None:
        """None if ATTACHED; otherwise a typed refusal. Covers the explicit
        LOST-on-operation and DETACHED cases: the guard only re-verifies SUSPECT,
        so a non-ATTACHED state here means never-attached or verify-failed, and we
        never auto-re-attach — the user must (attach-only, ADR-18)."""
        if self._state.health is _Health.ATTACHED:
            return None
        if self._state.health is _Health.LOST:
            limitation = (
                "the AEDT session was lost and cannot be used; re-attach to a "
                "running process to continue. PyAEDT was not reached."
            )
        else:  # DETACHED
            limitation = (
                "no AEDT session is attached; attach to a running process first. "
                "PyAEDT was not reached."
            )
        return self._cannot_evaluate("no usable session", limitation)

    def _prerequisite_met(self, stage: SelectionStage) -> bool:
        """Whether ``stage``'s upstream stage is selected (order enforcement)."""
        upstream = _UPSTREAM[stage]
        if upstream is None:
            return True  # project needs only an attached session (checked earlier)
        return _saved_value(self._state.chain, upstream) is not None

    def _prerequisite_refusal(self, stage: SelectionStage) -> CannotEvaluate:
        upstream = _UPSTREAM[stage]
        if upstream is None:
            limitation = (
                "attach a process before selecting a project. This is a session "
                "order refusal; PyAEDT was not reached."
            )
        else:
            limitation = (
                f"select a {upstream} before selecting a {stage}. This is a "
                "selection-order refusal enforced by the session; PyAEDT was not "
                "reached."
            )
        return self._cannot_evaluate("selection order", limitation)

    def _session_fault_refusal(self) -> CannotEvaluate:
        """Report (for list_selection_options, which has no SessionStatus arm) that
        a read faulted and the session transitioned. The transition already ran in
        ``_classify_fault(context="operation")``."""
        state_word = (
            "is now unverified (suspect)"
            if self._state.health is _Health.SUSPECT
            else "was lost"
        )
        return self._cannot_evaluate(
            "session fault during listing",
            f"the read did not complete and the session {state_word}; check "
            "get_session_status. The next operation will re-verify, or you may need "
            "to re-attach. PyAEDT could not complete the read.",
        )

    def _internal_error_refusal(self, fault: AdapterInternalError) -> CannotEvaluate:
        """Surface a post-verify internal error (escalation) rather than loop."""
        return self._cannot_evaluate(
            "internal inconsistency (not a PyAEDT limitation)",
            f"the agent hit an internal error that persisted across "
            f"re-verification: {fault.detail}. This is a bug in the agent's own "
            "bookkeeping, not a problem with your design or AEDT; PyAEDT was not "
            "the cause.",
        )

    @staticmethod
    def _map_adapter_cannot_evaluate(
        adapter_ce: AdapterCannotEvaluate,
    ) -> CannotEvaluate:
        """Faithfully map a genuine adapter ``cannot_evaluate`` (PyAEDT-backed, e.g.
        variation enumeration unavailable) onto the contract type. This is the ONE
        non-deviating use of ``CannotEvaluate`` — PyAEDT really was reached and
        could not evaluate."""
        return CannotEvaluate(
            reason=adapter_ce.reason,
            limitation=adapter_ce.limitation,
            template_text=f"Cannot evaluate via PyAEDT: {adapter_ce.limitation}",
        )

    @staticmethod
    def _cannot_evaluate(reason: str, limitation: str) -> CannotEvaluate:
        return CannotEvaluate(
            reason=reason,
            limitation=limitation,
            template_text=f"Cannot proceed: {limitation}",
        )

    @staticmethod
    def _attach_failure_note(process_id: int, fault: SessionFault) -> str:
        if isinstance(fault, AdapterCrash):
            detail = "the process is not available (it may have exited)"
        elif isinstance(fault, AdapterDisconnect):
            detail = "the connection could not be established"
        elif isinstance(fault, AdapterTimeout):
            detail = "the attach attempt timed out"
        else:  # AdapterInternalError
            detail = "an internal error occurred while attaching"
        return (
            f"Could not attach to AEDT process {process_id}: {detail}. No session "
            "is attached; verify the process id and try again."
        )

    @staticmethod
    def _options_template(
        stage: SelectionStage, options: list[SelectionOption]
    ) -> str:
        """Deterministic listing text. Option values are HFSS-sourced (untrusted,
        pre-sanitized) and framed as quoted data (ADR-9/§6.6)."""
        if not options:
            return f"No options are available for '{stage}'."
        rendered = ", ".join(f'"{option.value}"' for option in options)
        return f"Options for '{stage}': {rendered}."


def _saved_value(chain: SelectionChain, stage: SelectionStage) -> object | None:
    """The saved chain value for ``stage`` (None if unset)."""
    return {
        "project": chain.project,
        "design": chain.design,
        "setup": chain.setup,
        "sweep": chain.sweep,
        "variation": chain.variation,
    }[stage]
