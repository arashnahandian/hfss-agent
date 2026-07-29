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

``assembler`` is the entry point: it checks the W-9 gate results its caller hands
it, maps the six formulas onto the seven ``MetricRecord``s they produce, and
states every metric it could not report. It takes NO broker -- see its module
docstring for why that is a correctness decision about
``gate_status_at_computation`` rather than a scope one.
"""

from hfss_agent.metrics.assembler import (
    ALL_GATES_PASSED,
    AT_TARGET_METRICS,
    DB,
    GATE_OUTCOME_THAT_PERMITS_COMPUTATION,
    HZ,
    IMPEDANCE_AT_TARGET_REACTANCE,
    IMPEDANCE_AT_TARGET_RESISTANCE,
    METRIC_ORDER,
    MINUS_10DB_BANDWIDTH,
    NO_INTENT_REASON,
    OHM,
    RATIO,
    RESONANT_FREQUENCY,
    S11_AT_TARGET,
    S11_KEY,
    S11_MIN,
    VSWR_AT_TARGET,
    MetricsAssemblyError,
    compute_metrics,
)
from hfss_agent.metrics.export import (
    ExportContentError,
    csv_content,
    touchstone_content,
    touchstone_port_count,
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
    # The port count a .sNp filename must encode; policy on a mismatch is the
    # export_results tool's, at Step 3.4
    "touchstone_port_count",
    # The entry point, and the failure that discards a result rather than
    # reporting one it cannot vouch for
    "compute_metrics",
    "MetricsAssemblyError",
    # The seven record names, their canonical order, and the units they carry
    "METRIC_ORDER",
    "S11_MIN",
    "RESONANT_FREQUENCY",
    "MINUS_10DB_BANDWIDTH",
    "S11_AT_TARGET",
    "VSWR_AT_TARGET",
    "IMPEDANCE_AT_TARGET_RESISTANCE",
    "IMPEDANCE_AT_TARGET_REACTANCE",
    "AT_TARGET_METRICS",
    "DB",
    "HZ",
    "RATIO",
    "OHM",
    # The gate contract: the one permitting outcome, and the recorded status
    "GATE_OUTCOME_THAT_PERMITS_COMPUTATION",
    "ALL_GATES_PASSED",
    "NO_INTENT_REASON",
    "S11_KEY",
]
