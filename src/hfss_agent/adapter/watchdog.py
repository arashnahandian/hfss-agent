"""Per-call watchdog (W-3): bound every adapter call in wall-clock time.

Standalone and implementation-agnostic — the ``FakeAdapter`` now and the real
PyAEDT adapter later both route their primitive calls through it via the
``Adapter`` ABC's template method, so the timeout guarantee is inherited, never
re-implemented.

On timeout the call is ABANDONED, never pretend-cancelled (ADR-10, §6.7): a
stuck COM/gRPC call cannot be cancelled, so the worker runs on a daemon thread we
simply stop waiting on and leave to die with the process. The session module
reacts to the returned ``AdapterTimeout`` by marking the session suspect.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from hfss_agent.adapter.results import (
    AdapterInternalError,
    AdapterResult,
    AdapterTimeout,
)

# Default per-call bound. Generous enough for a live HFSS read; tests override it
# with a tiny value so a simulated hang resolves in milliseconds.
DEFAULT_TIMEOUT_SECONDS = 30.0


def run_with_watchdog(
    operation: Callable[[], AdapterResult[object]],
    timeout_seconds: float,
    name: str,
) -> AdapterResult[object]:
    """Run ``operation`` under a wall-clock bound. Always returns an outcome —
    never raises an operational error, never blocks past ``timeout_seconds``.
    """
    box: dict[str, object] = {}

    def target() -> None:
        # Catch ``Exception`` ONLY: operational errors become a typed outcome,
        # but interpreter-level signals (KeyboardInterrupt, SystemExit — both
        # BaseException, not Exception) are left alone rather than relabelled as
        # an adapter fault.
        try:
            box["value"] = operation()
        except Exception as exc:  # noqa: BLE001 - deliberately broad; see docstring
            box["error"] = exc

    worker = threading.Thread(target=target, name=f"adapter-op-{name}", daemon=True)
    worker.start()
    # A KeyboardInterrupt during a stuck call arrives on THIS (main) thread and
    # interrupts the join; we deliberately do not catch it, so Ctrl-C behaves like
    # Ctrl-C rather than becoming an adapter fault.
    worker.join(timeout_seconds)

    if worker.is_alive():
        # Abandon: do not join again. The daemon worker dies with the process.
        return AdapterTimeout(operation=name, limit_seconds=timeout_seconds)
    if "error" in box:
        exc = box["error"]
        return AdapterInternalError(detail=f"{type(exc).__name__}: {exc}")
    if "value" in box:
        return box["value"]
    # Reached only if the worker ended without producing either — e.g. a
    # BaseException that is not an Exception propagated out of the worker itself.
    # Report honestly rather than hang or hide it.
    return AdapterInternalError(detail=f"operation {name!r} produced no result")
