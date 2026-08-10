"""W-9 · gating — solution-validity gating. Permanent home: the open wrapper (ADR-12).

Pure functions over the snapshot, importing only ``hfss_agent.contract`` and
carrying the same static import audit applied to engine code (ADR-4). Runs the
four deterministic gates (solution exists / convergence / freshness / target
coverage) before any metric is computed or interpreted; on failure, reports why
and refuses interpretation. Touches no PyAEDT, files, or session state.

THE PUBLIC SURFACE IS ``evaluate_gates`` AND ``GATE_NAMES``, and nothing else.
A caller wanting the gate set wants all four in order; reaching for one gate alone
is the shape that lets a caller construct a partial gate list, which is exactly
what W-7 cannot detect (it "does not itself confirm that this is the complete set
of four"). The per-gate modules stay importable -- Python has no way to prevent it
and the calculation_ref strings must resolve -- but they are not re-exported here,
so the obvious call is the complete one.

``common`` IS DELIBERATELY NOT EXPORTED. It holds the provenance stamp, the
judgment axes and the identifier convention that the gates share; it is internal
machinery, not something a caller composes with.
"""

from hfss_agent.gating.gates import GATE_NAMES, evaluate_gates

__all__ = [
    "evaluate_gates",
    "GATE_NAMES",
]
