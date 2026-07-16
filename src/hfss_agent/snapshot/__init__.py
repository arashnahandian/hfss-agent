"""W-8 · snapshot — the versioned wrapper->engine contract artifact.

Assembles the DesignSnapshot: identity/environment, selection, inspection data,
native-validation output, solve-state, raw solved-data series, variation context,
optional intent. Plain JSON-serializable data only — never live handles, sessions,
paths, or callables. Doubles as pre-change state capture for Tier 2.3 (ADR-6).
"""
