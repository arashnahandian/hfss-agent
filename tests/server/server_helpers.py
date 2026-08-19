"""Shared fixtures for the W-1 server tests.

Two composition shapes, deliberately different:

  * ``fast_broker`` builds the broker DIRECTLY with an in-memory audit sink,
    mirroring ``tests/inspect/inspect_helpers.py``. The concurrency tests drive
    hundreds of rounds, and the real append-only writer costs ~13 ms per record
    (open, newline-guard read, open, write) -- enough to turn a 1-second test
    into a 13-second one while measuring nothing the lock is responsible for.
  * ``real_writer_composition`` uses the production ``build_composition`` with a
    real ``AuditLogWriter`` under ``tmp_path``. The audit-integrity test needs
    the real writer, because the defect it measures is IN that writer.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from hfss_agent.adapter.fake import FakeAdapter
from hfss_agent.broker import (
    Broker,
    CapabilityRegistry,
    RefuseAllConfirmer,
    session_routed_specs,
)
from hfss_agent.contract import AuditRecord
from hfss_agent.preflight import VersionRead
from hfss_agent.server import build_composition, serialized
from hfss_agent.session import Session

DEFAULT_PID = 4242


class RecordingSink:
    """In-memory audit sink: keeps what it was handed, touches no disk."""

    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


def found() -> VersionRead:
    """A ``pyaedt_version`` probe reporting an installed PyAEDT."""
    return VersionRead("1.2.0", "found")


def absent() -> VersionRead:
    """A probe reporting PyAEDT is not installed -- the CI machine's real state."""
    return VersionRead(None, "absent")


def unreadable() -> VersionRead:
    """A probe reporting PyAEDT present but with unreadable metadata."""
    return VersionRead(None, "unreadable")


def fast_broker() -> tuple[Session, Broker]:
    """An ATTACHED session plus a broker over an in-memory sink."""
    session = Session(FakeAdapter())
    session.attach(DEFAULT_PID)
    broker = Broker(
        session=session,
        registry=CapabilityRegistry(session_routed_specs(session)),
        audit_sink=RecordingSink(),
        confirmer=RefuseAllConfirmer(),
    )
    return session, broker


def real_writer_composition(data_dir: str):
    """The production composition over a ``FakeAdapter``, real audit writer."""
    composition = build_composition(FakeAdapter(), data_dir=data_dir)
    composition.session.attach(DEFAULT_PID)
    return composition


def selection_server(broker: Broker, *, serialize: bool) -> MCPServer:
    """An ``MCPServer`` with one tool that drives a two-stage selection.

    THE TOOL BODY IS A STAND-IN, AND THE SEAM UNDER TEST IS NOT. The seventeen
    real tools land in Part 6; until then this body plays the part of an
    assembler-backed tool -- two broker dispatches whose interleaving is exactly
    what produced the measured race. Everything around it is production code:
    the real ``MCPServer.call_tool`` entry point, the real ``serialized``
    decorator, the real process-wide ``TOOL_DISPATCH_LOCK``, and a real
    ``Session``/``Broker``/``FakeAdapter`` chain.

    ``serialize=False`` exists so the tests can prove the lock is what makes the
    difference, rather than asserting a green result that might have been green
    anyway.
    """

    def drive_selection(tag: str) -> str:
        broker.dispatch("select", {"stage": "project", "choice": "P" + tag})
        broker.dispatch("select", {"stage": "design", "choice": "D" + tag})
        return tag

    server = MCPServer(name="selection-probe", version="0")
    server.add_tool(
        serialized(drive_selection) if serialize else drive_selection,
        name="drive_selection",
        description="Stand-in for an assembler-backed tool: two dispatches.",
    )
    return server


def mismatched(session: Session) -> bool:
    """Whether the final chain pairs one caller's project with another's design.

    Each caller selects ``P<i>`` then ``D<i>``, so a correct final chain has
    matching indices. ``P2``/``D0`` is a state NO caller requested and no
    sequential execution could produce.
    """
    chain = session.get_session_status().selection
    if chain.project is None or chain.design is None:
        return False
    return chain.project.name[1:] != chain.design[1:]
