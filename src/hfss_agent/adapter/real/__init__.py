"""real adapter — the PyAEDT-backed ``Adapter``.

Importing this package is PyAEDT-free: it exposes ``RealAdapter`` (which imports
no AEDT API) and a ``make_live_adapter`` factory. Only *calling* the factory
lazily imports ``real.session`` — the one module permitted to import the AEDT API
— so ``import hfss_agent.adapter.real`` never pulls PyAEDT into ``sys.modules``.
The import audit (tests/boundary) enforces that boundary.

The factory is deliberately named ``make_*`` rather than ``create_*``: this whole
package is scanned by the read-only AST audit, whose mutation denylist includes
the ``create_`` prefix (AEDT editor mutators), so no name here should carry it.
"""

from __future__ import annotations

from hfss_agent.adapter.real.real_adapter import RealAdapter

__all__ = ["RealAdapter", "make_live_adapter"]


def make_live_adapter(timeout_seconds: float | None = None) -> RealAdapter:
    """Attach-capable ``RealAdapter`` wired to a live ``LiveSession``.

    The ``LiveSession`` import is deferred to here so the AEDT API loads only when
    a live session is actually requested — never at package-import time. The
    returned adapter is not yet attached; call ``.attach(process_id)``.
    """
    from hfss_agent.adapter.real.session import LiveSession
    from hfss_agent.adapter.watchdog import DEFAULT_TIMEOUT_SECONDS

    timeout = DEFAULT_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    return RealAdapter(LiveSession(), timeout_seconds=timeout)
