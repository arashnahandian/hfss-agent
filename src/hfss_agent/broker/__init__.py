"""W-4 · broker — the capability broker (the load-bearing wall).

Sole gateway for every capability: routes all adapter calls, owns the action
allowlist and the three-tier risk taxonomy (safe/medium/high), performs ALL file
I/O for both units, and writes the append-only JSONL audit log. The engine is
never handed the broker or anything it guards.
"""
