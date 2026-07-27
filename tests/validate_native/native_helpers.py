"""Shared helpers for the W-6 validate_native suite (Step 2.2b).

Everything drives the licence-free ``FakeAdapter`` through a REAL ``Broker`` —
W-6's only data path is a broker dispatch, so the assembler is exercised across
the boundary it actually uses rather than against a stubbed one. The audit sink
is in-memory, so the suite performs no file I/O.

Uniquely named (not ``conftest``) and imported explicitly, following the
session, broker, and inspect suites' stated rationale: sibling ``conftest``
modules from different test dirs collide under pytest's rootdir import mode.

DUPLICATES ``inspect_helpers`` ALMOST EXACTLY, and that is the accepted choice
rather than an oversight. Importing across suite directories would work only
through pytest's collection-order ``sys.path`` insertion, which is fragile and
would make this suite's importability depend on whether ``tests/inspect`` was
collected first. Duplication is the safer of the two.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from hfss_agent.adapter.fake import FakeAdapter, Scenario
from hfss_agent.broker import (
    Broker,
    CapabilityRegistry,
    CapabilitySpec,
    Confirmer,
    RefuseAllConfirmer,
    session_routed_specs,
)
from hfss_agent.contract import (
    CONTRACT_VERSION,
    AuditRecord,
    NativeValidation,
    NativeValidationProvenance,
)
from hfss_agent.contract.tool_io import NativeValidationBlock
from hfss_agent.session import Session

# The default FakeAdapter scenario's values — the same constants the session,
# broker, and inspect suites pin.
DEFAULT_PID = 1234
PROJECT = "patch_antenna"
DESIGN = "HFSSDesign1"
AEDT_VERSION = "2026.1"
WRAPPER_VERSION = "0.0.0"

# The default scenario's single ValidateDesign message.
DEFAULT_MESSAGE = "Design validation completed. 0 errors, 0 warnings."

SpecBuilder = Callable[[Session], tuple[CapabilitySpec, ...]]


class RecordingSink:
    """In-memory ``AuditSink``: appends to a list, never touches a file."""

    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


class RaisingSink:
    """A sink whose append always fails — drives the broker's fail-closed path,
    which reaches W-6 as an ``AuditFailure`` in place of the result."""

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
    whole prerequisite a native validation needs, since ValidateDesign is
    design-level — over a ``FakeAdapter`` driven by ``scenario``.

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


def canned_spec(name: str, result: object, *, tier: str = "safe") -> CapabilitySpec:
    """A spec returning ``result`` regardless of arguments — used to drive the
    dispatch-boundary arms that a correctly-wired session can never produce."""
    return CapabilitySpec(
        name=name,
        tier=tier,  # type: ignore[arg-type]
        handler=lambda **_kwargs: result,
        description=f"Synthetic {tier}-tier stand-in for {name} (test double).",
    )


def block_for(*messages: str) -> NativeValidationBlock:
    """A block with ``messages`` and a FIXED provenance — for the rendering
    tests, which are about ``native_template_text`` alone and must not vary by
    the instant they happen to run at.

    Built directly rather than through the broker on purpose: these tests hold
    the block constant and vary only message CONTENT, which is exactly the axis
    the framing-invariance guardrail measures.
    """
    return NativeValidationBlock(
        validation=NativeValidation(raw_output=list(messages)),
        provenance=NativeValidationProvenance(
            project=PROJECT,
            design=DESIGN,
            validated_at=datetime(2026, 7, 17, 9, 30, tzinfo=timezone.utc),
            contract_version=CONTRACT_VERSION,
            wrapper_version=WRAPPER_VERSION,
            validated_under_aedt_version=AEDT_VERSION,
        ),
    )
