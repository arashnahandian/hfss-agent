"""W-3 · adapter — the ONLY module in either unit that imports ``pyaedt``.

A finite, whitelisted set of read/inspect/query/export operations; no mutating
PyAEDT method is reachable. Every call runs under a per-call watchdog and returns
data, a typed error, or the first-class ``cannot_evaluate`` outcome — never a hang.
"""
