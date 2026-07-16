"""W-12 · contract — public Pydantic schemas (import-clean subpackage).

Importing this subpackage must never pull in ``pyaedt`` or anything I/O-capable;
the purity test in CI is load-bearing (ADR-3). The engine and ``gating`` depend
on it without tripping the import audit.
"""
