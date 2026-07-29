"""W-7 · metrics — open deterministic S-parameter calculations.

The approved Tier 1 metric set (S11 min, resonant frequency, S11 at target,
-10 dB bandwidth, VSWR at target, impedance at target) as pure, public,
individually referenceable formulas. Refuses to run before the W-9 gates pass.

The formulas themselves live in ``sparams`` and import only
``hfss_agent.contract`` and the standard library; see that module's docstring for
the reference-string convention, the one-variation rule, and why an out-of-range
target frequency raises rather than degrading gracefully.

``export`` holds the Touchstone/CSV export CONTENT generators (§1.1) under the
same contract-only constraint. They produce strings and nothing else -- the file
write goes through the broker. Unlike the metric formulas, export is general
N-port (Locked Idea Spec Point 5), and the export functions carry no reference
string: they emit no computed value, so there is nothing for a ``MetricRecord``
or a ``Finding`` to point at.
"""

from hfss_agent.metrics.export import (
    ExportContentError,
    csv_content,
    touchstone_content,
)
from hfss_agent.metrics.sparams import (
    FORMULA_REFS,
    IMPEDANCE_AT_TARGET_REF,
    MINUS_10_DB_THRESHOLD_DB,
    MINUS_10DB_BANDWIDTH_REF,
    NO_BAND_REASON,
    RESONANT_FREQUENCY_REF,
    S11_AT_TARGET_REF,
    S11_MIN_REF,
    VSWR_AT_TARGET_REF,
    Minus10dBBand,
    NoMinus10dBBand,
    impedance_at_target,
    minus_10db_bandwidth,
    resonant_frequency,
    s11_at_target,
    s11_min,
    vswr_at_target,
)

__all__ = [
    # The six referenceable formulas
    "s11_min",
    "resonant_frequency",
    "s11_at_target",
    "minus_10db_bandwidth",
    "vswr_at_target",
    "impedance_at_target",
    # The bandwidth result types -- two independent types, never one nullable one
    "Minus10dBBand",
    "NoMinus10dBBand",
    "NO_BAND_REASON",
    # Reference strings for MetricRecord.formula_ref / Finding.calculation_ref
    "S11_MIN_REF",
    "RESONANT_FREQUENCY_REF",
    "S11_AT_TARGET_REF",
    "MINUS_10DB_BANDWIDTH_REF",
    "VSWR_AT_TARGET_REF",
    "IMPEDANCE_AT_TARGET_REF",
    "FORMULA_REFS",
    "MINUS_10_DB_THRESHOLD_DB",
    # Export content generation -- strings only; the write is the broker's
    "touchstone_content",
    "csv_content",
    "ExportContentError",
]
