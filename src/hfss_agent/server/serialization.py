"""Process-wide tool-dispatch serialization (W-1, Step 2.8).

WHY THIS EXISTS, MEASURED RATHER THAN FEARED. The MCP SDK serves tool calls
CONCURRENTLY: a synchronous handler runs on an AnyIO worker thread, and four
overlapping calls were measured running four handlers at once. Nothing below
this layer is thread-safe. ``Session`` holds the selection chain in a plain
attribute and mirrors the adapter's chain into it after each call; the adapter
keeps its own scoping cache the same way. Both are read-modify-write.

Driven from four threads with no lock and no artificial delay, that produced,
in 200 rounds: 20 final selection chains pairing one caller's project with
another caller's design -- a state no caller requested -- and 2 rounds where
``Session``'s chain and the adapter's own ``_selection`` disagreed outright,
falsifying ``session.py``'s claim that the two "can never diverge". The
consequence is the one this product exists to prevent: a read scoped to design
D2 returned under a provenance stamp naming design D1. Wrong data, honest-looking
stamp.

WHY AT THIS LAYER AND NOT LOWER. Measured, three placements:

  * HERE (whole tool invocation) -- the only placement that covers the
    assembler-backed tools. ``inspect_design`` is not one dispatch, it is an
    assembler that dispatches twice (the read, then ``get_session_status`` for
    the stamp).
  * In ``Broker.dispatch`` -- REJECTED. Two concurrent assemblies interleaved
    their inner dispatches: T2 read, T1 read, T1 stamped, T2 stamped. That is
    worse than no lock, because the result looks protected while the stamp comes
    from a chain another caller moved.
  * In ``Session`` -- REJECTED. Covers less than the broker placement, and
    misses ``preflight_environment`` and ``export_diagnostics_bundle`` almost
    entirely.

WHY ``RLock`` RATHER THAN ``Lock``. Today a plain ``Lock`` would suffice: there
is no second lock at any lower layer, so nothing re-enters. ``RLock`` is here so
that stays true by accident rather than by luck -- a non-reentrant lock at two
layers was measured to DEADLOCK on the first ``inspect_design``, because the
assembler re-enters through ``Broker.dispatch``. If anyone later adds a lock
below, this one will not be the thing that hangs the server.

============================================================================
WHAT THIS LOCK DOES NOT COVER -- READ THIS BEFORE TRUSTING IT
============================================================================
"We added a lock" does NOT mean "concurrent state is now safe". One specific
hole was measured and cannot be closed by any mutex:

An adapter call that exceeds its watchdog timeout is ABANDONED, not cancelled
(ADR-10): control returns to the caller with an ``AdapterTimeout`` while the
worker thread KEEPS RUNNING. That orphan never asks for this lock, so it can
write ``adapter._selection`` after this lock has been released -- and was
measured writing while a later, properly-serialized call held it. Observed
event order: NEXT-CALLER-ACQUIRED-LOCK, NEXT-CALLER-RUNNING, ORPHAN-WRITE.

That path is covered by the SUSPECT / re-verify protocol, not by this lock: a
timeout marks the session suspect, and ``reconnect_guarded`` forces a re-verify
before the next operation runs. The hazard is pre-existing and identical
single-threaded; this lock neither creates nor fixes it. If you are reasoning
about post-timeout state, reason about ``Session._verify``, not about this file.

Two smaller exclusions, stated so the boundary is complete:
  * Anything that reaches the object graph WITHOUT going through a decorated
    tool -- a test driving ``Session`` directly, or a future non-tool entry
    point -- is unserialized by construction. The reflection test in
    ``tests/server`` is what keeps the tool surface honest.
  * A second ``Broker`` in the same process on the same ``data_dir`` would
    reintroduce two audit-log writers. The composition root builds exactly one;
    nothing enforces that beyond it building exactly one.
============================================================================

THE COST, MEASURED AND ACCEPTED. Every tool call serializes behind every other,
and the hold is NOT bounded by ADR-10's watchdog -- that watchdog wraps adapter
primitives only (``adapter/base.py``), and seven paths below a tool handler are
outside it: audit append (~13 ms, paid twice by a two-dispatch assembler),
``read_audit_records`` (whole file, linear, on a log that is never rotated), the
diagnostics bundle, ``os.fsync`` in the export writes, the intent store,
``compute_metrics``' array work, and the preflight probes. The alternative was
measured too: declaring handlers ``async`` also serializes, but stalls the
transport completely -- an unrelated tool waited 0.81 s during a 1.0 s block,
against 0.02 s with this lock, because a sync handler on a worker thread leaves
the event loop free.
"""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable
from typing import TypeVar

_F = TypeVar("_F", bound=Callable[..., object])

# THE one lock. Module-level, so every decorated tool in the process shares it
# regardless of how many ``MCPServer`` or ``Composition`` objects exist. Not
# stored on the app or the composition deliberately: a per-instance lock would
# silently stop serializing the moment a second instance appeared, which is
# exactly the failure this is here to prevent.
TOOL_DISPATCH_LOCK = threading.RLock()


def serialized(tool: _F) -> _F:
    """Run ``tool`` holding the process-wide dispatch lock.

    Applied BELOW the registration decorator, so the registered callable is the
    wrapper::

        @server.tool(name="...", description="...")
        @serialized
        def some_tool(...): ...

    ``functools.wraps`` is load-bearing, not cosmetic: the SDK builds each
    tool's input schema by introspecting the registered callable's signature,
    and ``wraps`` sets ``__wrapped__`` so ``inspect.signature`` sees through to
    the real parameters. Measured -- a wrapped ``(echo: str, count: int = 2)``
    produces the same schema as the unwrapped one, including the default.

    The ``__serialized__`` marker follows ``session.py``'s ``reconnect_guarded``
    precedent exactly: the wrapper carries a flag so a reflection test can prove
    EVERY registered tool is wrapped, and a tool added later without it fails
    that test rather than silently shipping unserialized.
    """

    @functools.wraps(tool)
    def wrapper(*args: object, **kwargs: object) -> object:
        with TOOL_DISPATCH_LOCK:
            return tool(*args, **kwargs)

    wrapper.__serialized__ = True  # type: ignore[attr-defined]
    return wrapper  # type: ignore[return-value]
