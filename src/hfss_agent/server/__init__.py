"""W-1 · server — MCP surface (FastMCP, stdio transport).

Registers Tier 1 tools, validates I/O against the contract schemas, routes every
call to a feature module. Scaffolding only — no business logic, no direct PyAEDT.

The two paragraphs above are this package's original charter, kept verbatim from
the Step 0 scaffold because they still state what W-1 is for. Two corrections of
FACT are recorded here rather than by editing them, so the charter and its
amendments stay separately readable:

  * "FastMCP" IS NOW SPELLED ``MCPServer``. The official SDK renamed its
    ergonomic server class in mcp 2.0.0 — ``mcp.server.fastmcp.FastMCP`` no
    longer exists and there is no compatibility shim. The decorator and run
    signatures we use are unchanged, so this is a rename, not a redesign. The
    Stack Decision Record's Axis A wording ("FastMCP API") predates the rename.
  * "stdio transport" IS UNCHANGED AND LOAD-BEARING. Axis A chose stdio because
    it has no network listener at all — strictly stronger than binding to
    localhost. Any future HTTP transport requires its own ADR.

WHAT THIS PACKAGE MAY IMPORT, and why it is the widest allowance in the repo:
this is Layer 7, the composition root, so it imports ``broker``, ``preflight``,
``inspect``, ``validate_native``, ``snapshot``, ``gating``, ``metrics``,
``findings`` and ``contract`` — plus ``adapter``, which no other module above
Layer 2 may touch. The exception is narrow and deliberate: SOMETHING has to
construct the adapter that the session wraps, and the composition root is the
only layer that knows which one this process should get. It is confined to
``adapter_selection`` (see that module) and never spreads to the tool handlers.

NOTHING BELOW LAYER 7 IMPORTS THIS PACKAGE. That direction is the CI-enforced
one, and it is what keeps a protocol-version bump a contained change.
"""

from hfss_agent.server.adapter_selection import (
    ADAPTER_ENV_VAR,
    FAKE,
    LEGAL_ADAPTER_VALUES,
    LIVE,
    AdapterSelectionError,
    select_adapter,
)
from hfss_agent.server.composition import Composition, build_composition

__all__ = [
    # Adapter selection (fail-closed; see the module for the refusal ethos)
    "ADAPTER_ENV_VAR",
    "LEGAL_ADAPTER_VALUES",
    "LIVE",
    "FAKE",
    "AdapterSelectionError",
    "select_adapter",
    # The composition root
    "Composition",
    "build_composition",
]
