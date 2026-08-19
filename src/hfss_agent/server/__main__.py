"""Process entry point (W-1, Step 2.8): ``hfss-agent`` and ``python -m``.

IMPORTING THIS MODULE STARTS NOTHING. Every side effect — parsing arguments,
selecting an adapter, creating the data directory, binding the transport —
happens inside ``main()``. That is not tidiness: this module is named by
``[project.scripts]``, so a console-script shim imports it as
``hfss_agent.server.__main__`` to look up ``main``, and an import that started
serving would hijack that lookup. It also keeps the module importable by a test
that wants ``main`` without a server.

STDOUT BELONGS TO THE PROTOCOL. Under stdio transport the SDK claims file
descriptor 1 for JSON-RPC and points the process's own stdout at stderr for the
duration, so a stray ``print`` inside a handler lands on stderr rather than
corrupting a frame — measured, not assumed. That protection begins when serving
begins: anything written to stdout BEFORE ``run()`` reaches the real descriptor
and would sit ahead of the first frame. So every diagnostic here goes explicitly
to stderr, and nothing in this package prints to stdout at any point.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from hfss_agent.preflight import REAL_PROBES
from hfss_agent.server.adapter_selection import (
    ADAPTER_FLAG,
    LEGAL_ADAPTER_VALUES,
    LIVE,
    AdapterSelectionError,
    build_adapter,
    resolve_adapter_kind,
)
from hfss_agent.server.app import build_app
from hfss_agent.server.composition import build_composition

# Exit code for a refused startup. Distinct from 1 so a supervisor can tell a
# deliberate refusal from an unexpected crash.
REFUSED_EXIT_CODE = 2


def build_parser() -> argparse.ArgumentParser:
    """The command line.

    ``--adapter`` deliberately does NOT use argparse's ``choices=``. With
    ``choices`` argparse rejects a bad value itself, printing its own usage text
    and exiting before ``select_adapter`` is consulted — which would leave two
    refusal paths with two different wordings, only one of which names the fix
    and is ASCII-checked. Accepting any string here keeps the single refusal
    path the module docstring of ``adapter_selection`` describes.
    """
    parser = argparse.ArgumentParser(
        prog="hfss-agent",
        description=(
            "Read-only MCP server for Ansys HFSS. Attaches to a running AEDT "
            "session; never launches, modifies, or solves."
        ),
    )
    parser.add_argument(
        ADAPTER_FLAG,
        dest="adapter",
        default=None,
        metavar="{" + ",".join(LEGAL_ADAPTER_VALUES) + "}",
        help=(
            "Which backend to serve from. Omit for '"
            + LIVE
            + "' (attach to real HFSS). '"
            + "fake"
            + "' serves canned test data and is for development only; the "
            "server discloses it at handshake, but individual responses carry "
            "no marker."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Select the adapter, wire the graph, and serve MCP over stdio.

    Args:
        argv: the argument list, defaulting to the process's own. Injectable so
            a test drives the real parser and the real refusal path without
            touching ``sys.argv``.

    Returns:
        ``0`` on a clean shutdown, ``REFUSED_EXIT_CODE`` when startup was
        refused. Returned rather than raised so the console-script wrapper and
        ``python -m`` behave identically, and so a test can call ``main`` and
        assert on the code instead of catching ``SystemExit``.
    """
    args = build_parser().parse_args(argv)

    try:
        # Resolved ONCE and used twice — for construction and for the
        # disclosure. Deriving the kind a second time from args.adapter would be
        # a second source of truth about whether this process is simulated, and
        # the disclosure is the half that must never be wrong.
        adapter_kind = resolve_adapter_kind(args.adapter, REAL_PROBES.pyaedt_version)
    except AdapterSelectionError as refusal:
        # Two lines, because "what is wrong" and "what to do" are two things.
        print(f"hfss-agent: refusing to start: {refusal.reason}", file=sys.stderr)
        print(f"hfss-agent: {refusal.remedy}", file=sys.stderr)
        return REFUSED_EXIT_CODE

    adapter = build_adapter(adapter_kind)
    composition = build_composition(adapter)
    app = build_app(composition, adapter_kind=adapter_kind)
    # Blocks until the client disconnects or the process is signalled. "stdio"
    # is passed explicitly rather than relying on the SDK default: the transport
    # is a locked architectural decision (no network listener at all), and a
    # default is not the place to record one.
    app.run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
