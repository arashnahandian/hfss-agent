"""Shared helpers for the W-5 inspect suite (Step 2.1).

Everything drives the licence-free ``FakeAdapter`` through a REAL ``Broker`` —
W-5's only data path is a broker dispatch (ADR-20 decision 1), so the assembler
is exercised across the boundary it actually uses rather than against a stubbed
one. The audit sink is in-memory, so the suite performs no file I/O.

Uniquely named (not ``conftest``) and imported explicitly, following the session
and broker suites' stated rationale: sibling ``conftest`` modules from different
test dirs collide under pytest's rootdir import mode. ``RecordingSink`` /
``RaisingSink`` are re-declared here rather than imported from
``broker_helpers`` for the same reason — the two suite directories are not on
each other's import path, and the doubles are four lines each.
"""

from __future__ import annotations

from collections.abc import Callable

from hfss_agent.adapter.fake import FakeAdapter, Scenario
from hfss_agent.broker import (
    Broker,
    CapabilityRegistry,
    CapabilitySpec,
    Confirmer,
    RefuseAllConfirmer,
    session_routed_specs,
)
from hfss_agent.contract import AuditRecord
from hfss_agent.session import Session

# The default FakeAdapter scenario's values — the same constants the session and
# broker suites pin, plus the two environment fields W-5 stamps.
DEFAULT_PID = 1234
PROJECT = "patch_antenna"
DESIGN = "HFSSDesign1"
AEDT_VERSION = "2026.1"
WRAPPER_VERSION = "0.0.0"

# The eight contract section names, spelled out here so the suite checks
# ``_CANONICAL_ORDER`` against an independently written list rather than against
# the constant it is meant to be auditing.
ALL_SECTIONS = frozenset(
    {
        "variables",
        "objects",
        "materials",
        "boundaries",
        "excitations_ports",
        "setups",
        "sweeps",
        "available_results",
    }
)

SpecBuilder = Callable[[Session], tuple[CapabilitySpec, ...]]


class RecordingSink:
    """In-memory ``AuditSink``: appends to a list, never touches a file."""

    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


class RaisingSink:
    """A sink whose append always fails — drives the broker's fail-closed path,
    which reaches W-5 as an ``AuditFailure`` in place of the result."""

    def append(self, record: AuditRecord) -> None:
        raise OSError("simulated audit sink failure")


def scoped_broker(
    scenario: Scenario | None = None,
    *,
    specs: SpecBuilder = session_routed_specs,
    sink: RecordingSink | RaisingSink | None = None,
    confirmer: Confirmer | None = None,
    broker_class: type[Broker] = Broker,
) -> tuple[Broker, RecordingSink | RaisingSink, Session, FakeAdapter]:
    """A broker whose session is ATTACHED with project+design selected — the
    prerequisite an inspection needs — over a ``FakeAdapter`` driven by
    ``scenario``.

    The attach/select drive calls the session DIRECTLY rather than dispatching,
    so the returned sink holds only the records the test's own call produced and
    a record count is a clean assertion. ``specs`` is a builder rather than a
    tuple because the broker's composition contract requires the handlers to be
    bound to the SAME session the broker holds.
    """
    fake = FakeAdapter(scenario) if scenario is not None else FakeAdapter()
    session = Session(fake)
    session.attach(DEFAULT_PID)
    session.select("project", PROJECT)
    session.select("design", DESIGN)
    sink = sink if sink is not None else RecordingSink()
    broker = broker_class(
        session=session,
        registry=CapabilityRegistry(specs(session)),
        audit_sink=sink,
        confirmer=confirmer if confirmer is not None else RefuseAllConfirmer(),
    )
    return broker, sink, session, fake


def detached_broker() -> tuple[Broker, RecordingSink, Session]:
    """A broker whose session was never attached — the ``refused_no_session``
    path."""
    session = Session(FakeAdapter())
    sink = RecordingSink()
    broker = Broker(
        session=session,
        registry=CapabilityRegistry(session_routed_specs(session)),
        audit_sink=sink,
        confirmer=RefuseAllConfirmer(),
    )
    return broker, sink, session


def without_capability(name: str) -> SpecBuilder:
    """Session-routed specs with one capability removed — the registry a
    ``UnknownCapability`` dispatch outcome comes from."""

    def build(session: Session) -> tuple[CapabilitySpec, ...]:
        return tuple(
            spec for spec in session_routed_specs(session) if spec.name != name
        )

    return build


def with_replacement(spec: CapabilitySpec) -> SpecBuilder:
    """Session-routed specs with one capability swapped for ``spec`` (matched by
    name). Synthetic non-safe tiers and canned handlers exist ONLY in test files
    — the shipped surface is 100% safe-tier and 100% session-bound."""

    def build(session: Session) -> tuple[CapabilitySpec, ...]:
        return tuple(
            spec if existing.name == spec.name else existing
            for existing in session_routed_specs(session)
        )

    return build


def canned_spec(
    name: str, result: object, *, tier: str = "safe"
) -> CapabilitySpec:
    """A spec returning ``result`` regardless of arguments — used to drive the
    dispatch-boundary arms that a correctly-wired session can never produce."""
    return CapabilitySpec(
        name=name,
        tier=tier,  # type: ignore[arg-type]
        handler=lambda **_kwargs: result,
        description=f"Synthetic {tier}-tier stand-in for {name} (test double).",
    )
