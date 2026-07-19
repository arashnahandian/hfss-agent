"""Internal session state and its deterministic projection onto ``SessionStatus``.

This module is pure: no adapter, no I/O, no pyaedt. It holds the four internal
health states, the crash/disconnect distinction the pinned contract cannot carry,
and the ONE builder that turns internal state into the contract ``SessionStatus``
— so ``connection_health`` and ``suspect`` are always derived from a single enum
and can never contradict.

Why the crash/disconnect distinction lives here and not in the contract:
``SessionStatus.connection_health`` is a two-value ``Literal`` (connected /
disconnected), merged and pinned by the engine repo. Crash and disconnect both
flatten to ``disconnected`` there, yet their recovery differs (relaunch + new pid
vs. re-attach the same pid). We keep the difference in ``_LostCause`` and surface
it only through deterministic ``template_text`` — never by widening the schema.

Part 3 will test: the state→status table for all four states; that
``disconnected + suspect=true`` is unreachable and raises if forced; and the
determinism (and crash-vs-disconnect wording) of the templates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from hfss_agent.contract.tool_io import SelectionChain, SessionStatus


class _Health(Enum):
    """The session's internal health. Only these four states exist."""

    DETACHED = auto()  # never attached, or a failed attach — no session
    ATTACHED = auto()  # connected; the selection chain is trusted
    SUSPECT = auto()   # connected, but a timeout/internal-error left it unverified
    LOST = auto()      # connection gone or unverifiable; the chain is reset


class _LostCause(Enum):
    """Why a session became LOST — kept distinct because recovery differs.

    A ``None`` cause (not a member here) means "unverifiable": lost for a
    non-transport reason (e.g. the liveness probe answered ``cannot_evaluate``),
    where claiming either crash or disconnect would be a false statement.
    """

    CRASH = auto()       # process exited; relaunch AEDT and attach a NEW pid
    DISCONNECT = auto()  # link dropped, process may live; re-attach the SAME pid


@dataclass
class _SessionState:
    """The session module's single source of truth.

    ``chain`` is authoritative; the adapter's own ``_selection`` is a
    session-driven scoping cache kept in lockstep. ``last_process_id`` survives a
    chain reset so a disconnect template can still say "re-attach the same pid".
    ``lost_cause`` is meaningful only when ``health is LOST``. ``note`` carries a
    one-line, deterministic explanation for the DETACHED (failed attach), LOST
    (unverifiable), and ATTACHED (partial re-verify) templates.
    """

    health: _Health = _Health.DETACHED
    chain: SelectionChain = field(default_factory=SelectionChain)
    last_process_id: int | None = None
    lost_cause: _LostCause | None = None
    note: str | None = None


def build_status(state: _SessionState) -> SessionStatus:
    """The ONLY constructor of ``SessionStatus``. Derives ``connection_health`` and
    ``suspect`` from the single ``_Health`` enum so the two can never disagree.
    """
    if state.health is _Health.ATTACHED:
        connection_health, suspect, selection = "connected", False, state.chain
    elif state.health is _Health.SUSPECT:
        connection_health, suspect, selection = "connected", True, state.chain
    else:  # DETACHED or LOST — both surface as disconnected, with an empty chain
        connection_health, suspect, selection = "disconnected", False, SelectionChain()

    _forbid_disconnected_suspect(connection_health, suspect)

    return SessionStatus(
        connection_health=connection_health,
        suspect=suspect,
        selection=selection,
        template_text=_template_for(state),
    )


def _forbid_disconnected_suspect(connection_health: str, suspect: bool) -> None:
    """SAFETY INVARIANT — explicit raise, not ``assert`` (``assert`` is stripped
    under ``python -O`` and this is a safety property, not a debug check).

    The design forbids reporting a disconnected session as suspect: ``suspect``
    means "connected but unverified", so the pair is meaningless and must never
    leave ``build_status``. Extracted so the guard is directly reachable and
    tested rather than only exercised through the (correct) state mapping, which
    by construction never produces the forbidden pair.
    """
    if connection_health == "disconnected" and suspect:
        raise RuntimeError(
            "session invariant violated: SessionStatus cannot be both "
            "disconnected and suspect"
        )


def _template_for(state: _SessionState) -> str:
    """Deterministic core text for a state — complete without any LLM (§3).

    Untrusted, HFSS-sourced chain values (project/design/setup/sweep names,
    solution type) arrive here already sanitized by the adapter (ADR-9); this
    builder additionally frames them inside explicit data delimiters (quotes) and
    never lets them influence control flow (§6.6).
    """
    if state.health is _Health.DETACHED:
        return state.note or (
            "No AEDT session is attached. Attach to a running AEDT process to begin."
        )
    if state.health is _Health.LOST:
        return _lost_template(state)

    pid = state.chain.process_id
    header = (
        f"Connected to AEDT process {pid}." if pid is not None else "Connected to AEDT."
    )
    if state.health is _Health.SUSPECT:
        return (
            f"{header} The connection is unverified after an abandoned or timed-out "
            "call; the next operation will re-verify the current selection before "
            "proceeding, and will not silently re-establish the session."
        )
    # ATTACHED
    summary = _selection_summary(state.chain)
    if state.note:
        return f"{header} {summary} {state.note}"
    return f"{header} {summary}"


def _lost_template(state: _SessionState) -> str:
    """Crash / disconnect / unverifiable wording — the distinction the contract
    flattens, surfaced here. Recovery is always a deliberate user re-attach; the
    session never re-establishes automatically (attach-only, ADR-1 Axis B)."""
    pid = state.last_process_id
    where = f"AEDT process {pid}" if pid is not None else "the AEDT session"
    if state.lost_cause is _LostCause.CRASH:
        return (
            f"{where} appears to have exited. Relaunch AEDT and attach to the new "
            "process id; the previous selection was cleared."
        )
    if state.lost_cause is _LostCause.DISCONNECT:
        return (
            f"The connection to {where} dropped; the process may still be running. "
            "Re-attach to the same process id to reconnect; the previous selection "
            "was cleared."
        )
    # unverifiable (lost_cause is None): no crash/disconnect to claim honestly
    detail = state.note or "the session could not be verified"
    return (
        f"{where} is no longer usable: {detail}. Re-attach to continue; the "
        "previous selection was cleared."
    )


def _selection_summary(chain: SelectionChain) -> str:
    """A data-framed summary of the current selection. Each untrusted name is
    rendered inside quotes as data, never instruction-positioned (ADR-9/§6.6)."""
    parts: list[str] = []
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
        # variation_hash is wrapper-computed (sha256:...) and not untrusted.
        parts.append(f"variation={chain.variation.variation_hash}")
    if not parts:
        return "No selection yet; list options for 'project' to begin."
    return "Selection: " + ", ".join(parts) + "."
