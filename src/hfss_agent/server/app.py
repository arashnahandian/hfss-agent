"""The MCP application object (W-1, Step 2.8): tools registered onto ``MCPServer``.

SCAFFOLDING ONLY — the charter's phrase, and this module is where it is easiest
to violate. Nothing here computes, judges, formats, or decides anything. A tool
function's whole body is: hand the arguments to a feature module, hand its result
back. Any line that inspects a result, branches on it, or builds a message from
it is business logic that belongs to the module that owns the outcome.

WHAT IS DELIBERATELY NOT HERE YET. None of the seventeen §3 tools are registered
in this step. The composition root and the transport had to be proven to stand up
first, and registering a real tool before the process-wide dispatch lock exists
(Part 5) would expose the session state machine to the SDK's concurrent tool
dispatch — measured at four simultaneous handlers on separate worker threads.
Part 5 adds the lock and the tools together, in that order.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from hfss_agent.server.composition import Composition

# Surfaced to the client at handshake. Read from the installed distribution
# rather than hardcoded, so it cannot drift from pyproject's version.
_SERVER_NAME = "hfss-agent"


def build_app(composition: Composition) -> MCPServer:
    """The configured ``MCPServer``, with no transport started.

    Takes the composition explicitly rather than building one, so a test can
    stand the app up against a ``FakeAdapter`` composition without touching the
    environment or the default data directory. Building the app performs no
    I/O and no adapter round trip.
    """
    server = MCPServer(name=_SERVER_NAME, version=_wrapper_version())

    # -- THROWAWAY, PART 5 FODDER — DELETE WHEN THE REAL TOOLS LAND ------------
    # Exists for exactly one reason: to prove a client can complete a handshake
    # and round-trip a call against this server. It is NOT one of the seventeen
    # §3 tools, touches no feature module, reaches no adapter, and reads no
    # session state. When Part 5 registers the real surface behind the dispatch
    # lock, this goes with it — it must never appear in a shipped tool list,
    # where an LLM would see a tool that does nothing and try to use it.
    @server.tool(
        name="__handshake_probe",
        description=(
            "Disposable connectivity probe (Step 2.8 Part 4 scaffolding). "
            "Returns its input unchanged. Not a Tier 1 tool; slated for "
            "deletion in Part 5."
        ),
    )
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
