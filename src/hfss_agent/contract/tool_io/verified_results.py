"""Verified-results tool I/O (§3): check_solution_validity, compute_metrics,
get_solve_health, export_results.

compute_metrics carries the product's core promise structurally: its result is a
discriminated union whose arms make "metrics *and* a failed gate" and "neither"
both unconstructible — no numbers on gate failure, enforced by the type, not by
convention.

THE FOURTH ARM ADDED AT STEP 2.6a DOES NOT SOFTEN THAT PROMISE, and the sentence
above is stated in terms of a FAILED gate for exactly that reason.
``MetricsComputedWithCaveats`` carries numbers beside gate results that HEDGED —
a solve that stopped short of convergence, or a freshness check that could not
confirm currency — and its allow-list refuses a ``fail`` outright, so "numbers on
gate failure" stays unconstructible through it too.
"""

from typing import Annotated, Literal

from pydantic import Field, model_validator

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
    # The unit lives in the FIELD NAME, not only in prose, for the reason already
    # written at ``IntentObject.target_frequency_hz``: a caller reading the
    # schema, a rendered template, or an on-disk record sees "hz" without having
    # to find the sentence that states the assumption.
    #
    # RENAMED FROM ``target_frequency`` AT STEP 2.6a. The defect was not that one
    # field lacked a unit in the abstract — it was that this field and
    # ``IntentObject.target_frequency_hz`` name THE SAME QUANTITY under two
    # spellings, and a single Journey-2 sequence carries both (check_solution_
    # validity takes this, compute_metrics takes the IntentObject). Two spellings
    # for one quantity on one path is the drift that invites a caller to assume
    # they mean different things.
    target_frequency_hz: float | None = None


CheckSolutionValidityResult = SolutionValidityReport | CannotEvaluate


# --- compute_metrics (the core-promise schema) -------------------------------


class MetricsComputed(StrictModel):
    """compute_metrics clean arm: EVERY gate passed, metrics returned.

    Has NO ``failing_gates`` field — a computed result cannot also carry gate
    failures. Reuses MetricRecord (each carries provenance and
    gate_status_at_computation).

    THE CLEAN ARM AND ONLY THE CLEAN ONE, as of Step 2.6a. A result whose gates
    hedged goes to ``MetricsComputedWithCaveats``, a separate class rather than an
    optional caveat field here — an optional would make "clean" and "hedged" the
    same wire shape, distinguished only by whether a consumer remembered to look
    at a field that is usually empty.
    """

    outcome: Literal["metrics_computed"] = "metrics_computed"
    metrics: list[MetricRecord]
    template_text: str


# The gate outcomes that QUALIFY a metrics result rather than refusing it.
#
# AN ALLOW-LIST, NOT A DENY-LIST, and the direction is the entire point. This is
# ADR-25 decision 10's own reasoning applied one level over: that decision made
# ``"pass"`` an allow-list at the assembler because a deny-list would let a sixth
# ``FindingOutcome``, added later by someone with no reason to think about this
# file, DEFAULT TO PERMITTING numbers. The identical trap sits here, one step
# further in — a deny-list ("anything that is not ``fail``") would let that sixth
# member default to permitting numbers WITH A CAVEAT, which is the quieter form
# of the same failure and reads to a caller as a checked result rather than an
# unconsidered one. Written as an allow-list, a new outcome reaches this arm only
# by being added to this line, in a diff someone reviews.
#
# WHY EACH OF THE FIVE IS IN OR OUT, stated because an unlisted omission is
# indistinguishable from an unconsidered one (ADR-29 dec. 4):
#
#   * ``warning`` — IN. A solve that stopped without converging still produced
#     numbers, and AEDT itself warns in the Message Manager and proceeds into the
#     frequency sweep rather than withholding them. The ruling is to mirror the
#     solver: show the numbers with the warning attached. Making that expressible
#     is why this arm exists at all.
#   * ``insufficient_evidence`` — IN. The freshness gate could not confirm the
#     results are current — and on the real adapter it never can: freshness comes
#     back ``FreshnessEvidence(available_signals={}, determinable=False)`` with no
#     branch above it, unconditionally. Refusing on it would mean the tool never
#     shows a number on any real design, so the ruling is to show them under a
#     notice that currency could not be confirmed.
#   * ``fail`` — OUT, and this one IS the core promise. A gate that ran and said
#     no is the exact case "no numbers on gate failure" was written for; letting a
#     ``fail`` in here would defeat that promise through the arm added to soften
#     it.
#   * ``not_evaluated`` — OUT, deliberately rather than by oversight. A gate that
#     did not run produced no evidence, so there is nothing for it to qualify a
#     number WITH, and listing it as a caveat would assert that we looked. It is
#     also the one non-passing outcome no ruling covers, and an unruled state
#     refuses by default.
#   * ``pass`` — OUT, which is the exclusion a reader is least likely to expect.
#     ``qualifying_gates`` holds the gates that HEDGE the result, never the whole
#     gate set; a passing gate hedges nothing, and admitting one would let this
#     arm be filled entirely with passes — a result announcing a caveat in its own
#     ``outcome`` and naming none. ``MetricsRefused`` echoes only its non-passing
#     gates for the same reason.
GATE_OUTCOMES_THAT_QUALIFY_COMPUTATION: frozenset[str] = frozenset(
    {"warning", "insufficient_evidence"}
)


class MetricsComputedWithCaveats(StrictModel):
    """compute_metrics qualified arm: metrics returned WITH the gate results that
    qualify them (Step 2.6a).

    THE TWO CASES THIS EXISTS FOR, as ruled on rather than as inferred from a
    schema. A solve that stopped without converging has numbers, and AEDT warns
    and proceeds into the sweep rather than withholding them — so we mirror the
    solver instead of being stricter than it. And a freshness check that cannot
    confirm currency must not withhold them either, because the real adapter
    reports freshness undeterminable unconditionally, so refusing there would mean
    the tool never shows a number on any real design. See
    ``GATE_OUTCOMES_THAT_QUALIFY_COMPUTATION`` for both, and for why the other
    three outcomes still refuse.

    NUMBERS AND CAVEAT TRAVEL IN ONE OBJECT, which is the whole reason this is a
    type and not a paragraph appended to ``template_text``. Both fields are
    required, so the qualification cannot be dropped in transit, summarised away
    downstream, or missed by a consumer that reads ``metrics`` and nothing else.
    That is precisely what ``MetricsComputed`` could not do — it has no field able
    to carry a qualification, which is *why* a ``warning`` had to refuse before
    this arm existed, rather than a judgment that a warning deserved refusing.

    NOT A SUBCLASS OF ``MetricsComputed``, and the shared CLASS-NAME prefix is
    not a hint that it is one — the same independence the four provenance types
    hold. ``isinstance(result, MetricsComputed)`` is FALSE for one of these, and
    that is correct: a consumer that wants clean results only must not silently
    receive caveated ones.

    NAMED FOR THE UGLY-BUT-UNAMBIGUOUS READING, deliberately. "Qualified" carries
    both "hedged" and "certified" in English, and in an RF context the second is
    the louder one — qualification is what a part passes. A reader meeting
    ``MetricsQualified`` beside ``MetricsComputed`` would have had a coin-flip
    between "caveated" and "vetted", and getting it backwards means trusting
    numbers at precisely the moment they were flagged. The verbosity is the price
    of the name never being read as its own opposite.
    """

    # THE LITERAL DELIBERATELY DOES NOT MIRROR THE CLASS NAME, and restoring the
    # mirror would reintroduce a real defect rather than tidy anything.
    # ``metrics_computed_with_caveats`` would have ``MetricsComputed``'s literal
    # as a PROPER PREFIX, so a consumer routing on the string with ``startswith``
    # — or any prefix match — would read a caveated result as a clean one, which
    # is the exact distinction this arm exists to draw. Dropping the
    # ``computed_`` makes that collision UNCONSTRUCTIBLE instead of merely
    # documented, which is how this package handles dangerous states everywhere
    # else. ``MetricsRefused`` already decouples the two spaces (its literal is
    # ``gates_failed``), so there is no consistency to preserve by matching.
    # ``test_no_outcome_literal_is_a_prefix_of_another`` pins it over all four
    # arms, so a future arm cannot reintroduce the collision from the other side.
    outcome: Literal["metrics_with_caveats"] = "metrics_with_caveats"
    metrics: list[MetricRecord]
    # NON-EMPTY BY THE SCHEMA, unlike ``metrics`` beside it. An empty list here is
    # a specific dishonesty a type can prevent: this arm announces a caveat in its
    # own ``outcome``, so naming none would leave a caller told to be careful with
    # no statement of what about — and would make the arm indistinguishable in
    # content from ``MetricsComputed`` while still claiming to differ from it.
    # (``metrics=[]`` is a separate question, left where the existing decision put
    # it: constructible on both computed arms, refused by the producer, so the two
    # computed arms stay consistent with each other on that point.)
    qualifying_gates: Annotated[list[Finding], Field(min_length=1)]
    template_text: str

    @model_validator(mode="after")
    def _qualifying_gates_are_on_the_allow_list(self) -> "MetricsComputedWithCaveats":
        """No gate outcome outside the allow-list may accompany numbers.

        THE FIELD TYPE CANNOT DO THIS ON ITS OWN. ``Finding`` admits all five
        ``FindingOutcome`` members by design — it is the one shared shape for
        every judgment — so without this validator a ``fail`` could be placed in
        ``qualifying_gates`` and the result would carry numbers beside the single
        gate state this product promises never to report numbers for.

        RAISED AS A ``ValueError`` so it surfaces as a pydantic
        ``ValidationError``, which means the check holds on a WIRE PAYLOAD
        arriving as a dict and not merely on an object assembled in-process. That
        matters here more than at most validators: compute_metrics results are
        rendered by a layer that receives them as data.
        """
        disallowed = sorted(
            {
                finding.outcome
                for finding in self.qualifying_gates
                if finding.outcome not in GATE_OUTCOMES_THAT_QUALIFY_COMPUTATION
            }
        )
        if disallowed:
            raise ValueError(
                f"qualifying_gates carries gate outcome(s) {disallowed}, which do "
                "not qualify a metrics result; only "
                f"{sorted(GATE_OUTCOMES_THAT_QUALIFY_COMPUTATION)} do. Numbers may "
                "accompany a gate that hedged, never one that failed, did not run, "
                "or passed."
            )
        return self


class MetricsRefused(StrictModel):
    """compute_metrics refusal arm: the gates did not permit interpretation, so
    NO numbers are returned (§3).

    Has NO ``metrics`` field — "refused, but here are numbers anyway" is
    unconstructible.

    WHICH OUTCOMES LAND HERE IS THE PRODUCER'S RULE, NOT THIS SCHEMA'S, and the
    parenthetical that stood here ("outcome ∈ fail / insufficient_evidence") read
    as though it were this type's. It named two of the four the assembler actually
    routes here: ``warning`` and ``not_evaluated`` arrive too, which
    ``test_every_non_passing_outcome_refuses`` pins. ``failing_gates`` is a plain
    ``list[Finding]`` and always was.

    What Step 2.6a changed is that two of those four now have somewhere else they
    may go — see ``GATE_OUTCOMES_THAT_QUALIFY_COMPUTATION``. THE ASSEMBLER HAS NOT
    MOVED YET (Step 2.6b), so today every non-passing gate still arrives here and
    ``MetricsComputedWithCaveats`` has no producer.

    ``failing_gates`` IS A MILD MISNOMER for a warning or a not-evaluated gate.
    Kept, because renaming a field on a live wire shape costs more than the
    imprecision does, and each Finding's own five-state ``outcome`` is exact.
    """

    outcome: Literal["gates_failed"] = "gates_failed"
    failing_gates: list[Finding]
    template_text: str


# Exactly one arm is ever inhabited. "metrics and a FAILED gate" is impossible
# (distinct classes, each extra="forbid" — and the qualified arm's allow-list
# refuses a fail, so the arm that may carry both metrics and gate results cannot
# carry that combination); "neither populated" is impossible (each arm requires
# its payload). CannotEvaluate is the honest state for "the gates could not even
# run" — not a metrics/refused claim with empty fields.
#
# FOUR ARMS SINCE STEP 2.6a, ordered here as a severity gradient — clean,
# qualified, refused, could-not-run — so the declaration reads as the thing it is.
ComputeMetricsResult = Annotated[
    MetricsComputed | MetricsComputedWithCaveats | MetricsRefused | CannotEvaluate,
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
# Response is the shared ExportResult (contract.tool_io.common), whose FOUR arms
# are ExportWritten / ExportRefused / ExportFailed / CannotEvaluate.
#
# This comment said "three arms ... written / refused-existing-path /
# cannot_evaluate" until Step 2.4a, and was stale twice over. ExportFailed did
# not exist when it was written and the first contract amendment added it —
# without that arm there is no way to say a write BROKE mid-operation, possibly
# leaving an orphaned temp, as opposed to being refused before the disk was
# touched. And "refused-existing-path" named one of ExportRefused's three
# remedies as though it were the whole arm; the other two, refused_invalid_path
# and refused_network_path, send the caller somewhere completely different.


class ExportResultsRequest(StrictModel):
    format: ExportFormat
    path: str
    overwrite: bool = False
