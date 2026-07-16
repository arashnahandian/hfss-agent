"""W-9 · gating — solution-validity gating. Permanent home: the open wrapper (ADR-12).

Pure functions over the snapshot, importing only ``hfss_agent.contract`` and
carrying the same static import audit applied to engine code (ADR-4). Runs the
four deterministic gates (solution exists / convergence / freshness / target
coverage) before any metric is computed or interpreted; on failure, reports why
and refuses interpretation. Touches no PyAEDT, files, or session state.
"""
