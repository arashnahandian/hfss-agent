"""The aggregator: run all four validity gates over one snapshot.

ALWAYS EXACTLY FOUR FINDINGS, ALWAYS IN THE SAME ORDER, for every snapshot shape
including a design that was never solved. Both halves are load-bearing:

  * FOUR, NEVER FEWER. A gate that could not decide emits a finding SAYING it
    could not decide; it is never omitted. Omitting one would make "the gate was
    not applicable" indistinguishable from "the gate was forgotten", which is the
    conflation ADR-28 refuses structurally elsewhere. It also matters downstream:
    W-7 states the count of gate results it was handed and admits it "does not
    itself confirm that this is the complete set of four" -- a short list would
    make that sentence quietly false rather than merely cautious.
  * IN ORDER, so ``template_text`` renderings and the audit log are
    byte-deterministic. The order is §1.1's own, and it is pinned against
    ``GATE_NAMES`` below rather than being whatever the imports happen to be.

NAMED ``gates`` RATHER THAN ``assembler``, unlike the five Layer-4/5 siblings that
all use that name. The deviation is deliberate: those modules ASSEMBLE a tool
result -- an ``InspectionResult``, a ``ComputeMetricsResult``, a
``DesignSnapshot`` -- whereas this one evaluates and returns a plain
``list[Finding]``. Calling it ``assembler`` would advertise the
``SolutionValidityReport`` composition it deliberately does not do: that report is
``check_solution_validity``'s response and belongs to Step 3.4, which ADR-25's
consequences assign the composition to in as many words ("Step 3.4 owns the
composition: constructing the gate list from ``evaluate_gates``").

DISPATCHES NON-UNIFORMLY, BY ONE GATE. ``target_coverage`` takes a second
parameter and the other three do not, because it is the only gate whose question
involves a value the caller names. The alternative -- giving all four an identical
signature with three of them ignoring the argument -- was rejected: a parameter a
function never reads asserts a capability that does not exist, which is the shape
``NativeValidationProvenance`` refuses in as many words and ADR-30 dec. 3
generalises. The asymmetry is paid for once, here, in a named place, instead of by
three signatures that would each be quietly untrue.
"""

from __future__ import annotations

from hfss_agent.contract import DesignSnapshot, Finding

# THE FOUR GATE MODULES BY THEIR OWN NAMES, not ``from hfss_agent.gating import
# convergence, ...``. Both spellings work and both create the same package-level
# cycle (``gating/__init__`` re-exports from here, and importing any submodule runs
# the parent's ``__init__`` first). The difference is in what each DEPENDS ON to
# work, and in what a static reader sees:
#
#   * The package-root spelling resolves through ``_handle_fromlist``'s fallback:
#     it first tries ``getattr`` on a PARTIALLY INITIALISED ``hfss_agent.gating``,
#     fails because ``__init__`` has not finished binding submodule attributes, and
#     only then re-enters the import machinery. It works on every supported
#     interpreter, but it works because of a fallback most readers do not know is
#     there.
#   * This spelling names the four modules directly, so nothing is looked up on a
#     half-built package object.
#
# AND IT IS WHAT THE IMPORT AUDIT SEES. Under the package-root spelling an AST scan
# records the dependency as ``hfss_agent.gating`` -- coarser than the truth, and
# indistinguishable from a module that genuinely reached for the package. Named
# individually, the audit sees exactly the four modules this one composes, which is
# what lets a per-file rule be written at all.
from hfss_agent.gating.convergence import evaluate as _convergence
from hfss_agent.gating.freshness import evaluate as _freshness
from hfss_agent.gating.solution_exists import evaluate as _solution_exists
from hfss_agent.gating.target_coverage import evaluate as _target_coverage

# THE FOUR GATES IN §1.1's ORDER -- solution exists, convergence, freshness,
# target coverage. Spelled out here rather than derived from the import list,
# because import order is not a decision and this is: the tuple is what makes the
# output order a stated property rather than an accident of how the module was
# written.
#
# THESE ARE THE NAMES THE REST OF THE SYSTEM ALREADY ASSUMES. Each gate's
# ``rule_id`` is ``gate.<name>`` and its ``calculation_ref`` is
# ``hfss_agent.gating.<name>:evaluate``; the Step 1.1 contract fixtures pinned both
# spellings before any gate existed. ``tests/metrics/assembly_helpers`` carries an
# independently written copy of this tuple for W-7's tests, which may not import
# this package -- the two are held to each other by nothing today, and a test
# asserting they agree is the obvious cheap guard whenever someone wants it.
GATE_NAMES: tuple[str, ...] = (
    "solution_exists",
    "convergence",
    "freshness",
    "target_coverage",
)


def evaluate_gates(
    snapshot: DesignSnapshot, target_frequency_hz: float | None = None
) -> list[Finding]:
    """Run the four validity gates and return their findings, in order.

    A PURE FUNCTION OF ITS ARGUMENTS. It reads a clock, mints no identifier, and
    reaches nothing -- so the same snapshot yields byte-identical findings forever,
    which is the property ADR-30 dec. 2 relies on when it refuses an
    ``evaluated_at`` field on ``FindingProvenance``.

    Args:
        snapshot: the artifact to judge. Never mutated; nothing is fetched.
        target_frequency_hz: the frequency to test coverage against, if the caller
            names one. Reaches ``target_coverage`` ALONE. When omitted, that gate
            falls back to ``snapshot.intent.target_frequency_hz``, and when neither
            exists it reports that it could not check rather than checking against
            an assumed value.

    Returns:
        Exactly four ``Finding``s in ``GATE_NAMES`` order. Never fewer, whatever
        the snapshot holds: a gate that could not decide says so in its outcome.

    Raises:
        Nothing, for a well-formed snapshot. Every state a gate cannot judge is an
        outcome rather than an exception -- the whole point of the five-state
        ``FindingOutcome``.
    """
    return [
        _solution_exists(snapshot),
        _convergence(snapshot),
        _freshness(snapshot),
        # THE ONE NON-UNIFORM CALL. See the module docstring for why this is a
        # dispatch here rather than three ignored parameters there.
        _target_coverage(snapshot, target_frequency_hz),
    ]
