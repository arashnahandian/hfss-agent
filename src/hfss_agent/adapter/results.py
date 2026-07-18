"""Adapter-domain outcome types (W-3).

These are deliberately NOT contract schemas: they carry session-lifecycle /
transport semantics the wrapper->engine contract does not model, and they never
travel to the engine. They live here, in the capability module, and are consumed
by the ``session`` module (W-2), which reacts to a ``SessionFault`` by marking
the session suspect and forcing reconnect-and-verify (ADR-10, §6.7).

A crash and a lost/dropped session are different real failure modes and never
collapse into one generic error (ADR-10): ``AdapterCrash`` and
``AdapterDisconnect`` are distinct types with distinct recovery meaning — a
crashed process likely needs relaunch; a dropped link may recover on re-attach.

The single predicate that says "the session can no longer be trusted" is
``isinstance(outcome, SessionFault)``; ``AdapterCannotEvaluate`` is intentionally
NOT a ``SessionFault`` — PyAEDT answered, it simply cannot read/evaluate the
requested thing, and the session stays healthy.
"""

from dataclasses import dataclass
from typing import ClassVar, TypeVar


@dataclass(frozen=True)
class AdapterOutcome:
    """Base marker for every "not the success data" result.

    ``status`` is a per-class discriminator carried as a ``ClassVar`` (not an
    instance field) so it never participates in dataclass field ordering and is
    never treated as sanitizable content.
    """

    status: ClassVar[str]


@dataclass(frozen=True)
class AdapterCannotEvaluate(AdapterOutcome):
    """PyAEDT is connected and responsive but genuinely cannot read/evaluate the
    requested thing. Names the limitation the way ``InspectionSection.limitation``
    does. The tool layer maps this to the contract ``CannotEvaluate`` (adding the
    server-owned ``template_text``); it never becomes a hang and never a session
    fault.
    """

    status: ClassVar[str] = "cannot_evaluate"
    reason: str
    limitation: str


@dataclass(frozen=True)
class SessionFault(AdapterOutcome):
    """Base for the transport/lifecycle faults. Its presence is the one predicate
    the session module keys on: mark suspect, force reconnect-and-verify."""


@dataclass(frozen=True)
class AdapterTimeout(SessionFault):
    """The per-call watchdog abandoned the call (§6.7). The stuck worker was left
    to die with the process — never pretend-cancelled."""

    status: ClassVar[str] = "timed_out"
    operation: str
    limit_seconds: float


@dataclass(frozen=True)
class AdapterCrash(SessionFault):
    """The AEDT process died mid-call. Distinct from a dropped link: the process
    itself is gone and likely needs relaunch (ADR-10)."""

    status: ClassVar[str] = "crashed"
    detail: str


@dataclass(frozen=True)
class AdapterDisconnect(SessionFault):
    """The gRPC/session link dropped, but the process may still be alive. Distinct
    from a crash: a re-attach may recover it (ADR-10)."""

    status: ClassVar[str] = "disconnected"
    detail: str


@dataclass(frozen=True)
class AdapterInternalError(SessionFault):
    """The watchdog caught an unexpected (non-transport) exception and converted
    it to a typed outcome so nothing escapes uncaught. Deliberately its own arm,
    not folded into ``AdapterCrash`` — a bug in our code must never report itself
    to the user as an AEDT process crash. Treated as a ``SessionFault`` because,
    if our own call blew up mid-op, session integrity is unknown."""

    status: ClassVar[str] = "internal_error"
    detail: str


# Generic result alias. Each operation returns its success payload ``T`` or one
# of the non-data outcomes; e.g. ``read_solve_state() -> AdapterResult[SolveState]``.
# A union over a ``TypeVar`` so ``AdapterResult[SolveState]`` is a valid subscripted
# alias on every supported interpreter (3.10-3.12).
T = TypeVar("T")
AdapterResult = (
    T
    | AdapterCannotEvaluate
    | AdapterTimeout
    | AdapterCrash
    | AdapterDisconnect
    | AdapterInternalError
)
