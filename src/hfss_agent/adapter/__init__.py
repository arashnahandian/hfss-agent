"""W-3 · adapter — the ONLY module in either unit that imports ``pyaedt``.

A finite, whitelisted set of read/inspect/query/export operations; no mutating
PyAEDT method is reachable. Every call runs under a per-call watchdog and returns
data, a typed error, or the first-class ``cannot_evaluate`` outcome — never a hang.

This step (W-3, fake side) ships the interface, the reusable watchdog, the ADR-9
untrusted-string sanitizer, and the licence-free ``FakeAdapter``. No ``pyaedt``
import lives anywhere here yet; the real adapter is a separate, later step.
"""

from hfss_agent.adapter.base import Adapter
from hfss_agent.adapter.results import (
    AdapterCannotEvaluate,
    AdapterCrash,
    AdapterDisconnect,
    AdapterInternalError,
    AdapterOutcome,
    AdapterResult,
    AdapterTimeout,
    SessionFault,
)
from hfss_agent.adapter.sanitize import (
    MAX_UNTRUSTED_STR_LEN,
    sanitize_result,
    sanitize_str,
)
from hfss_agent.adapter.watchdog import DEFAULT_TIMEOUT_SECONDS, run_with_watchdog

__all__ = [
    # Interface
    "Adapter",
    # Outcome types (adapter-domain, deliberately outside the contract)
    "AdapterResult",
    "AdapterOutcome",
    "AdapterCannotEvaluate",
    "SessionFault",
    "AdapterTimeout",
    "AdapterCrash",
    "AdapterDisconnect",
    "AdapterInternalError",
    # Watchdog
    "run_with_watchdog",
    "DEFAULT_TIMEOUT_SECONDS",
    # Sanitization (ADR-9)
    "sanitize_result",
    "sanitize_str",
    "MAX_UNTRUSTED_STR_LEN",
]
