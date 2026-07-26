"""Shared helpers for the W-4 broker suite (Part 2).

Uniquely named (not ``conftest``) and imported explicitly, following the
session suite's stated rationale: sibling ``conftest`` modules from different
test dirs collide under pytest's rootdir import mode.

Everything here is in-memory — Part 2's hard constraint is NO file I/O — so
the audit sink double records ``AuditRecord`` objects in a list, and the
session-routed capabilities drive the licence-free ``FakeAdapter``.
"""

from __future__ import annotations

from pathlib import Path

from hfss_agent.adapter.fake import FakeAdapter, Scenario
from hfss_agent.broker import (
    Broker,
    CapabilityRegistry,
    CapabilitySpec,
    ConfirmationRequest,
    Confirmer,
    IntentStore,
    RefuseAllConfirmer,
    audit_capabilities,
    intent_capabilities,
    session_routed_specs,
)
from hfss_agent.broker.files import default_audit_log_path
from hfss_agent.contract import AuditRecord, RiskTier
from hfss_agent.session import Session

# Selection values matching the FakeAdapter's default scenario (the same
# constants the session suite pins), in chain order.
DEFAULT_PID = 1234
FULL_CHAIN: tuple[tuple[str, str], ...] = (
    ("project", "patch_antenna"),
    ("design", "HFSSDesign1"),
    ("setup", "Setup1"),
    ("sweep", "Sweep1"),
    ("variation", "sha256:defaultvariation"),
)


class RecordingSink:
    """In-memory ``AuditSink``: appends to a list, never touches a file."""

    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


class RaisingSink:
    """A sink whose append always fails — drives the fail-closed audit path."""

    def append(self, record: AuditRecord) -> None:
        raise OSError("simulated audit sink failure")


class ApproveAllConfirmer:
    """Approves everything and records what it was asked — proving both that
    medium proceeds on approval and that high never consults it at all."""

    def __init__(self) -> None:
        self.requests: list[ConfirmationRequest] = []

    def confirm(self, request: ConfirmationRequest) -> bool:
        self.requests.append(request)
        return True


class RecordingRefuseAllConfirmer(RefuseAllConfirmer):
    """The Tier 1 default behaviour (refuse everything), recording requests so
    tests can assert what the confirmer was — and was not — asked."""

    def __init__(self) -> None:
        self.requests: list[ConfirmationRequest] = []

    def confirm(self, request: ConfirmationRequest) -> bool:
        self.requests.append(request)
        return super().confirm(request)


class ExplodingConfirmer:
    """Raises if consulted — proves safe-tier dispatch never asks."""

    def confirm(self, request: ConfirmationRequest) -> bool:
        raise AssertionError("the confirmer must not be consulted")


class HandlerSpy:
    """Callable capability-handler double: records every invocation's kwargs,
    then returns a canned result or raises a scripted exception."""

    def __init__(
        self, result: object = "spy-result", raises: Exception | None = None
    ) -> None:
        self.result = result
        self.raises = raises
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises
        return self.result


def spec_for(
    handler: HandlerSpy, *, name: str = "synthetic", tier: RiskTier = "safe"
) -> CapabilitySpec:
    """A synthetic spec around a spy. Synthetic medium/high capabilities exist
    ONLY in test files — the production registry is 100% safe-tier."""
    return CapabilitySpec(
        name=name,
        tier=tier,
        handler=handler,
        description=f"Synthetic {tier}-tier capability (test double).",
    )


def make_broker(
    specs: tuple[CapabilitySpec, ...],
    *,
    confirmer: Confirmer | None = None,
    sink: RecordingSink | RaisingSink | None = None,
    session: Session | None = None,
) -> tuple[Broker, RecordingSink | RaisingSink]:
    """A broker over an in-memory sink and a fresh DETACHED fake-backed
    session (unless overridden). The default confirmer is the Tier 1
    refuse-all."""
    session = session if session is not None else Session(FakeAdapter())
    sink = sink if sink is not None else RecordingSink()
    confirmer = confirmer if confirmer is not None else RefuseAllConfirmer()
    broker = Broker(
        session=session,
        registry=CapabilityRegistry(tuple(specs)),
        audit_sink=sink,
        confirmer=confirmer,
    )
    return broker, sink


def session_broker(
    scenario: Scenario | None = None,
) -> tuple[Broker, RecordingSink, Session, FakeAdapter]:
    """A broker exposing the six session-routed capabilities over a
    ``FakeAdapter`` driven by ``scenario`` (default canned data otherwise)."""
    fake = FakeAdapter(scenario) if scenario is not None else FakeAdapter()
    session = Session(fake)
    sink = RecordingSink()
    broker = Broker(
        session=session,
        registry=CapabilityRegistry(session_routed_specs(session)),
        audit_sink=sink,
        confirmer=RefuseAllConfirmer(),
    )
    return broker, sink, session, fake


def audit_broker(tmp_path: Path) -> tuple[Broker, str, Session]:
    """A broker with the REAL audit writer (built by the Broker itself from
    ``data_dir`` — the Part 4 wiring), exposing the session-routed
    capabilities plus get_audit_log. Returns the log path for direct
    inspection."""
    session = Session(FakeAdapter())
    log_path = default_audit_log_path(str(tmp_path))
    broker = Broker(
        session=session,
        registry=CapabilityRegistry(
            session_routed_specs(session) + audit_capabilities(log_path)
        ),
        confirmer=RefuseAllConfirmer(),
        data_dir=str(tmp_path),
    )
    return broker, log_path, session


def intent_broker(
    tmp_path: Path,
) -> tuple[Broker, RecordingSink, IntentStore, Session]:
    """A broker exposing the session-routed AND intent capabilities, with the
    intent file on the test's ``tmp_path`` (constructor-injected path, plan
    §6e)."""
    session = Session(FakeAdapter())
    store = IntentStore(str(tmp_path / "intent.json"))
    sink = RecordingSink()
    broker = Broker(
        session=session,
        registry=CapabilityRegistry(
            session_routed_specs(session) + intent_capabilities(store, session)
        ),
        audit_sink=sink,
        confirmer=RefuseAllConfirmer(),
    )
    return broker, sink, store, session
