"""Verified-results tool I/O (§3): check_solution_validity, compute_metrics,
get_solve_health, export_results.

compute_metrics carries the product's core promise structurally: its result is a
discriminated union whose arms make "metrics *and* failing gates" and "neither"
both unconstructible — no numbers on gate failure, enforced by the type, not by
convention.
"""

from typing import Annotated, Literal

from pydantic import Field

from hfss_agent.contract.common import StrictModel
from hfss_agent.contract.design_snapshot import SolveState
from hfss_agent.contract.finding import Finding
from hfss_agent.contract.intent_object import IntentObject
from hfss_agent.contract.metric_record import MetricRecord
from hfss_agent.contract.provenance_record import ProvenanceRecord
from hfss_agent.contract.tool_io.common import CannotEvaluate, ExportFormat

# --- check_solution_validity -------------------------------------------------


class SolutionValidityReport(StrictModel):
    """check_solution_validity response (§3, W-9): the four validity gates, each
    a five-state Finding with evidence. Thin named container over reused
    Findings — the gates ARE Findings (source="gate"); no new per-gate shape.
    """

    gates: list[Finding]
    template_text: str


class CheckSolutionValidityRequest(StrictModel):
    target_frequency: float | None = None


CheckSolutionValidityResult = SolutionValidityReport | CannotEvaluate


# --- compute_metrics (the core-promise schema) -------------------------------


class MetricsComputed(StrictModel):
    """compute_metrics success arm: gates passed, metrics returned.

    Has NO ``failing_gates`` field — a computed result cannot also carry gate
    failures. Reuses MetricRecord (each carries provenance and
    gate_status_at_computation).
    """

    outcome: Literal["metrics_computed"] = "metrics_computed"
    metrics: list[MetricRecord]
    template_text: str


class MetricsRefused(StrictModel):
    """compute_metrics refusal arm: one or more gates failed, so interpretation
    is refused and NO numbers are returned (§3).

    Has NO ``metrics`` field — "refused, but here are numbers anyway" is
    unconstructible. Carries the failing gate Findings (outcome ∈
    fail / insufficient_evidence).
    """

    outcome: Literal["gates_failed"] = "gates_failed"
    failing_gates: list[Finding]
    template_text: str


# Exactly one arm is ever inhabited. "metrics and failing gates" is impossible
# (distinct classes, each extra="forbid"); "neither populated" is impossible
# (each arm requires its payload). CannotEvaluate is the honest third state for
# "the gates could not even run" — not a metrics/refused claim with empty fields.
ComputeMetricsResult = Annotated[
    MetricsComputed | MetricsRefused | CannotEvaluate,
    Field(discriminator="outcome"),
]


class ComputeMetricsRequest(StrictModel):
    intent: IntentObject | None = None


# --- get_solve_health --------------------------------------------------------


class SolveHealthReport(StrictModel):
    """get_solve_health response (§3, W-8 solve-state readout): convergence
    history, ΔS progression, solver messages (already untrusted-string enveloped
    inside SolveState). Reuses SolveState wholesale, adding the ProvenanceRecord
    tying the readout to its selection + variation.
    """

    solve_state: SolveState
    provenance: ProvenanceRecord
    template_text: str


SolveHealthResult = SolveHealthReport | CannotEvaluate


# --- export_results ----------------------------------------------------------
# Response is the shared ExportResult (contract.tool_io.common), whose three
# arms are written / refused-existing-path / cannot_evaluate.


class ExportResultsRequest(StrictModel):
    format: ExportFormat
    path: str
    overwrite: bool = False
