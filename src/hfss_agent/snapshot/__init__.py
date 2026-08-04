"""W-8 · snapshot — the versioned wrapper->engine contract artifact.

Assembles the DesignSnapshot: identity/environment, selection, inspection data,
native-validation output, solve-state, raw solved-data series, variation context,
optional intent. Plain JSON-serializable data only — never live handles, sessions,
paths, or callables. Doubles as pre-change state capture for Tier 2.3 (ADR-6).

Evaluates nothing and calls nothing: the Layer-4 outputs arrive as DATA and are
composed, never fetched. This package imports ``contract`` only — no broker, no
session, no adapter — so the artifact that crosses the engine seam is built by a
module holding no capability that could have reached HFSS, the filesystem, the
network, or the OS.

The assembly itself lives in ``assembler``; see that module's docstring for what
the contract-only grant admits, the three reasons assembly refuses, what
``created_at`` means, why ``snapshot_id`` identifies a capture rather than a
design state, and why the variation hash is received as data and never computed
here.
"""

from hfss_agent.snapshot.assembler import SnapshotAssemblyError

__all__ = [
    "SnapshotAssemblyError",
]
