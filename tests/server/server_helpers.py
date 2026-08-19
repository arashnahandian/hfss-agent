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

``composed_app`` is the third and is the one the completeness proof uses: the
production composition AND the production ``build_app``, with the tool names read
back off the server the way a client reads them. Nothing about the surface is
written down here -- that is the entire point, since a helper that returned a
hand-written list would make the completeness test compare a list to itself.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from mcp import ClientSession
from mcp.server.mcpserver import MCPServer
from mcp.shared.memory import create_client_server_memory_streams

from hfss_agent.adapter.fake import FakeAdapter
from hfss_agent.broker import (
    Broker,
    CapabilityRegistry,
    RefuseAllConfirmer,
    session_routed_specs,
)
from hfss_agent.contract import AuditRecord
from hfss_agent.preflight import VersionRead
from hfss_agent.server import FAKE, Composition, build_composition, serialized
from hfss_agent.server.app import build_app
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


def registered_tool_names(app: MCPServer) -> set[str]:
    """The tool names a CLIENT would see, read off the server.

    Goes through ``list_tools()`` rather than the private ``_tool_manager``
    because that is the call a client actually makes; the completeness suite
    separately pins that the two agree.
    """
    return {tool.name for tool in asyncio.run(app.list_tools())}


def composed_app(
    tmp_path: Path, *, want_app: bool = False
) -> tuple[Composition | MCPServer, set[str]]:
    """The production composition and app over a ``FakeAdapter``, plus the tool
    names read back off it.

    Returns the ``Composition`` by default because most completeness checks need
    the registry; ``want_app=True`` returns the ``MCPServer`` for the two checks
    that interrogate the server object itself. One helper rather than two so
    every caller is provably looking at the SAME server the names came from.
    """
    composition = build_composition(FakeAdapter(), data_dir=str(tmp_path))
    app = build_app(composition, adapter_kind=FAKE)
    return (app if want_app else composition), registered_tool_names(app)


# --- a real MCP client, in process -------------------------------------------
#
# WHY THIS EXISTS. Until Part 10 the whole server suite read METADATA off the
# app -- ``list_tools()`` names, ``_tool_manager._tools`` keys, ``app.name``,
# ``app.instructions`` -- and the only ``call_tool`` in the suite went to
# ``selection_server`` above, a STAND-IN with a stand-in tool. Not one of the
# eleven registered handlers was ever executed, so the Done bar's "a local MCP
# client can complete a handshake and call at least one tool end-to-end" was
# true in fact and proved by nothing.


@asynccontextmanager
async def connected_client(app: MCPServer):
    """A real ``ClientSession`` speaking MCP to ``app`` over memory streams.

    THE SDK'S OWN SERVER LOOP, NOT A SIMULATION OF ONE. The server side is
    ``app._lowlevel_server.run(...)`` -- the same coroutine ``app.run("stdio")``
    ends up driving -- with anyio memory streams standing in for the process's
    two file descriptors. ``initialize``, ``list_tools`` and ``call_tool`` are
    therefore real protocol round trips: request/response correlation, JSON-RPC
    framing and result serialization all happen.

    IN PROCESS RATHER THAN BY SPAWNING ``hfss-agent.exe``, deliberately. A
    subprocess would additionally cover the console-script shim and the stdio
    file descriptors, and would cost every test an install step, a start-up
    race, and a platform-specific executable path. The transport is not what
    these tests are about; the eleven handlers are. ``__main__``'s own wiring is
    covered separately in ``test_entry_point.py``.

    Yields:
        ``(session, init)`` -- the connected client and the ``InitializeResult``
        from the handshake, so a caller can assert on the server name, version
        and instructions AS A CLIENT RECEIVES THEM rather than by reading the
        attributes off the app object.
    """
    async with create_client_server_memory_streams() as (client_side, server_side):
        client_read, client_write = client_side
        server_read, server_write = server_side
        low = app._lowlevel_server
        async with anyio.create_task_group() as group:
            group.start_soon(
                low.run,
                server_read,
                server_write,
                low.create_initialization_options(),
            )
            async with ClientSession(client_read, client_write) as session:
                init = await session.initialize()
                yield session, init
            # The server loop has no other reason to end; without this the task
            # group would wait on it forever.
            group.cancel_scope.cancel()


def drive_client(app: MCPServer, work):
    """Run ``work(session, init)`` against ``app`` and return what it returns.

    Exists so the tests stay synchronous and readable; ``work`` is an async
    callable taking the connected session and the handshake result.
    """

    async def run():
        async with connected_client(app) as (session, init):
            return await work(session, init)

    return asyncio.run(run())


# --- the wire-shape split (app.py's "A WIRE-SHAPE ASYMMETRY") -----------------
#
# The SDK derives each tool's structured content from its RETURN ANNOTATION, and
# treats a UNION return differently from a single model: a union nests the
# payload under ``result``, a single model is flat. ``app.py`` records this at
# its module docstring as SDK behaviour rather than a choice made there, and
# warns that "a test (or a consumer) reading ``structured_content`` has to
# handle both shapes, and nothing in the signatures says so".
#
# So the split is written out HERE, per tool, rather than being discovered by
# each assertion. Two things follow. A test can ask for a payload without
# knowing the shape, and -- more usefully -- the split itself becomes an
# assertion: if the SDK ever changes how it serializes one of these, the
# agreement test in ``test_end_to_end.py`` fails and names the tool, instead of
# eleven assertions quietly reading ``None``.
NESTED_UNDER_RESULT = frozenset(
    {
        "attach",
        "list_selection_options",
        "select",
        "inspect_design",
        "export_diagnostics_bundle",
    }
)
FLAT_STRUCTURED = frozenset(
    {
        "preflight_environment",
        "get_session_status",
        "set_design_intent",
        "get_design_intent",
        "clear_design_intent",
        "get_audit_log",
    }
)


def payload(name: str, structured: dict) -> dict:
    """The tool's own payload, whichever shape the SDK gave it.

    Refuses a name it has no row for, rather than guessing a shape: an
    unclassified tool means the table above is stale, and silently defaulting to
    one shape is how a test starts reading ``None`` and asserting nothing.
    """
    if name in NESTED_UNDER_RESULT:
        assert set(structured) == {"result"}, (
            f"{name} is classified as union-returning (payload nested under "
            f"'result') but its structured content has keys "
            f"{sorted(structured)}. Update NESTED_UNDER_RESULT/FLAT_STRUCTURED "
            "in server_helpers -- the SDK's serialization has changed."
        )
        return structured["result"]
    if name in FLAT_STRUCTURED:
        assert "result" not in structured, (
            f"{name} is classified as single-model (flat payload) but its "
            "structured content nests under 'result'. Update "
            "NESTED_UNDER_RESULT/FLAT_STRUCTURED in server_helpers."
        )
        return structured
    raise AssertionError(
        f"{name!r} is in neither NESTED_UNDER_RESULT nor FLAT_STRUCTURED. Every "
        "registered tool must be classified, or a test reading its response "
        "would be assuming a shape."
    )
