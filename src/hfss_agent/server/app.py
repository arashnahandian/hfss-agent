"""The MCP application object (W-1, Step 2.8): tools registered onto ``MCPServer``.

SCAFFOLDING ONLY — the charter's phrase, and this module is where it is easiest
to violate. Nothing here computes, judges, formats, or decides anything. A tool
function's whole body is: hand the arguments to a feature module, hand its result
back. Any line that inspects a result, branches on it, or builds a message from
it is business logic that belongs to the module that owns the outcome.

EVERY TOOL IS WRAPPED IN ``serialized``. That is not optional and not a
per-tool judgment call — see ``serialization`` for the measured race it prevents
and, importantly, for what it does NOT cover. A reflection test walks the
registered tools and fails if any one of them is missing the marker, so a tool
added later without it does not ship quietly.

WHAT IS DELIBERATELY NOT HERE YET. None of the seventeen §3 tools are registered
in this step; they arrive in Part 6, replacing the throwaway probe below.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from hfss_agent.server.adapter_selection import FAKE, LIVE
from hfss_agent.server.composition import Composition
from hfss_agent.server.serialization import serialized

_SERVER_NAME = "hfss-agent"

# Appended to the server name when the simulated backend is in use. Short,
# because a client renders the name in constrained places, and upper-case
# because it is the only part of the name a human is meant to notice.
_FAKE_NAME_SUFFIX = " (SIMULATED)"

# Handed to the client at initialize. THIS IS A DISCLOSURE, NOT A GUARD, and the
# wording is careful about the difference for a reason.
#
# A disclosure tells the host something true and hopes it is surfaced. It cannot
# enforce anything: the host may render `instructions`, summarise it, or ignore
# it entirely, and nothing downstream is changed by its presence. In particular
# — and this is the sentence that must not be softened — the VALUES this server
# returns while simulated are NOT marked, NOT flagged, and NOT distinguishable
# from live ones by any field of any response. ``Environment``'s four fields are
# all filled with realistic values, its ``pyaedt_version`` is literally the
# pinned real version, and ``preflight_environment`` against a fake-backed
# broker reports ``overall="ok"`` with ``aedt_version_source="attached_session"``.
#
# Writing this text as though it made the data identifiable would be the precise
# defect it exists to prevent: a disclosure that understates its own hole. So it
# says what it is, once, at the only moment it is guaranteed to be delivered.
_FAKE_INSTRUCTIONS = (
    "SIMULATED DATA. This server was started with --adapter fake and is NOT "
    "connected to Ansys HFSS. Every value it returns -- versions, project and "
    "design names, validation messages, solve state, S-parameters, metrics -- "
    "is canned test data invented by this package. None of it was measured from "
    "any design.\n\n"
    "Do not report any value from this server as a measurement, a simulation "
    "result, or a property of a real design, and do not use it to answer a "
    "question about real hardware.\n\n"
    "This notice is the ONLY indication that the data is simulated. Individual "
    "responses carry no marker: their fields, provenance stamps and environment "
    "versions are indistinguishable from a live session's. If this notice is "
    "not carried forward into the conversation, nothing later will reveal it."
)

# The live counterpart. Deliberately does NOT claim the data is verified or
# correct -- it states what the connection is, and nothing more.
_LIVE_INSTRUCTIONS = (
    "Read-only, attach-only access to a running Ansys HFSS (AEDT) session on "
    "this machine. Values are read from that session or computed by this "
    "package's open, referenceable formulas; where something cannot be read or "
    "evaluated, the response says so rather than estimating."
)


def build_app(composition: Composition, *, adapter_kind: str) -> MCPServer:
    """The configured ``MCPServer``, with no transport started.

    Args:
        composition: the wired object graph. Taken explicitly rather than built
            here, so a test can stand the app up against a ``FakeAdapter``
            composition without touching the default data directory.
        adapter_kind: ``LIVE`` or ``FAKE`` — which backend ``composition`` was
            built over. KEYWORD-ONLY AND UNDEFAULTED, because a default would
            mean a caller could omit it and get the live wording over a fake
            adapter, which is the one combination that must be impossible to
            reach by accident. It is passed rather than sniffed from the
            composition: ``Composition`` holds an ``Adapter``, and deciding
            "is this the fake one?" by isinstance would put a second, quietly
            divergent answer next to ``select_adapter``'s.

    Building the app performs no I/O and no adapter round trip.
    """
    simulated = adapter_kind == FAKE
    server = MCPServer(
        name=_SERVER_NAME + (_FAKE_NAME_SUFFIX if simulated else ""),
        version=_wrapper_version(),
        instructions=_FAKE_INSTRUCTIONS if simulated else _LIVE_INSTRUCTIONS,
    )

    # -- THROWAWAY, PART 6 FODDER — DELETE WHEN THE REAL TOOLS LAND ------------
    # Exists for exactly one reason: to prove a client can complete a handshake
    # and round-trip a call against this server. It is NOT one of the seventeen
    # §3 tools, touches no feature module, reaches no adapter, and reads no
    # session state. It is wrapped in ``serialized`` anyway -- not because it
    # needs to be, but because the reflection test admits no exceptions and an
    # exemption list is how that test would start to rot.
    @server.tool(
        name="__handshake_probe",
        description=(
            "Disposable connectivity probe (Step 2.8 scaffolding). Returns its "
            "input unchanged. Not a Tier 1 tool; slated for deletion in Part 6."
        ),
    )
    @serialized
    def handshake_probe(echo: str) -> str:
        return echo

    return server


def _wrapper_version() -> str:
    """This package's version, or a truthful placeholder when it cannot be read.

    Deliberately does NOT fabricate a plausible version on failure. An
    unreadable distribution is rare (an editable install mid-rebuild), and a
    made-up number reported to a client as the server version is exactly the
    class of quiet lie this repo refuses elsewhere — ``preflight`` keeps
    "absent" and "unreadable" distinct for the same reason. The literal string
    below cannot be mistaken for a real version.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("hfss-agent")
    except PackageNotFoundError:
        return "0.0.0+unknown"


__all__ = ["build_app", "LIVE", "FAKE"]
