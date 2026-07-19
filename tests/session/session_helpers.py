"""Shared helpers for the W-2 session suite (Part 3).

Everything drives the licence-free ``FakeAdapter``. Faults are injected via
scenario scripting (``behavior`` / ``behavior_sequence``) — never real sleeps or
tight timing assertions, so the suite is deterministic on Windows CI. A scripted
``fault=AdapterTimeout(...)`` makes the fake RETURN a timeout outcome directly:
no watchdog, no wall-clock wait.

Uniquely named (not ``conftest``) and imported explicitly, to dodge the pytest
gotcha where sibling ``conftest`` modules from different test dirs collide.
"""

from __future__ import annotations

from hfss_agent.adapter.fake import FakeAdapter, OpBehavior, Scenario
from hfss_agent.adapter.results import AdapterTimeout
from hfss_agent.session import Session
from hfss_agent.session.status import _Health

# Selection values matching the default FakeAdapter scenario, in chain order.
FULL_CHAIN: tuple[tuple[str, str], ...] = (
    ("project", "patch_antenna"),
    ("design", "HFSSDesign1"),
    ("setup", "Setup1"),
    ("sweep", "Sweep1"),
    ("variation", "sha256:defaultvariation"),
)
STAGES: tuple[str, ...] = tuple(stage for stage, _ in FULL_CHAIN)
PROJECT_PATH = r"C:\proj\patch_antenna.aedt"
SOLUTION_TYPE = "DrivenModal"
DEFAULT_PID = 1234


def make_session(scenario: Scenario | None = None) -> tuple[Session, FakeAdapter]:
    """A fresh (DETACHED) session over a FakeAdapter with the given scenario."""
    fake = FakeAdapter(scenario) if scenario is not None else FakeAdapter()
    return Session(fake), fake


def attached(scenario: Scenario | None = None) -> tuple[Session, FakeAdapter]:
    """A session attached to DEFAULT_PID. Any scenario scripts ops OTHER than
    attach, so the attach itself succeeds."""
    session, fake = make_session(scenario)
    status = session.attach(DEFAULT_PID)
    assert session._state.health is _Health.ATTACHED, status
    return session, fake


def build_full_chain(session: Session, stale_stage: str | None = None) -> None:
    """Select the full canned chain. If ``stale_stage`` is given, that stage gets
    a value the adapter's options do NOT contain — a deterministic proxy for "the
    design changed underneath us" (the static fake cannot vary its own data), so a
    later verify finds that stage absent and resets from it down."""
    for stage, choice in FULL_CHAIN:
        session.select(stage, "GHOST" if stage == stale_stage else choice)


def list_timeout_then(*later: OpBehavior) -> Scenario:
    """Scenario whose FIRST ``list_options`` call returns a timeout (a SUSPECT
    trigger with no real sleep) and whose later calls take ``later`` in order
    (falling through to canned data once exhausted). Chain-building uses only
    ``select``, so the trigger is deterministically the first ``list_options``
    call and a subsequent verify re-drives on calls 2+."""
    timeout = OpBehavior(
        fault=AdapterTimeout(operation="list_options", limit_seconds=1.0)
    )
    return Scenario(behavior_sequence={"list_options": [timeout, *later]})


def force_suspect(session: Session) -> None:
    """Drive an ATTACHED session to SUSPECT via the scripted first-``list_options``
    timeout. Requires the FakeAdapter built with ``list_timeout_then(...)``."""
    session.list_selection_options("project")
    assert session._state.health is _Health.SUSPECT
