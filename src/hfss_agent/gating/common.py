"""Primitives every gate agrees on: the provenance stamp, the two judgment axes,
and the identifier convention.

SHARED SO THE GATES CANNOT DISAGREE, following ``contract/common.py``'s own stated
rationale one layer down -- it exists "so every schema that references them agrees
on the exact spelling", and the identical hazard sits here. Four gates each minting
a severity, a five-to-three classification map and a nine-field provenance would
drift, and the drift would be INVISIBLE: a ``Finding`` travels to W-10 and into a
tool response WITHOUT the snapshot beside it, so nothing downstream could
contradict whichever copy drifted.

NAMED ``common`` RATHER THAN ``provenance``, because the provenance builder is one
of four things it holds and four one-item modules would be worse than one named
for the role they share. ``contract/common.py`` and ``contract/tool_io/common.py``
already set that precedent for exactly this job.

PRIVATE TO THE PACKAGE, expressed by absence from ``gating/__init__.py`` rather
than by a leading underscore: no module anywhere in ``hfss_agent`` uses an
underscore prefix, and inventing the convention here for one file would be a
novelty a reader has to stop and interpret. W-9's public surface is the gates and,
from Part 4, their aggregator.

IMPORTING THIS MAKES ``hfss_agent.gating`` SELF-IMPORTABLE, which Part 5's import
audit must admit as an allowed root beside ``hfss_agent.contract``. That is not a
boundary break -- every sibling audit already grants a package its own submodules
in as many words ("a package importing its own submodules is not a boundary
break").
"""

from __future__ import annotations

from hfss_agent.contract import (
    CONTRACT_VERSION,
    Applicability,
    DesignSnapshot,
    FindingClassification,
    FindingOutcome,
    FindingProvenance,
    FindingSource,
)

# Every gate is a ``Finding`` from the gate source; the alternative member,
# ``engine_rule``, belongs to E-2 and is unreachable from this package. Annotated
# with the Literal rather than left a bare ``str`` so a typo is a contract
# violation at the annotation, not only at pydantic validation.
GATE_SOURCE: FindingSource = "gate"

# THE SEVERITY EVERY GATE EMITS, CONSTANT ACROSS ALL FOUR GATES AND ALL FIVE
# OUTCOMES. Degenerate ON PURPOSE, and the record of that is here because a
# deliberate constant is indistinguishable from an accidental one otherwise.
#
# WHY CONSTANT. ``Finding`` already declares two judgment axes and
# ``finding.py`` describes ``classification`` as "the coarse severity
# classification" in as many words -- so the severity axis exists and is spelled
# ``classification``. A second, free-string severity varying alongside it would be
# two homes for one fact. Both existing fixtures
# (``tests/schemas/conftest.py``, ``tests/metrics/assembly_helpers.py``) use
# ``"info"`` and it is the only ``Finding.severity`` value anywhere in the repo,
# so this follows them rather than inventing a vocabulary.
#
# ``ComponentCheck.severity`` IS A DIFFERENT FIELD ON A DIFFERENT TYPE, with a
# closed ``Literal["required", "advisory"]`` and eight producers in
# ``preflight/assembler.py``. Copying that vocabulary into a ``Finding`` would be
# silently wrong, and the shared field name is the whole reason to say so here.
#
# THE CONSEQUENCE, RECORDED RATHER THAN LEFT TO BE REDISCOVERED: a required field
# that no producer ever varies is the shape ADR-30 dec. 3-4 condemned on
# ``ProvenanceRecord.engine_version``/``rule_version`` -- "the slot then advertises
# a capability that does not exist". W-9 is ``Finding.severity``'s first producer
# and holds it constant, which makes the field a REMOVAL CANDIDATE at the next
# contract amendment on that identical argument. Not proposed here: removing it is
# a semver event and out of this step's scope. The evidence for it is created by
# this line.
GATE_SEVERITY = "info"

# THE FIVE-TO-THREE MAP, which the contract deliberately left open: ``outcome``
# has five members, ``classification`` has three, and ``finding.py`` says only that
# the two "are different axes and must not collapse into one".
#
#   * ``fail`` -> ``error``. The one state that asserts something IS wrong.
#   * ``warning`` and ``insufficient_evidence`` -> ``warning``. These are exactly
#     the members of ``GATE_OUTCOMES_THAT_QUALIFY_COMPUTATION``, so this axis
#     becomes a readable proxy for "this result travels with a caveat" -- which is
#     what a renderer, and W-10's merge, actually need.
#   * ``pass`` and ``not_evaluated`` -> ``judgment_call``. The two states that
#     assert nothing about the design: a pass has nothing to report, and a
#     not-evaluated looked at nothing.
#
# THE IMPERFECTION, STATED RATHER THAN HIDDEN: ``not_evaluated`` refuses metrics
# while sharing a classification with ``pass``, which permits them. That is
# ACCEPTED, and accepted precisely BECAUSE ``classification`` is not the routing
# axis -- W-7 routes on ``outcome`` alone. Making this mirror the routing would
# collapse the two axes ``finding.py`` says must not collapse.
CLASSIFICATION_BY_OUTCOME: dict[FindingOutcome, FindingClassification] = {
    "pass": "judgment_call",
    "fail": "error",
    "warning": "warning",
    "not_evaluated": "judgment_call",
    "insufficient_evidence": "warning",
}


def applicability(conditions: dict[str, object]) -> Applicability:
    """The applicability block, with ``held`` DERIVED from the conditions.

    THE ``held`` RULE, STATED ONCE AND STATED HERE, because this is the point at
    which ``held`` is computed and the only place a reader can check it against
    what it is computed from.

    ``held`` answers "did the machine-checked applicability conditions for APPLYING
    THIS RULE hold". It does NOT answer "did the design pass". Those are different
    questions, and reading the first as the second is the misread this exists to
    prevent -- which is why ``Finding`` carries a separate five-state ``outcome``.

    TWO COMBINATIONS FOLLOW THAT LOOK WRONG AT A GLANCE AND ARE NOT. Both are
    reachable today, so neither is hypothetical:

      * ``held=False`` WITH ``outcome="fail"`` -- the solution-existence gate on
        ``no_solution``. The conditions for applying the rule were absent (there
        was no solve state to read), AND that very absence is a negative
        observation about the thing the gate asks. Both are true at once.
      * ``held=True`` WITH ``outcome="warning"`` -- the convergence gate on
        ``stopped``. The rule applied cleanly and returned a hedge. A hedge is a
        result, not a failure to apply.

    SO ``held`` IS NOT A PROXY FOR "A DETERMINATION WAS REACHED", and nothing
    downstream may use it as one. ``outcome`` is the only field carrying the
    verdict, and it carries all five states precisely so this one does not have to.

    DERIVED, NEVER PASSED IN. Computing it here rather than accepting it as a
    parameter is what makes the value checkable against the conditions beside it,
    and it is why no gate can set the two into disagreement. A gate supplies
    observations; it does not get to assert the conclusion drawn from them.

    THE EMPTY-DICT HAZARD, recorded rather than guarded: ``all({}.values())`` is
    ``True``, so an empty ``conditions`` would yield ``held=True`` with nothing
    named -- a claim that conditions held when none were stated. Every gate names
    at least one, and the gate tests assert non-emptiness on the OUTPUT rather than
    this function raising: a raise would be a behaviour change for a state no
    producer reaches, and pinning that the hazard EXISTS would be the inverted
    guard ADR-30 dec. 12 names -- a test that fails only when the product improves.
    """
    return Applicability(conditions=conditions, held=all(conditions.values()))


def finding_id(gate_name: str, outcome: FindingOutcome) -> str:
    """The identifier for one gate result, DERIVED FROM CONTENT.

    Content-derived rather than minted, and the choice is load-bearing beyond
    tidiness: a ``uuid4()`` would need ``import uuid``, which Part 5's import audit
    would then have to admit -- and admitting it re-opens the non-determinism hole
    that audit exists to close. W-8 mints a uuid for ``snapshot_id`` because a
    snapshot identifies a CAPTURE EVENT (something that happened at a time); a gate
    finding is a pure function of a snapshot and has no event to identify, which is
    the same reasoning ADR-30 dec. 2 uses to refuse ``evaluated_at``.

    UNIQUE WITHIN ONE EVALUATION, NOT GLOBALLY, and the limitation is written here
    rather than only in an ADR because this is where someone would rely on it. The
    four gate names are distinct, so one ``evaluate_gates`` call yields four
    distinct ids; but ``gate-freshness-insufficient_evidence`` is the SAME STRING
    for every design on earth. Nothing asserts global uniqueness today and no
    consumer needs it.

    THE UPGRADE PATH, if W-10's merge ever does need it: ``f"{snapshot.snapshot_id}
    -gate-{name}"``. Still deterministic GIVEN a snapshot, still no new import, and
    ``snapshot_id`` is already on the provenance beside it. Deliberately not done
    now -- it buys nothing today and would make the id vary between two captures of
    an unchanged design, which is a cost with no matching benefit.
    """
    return f"gate-{gate_name}-{outcome}"


def gate_provenance(snapshot: DesignSnapshot) -> FindingProvenance:
    """Stamp one judgment's provenance from the snapshot it judged.

    EVERY FIELD IS SOURCED UNDER BOTH ARMS OF ``solve_state`` (ADR-30 dec. 1) --
    the property ``FindingProvenance`` was shaped to have, and the reason a gate can
    report on a design that was never solved, which ADR-28 calls the ordinary case
    rather than an edge one. Nothing below reads ``solve_state`` or ``solved_data``
    at all, which is what makes that claim checkable rather than aspirational.

    ``engine_version`` IS NEVER SET, and that is a statement rather than an
    omission. It is the type's one optional, and the rule permitting it (written at
    the field itself) turns on a gate having no engine behind it while an engine
    rule knows its own version. A gate is the first case: there is no engine and
    there never will be, by construction. Leaving the field at its default is the
    honest form of that.

    Args:
        snapshot: the artifact being judged. Read for IDENTITY only.

    Returns:
        A complete ``FindingProvenance``; ``engine_version`` stays ``None``.
    """
    selection = snapshot.selection
    return FindingProvenance(
        # The six selection fields are required on every snapshot and identical
        # under both arms. ``Selection.project`` is the bare NAME, not a path
        # (ADR-28), so there is no filesystem string here to travel out with a
        # finding -- and no operator account name inside one.
        project=selection.project,
        design=selection.design,
        solution_type=selection.solution_type,
        setup=selection.setup,
        sweep=selection.sweep,
        variation=selection.variation,
        # WHICH CAPTURE THIS JUDGMENT RESTED ON. A ``Finding`` is rendered without
        # the snapshot beside it, so this is the only route back to the artifact.
        snapshot_id=snapshot.snapshot_id,
        # THE CONSTANT, NOT ``snapshot.contract_version``, and the two are not
        # interchangeable even though W-8 stamps the same value into both today.
        # This field states the schema THIS RECORD conforms to, and the record is
        # built here, now, by this code -- so the running package's version is the
        # only honest answer. ``snapshot.contract_version`` states what the SNAPSHOT
        # claims, which is a fact about a different artifact and would be the wrong
        # one to copy if the two ever differed. W-5 and W-6 both make this call the
        # same way (``inspect/assembler.py:378``, ``validate_native/assembler.py:422``).
        contract_version=CONTRACT_VERSION,
        # From the snapshot's environment block, matching both siblings' spelling
        # (``wrapper_version=environment.wrapper_version``). NOT read from importlib
        # metadata: ``gating`` reaches nothing, and the snapshot already carries the
        # version its capture was made under.
        wrapper_version=snapshot.environment.wrapper_version,
    )
