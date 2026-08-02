"""Shared contract primitives.

Holds the ``Variation`` key and the enumerated value sets that System Design
§2 fixes verbatim for several schema fields, so every schema that references
them agrees on the exact spelling. Nothing here imports anything I/O-capable —
the contract purity test (ADR-3) depends on that staying true.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

# HFSS-sourced strings (project/design/material names, notes, solver messages)
# are attacker-writable and therefore untrusted data (System Design §6.6). This
# alias carries no behaviour of its own — length-capping and control-character
# stripping happen at the adapter on read — but it marks, at the schema level,
# which fields hold untrusted text so downstream code never treats it as
# trusted, routes it into an instruction position, or lets it steer control
# flow.
UntrustedStr = str

# The contract SCHEMA version — the ``snapshot-...`` space stamped into every
# record's ``contract_version`` field (ADR-21 dec. 10). This is deliberately
# SEPARATE from the package version (pyproject's, surfaced as
# ``wrapper_version``): ADR-21 dec. 10 keeps the two spaces independent, so the
# schema shape and the package release can move without forcing each other.
# Every site imports this one constant; the pin test in the schema suite is what
# makes an accidental edit to its value loud.
#
# ``2.0.0`` because ADR-23 resolves the increment scheme ADR-21 dec. 10 and
# ADR-22 dec. 2 deferred: this space is PLAIN SEMVER OVER THE SCHEMA SURFACE.
# The ADR-23 amendment removed a ``Literal`` member and added a required field
# to a schema under ``extra="forbid"``; both are breaking for a producer or an
# exhaustive consumer, regardless of how few of either exist today. The two
# version spaces move INDEPENDENTLY and are never synchronised — seeing
# ``snapshot-2.0.0`` beside package version ``0.3.0`` is correct, not drift, and
# "fixing" either to match the other would destroy the ability to say which
# schema surface produced a given record.
#
# The 0.2.0 -> 0.3.0 bump at Step 2.4a is itself the worked example: that
# amendment retyped ``PreflightReport.environment`` and added a required field
# to ``ComponentCheck``, both breaking for a producer, so the PACKAGE version
# moved. ``CONTRACT_VERSION`` did not, and the rule for why is worth stating
# once here rather than re-derived per amendment: it moves if and only if the
# change touches a type reachable from ``DesignSnapshot`` or ``Finding`` — the
# two artifacts crossing ``evaluate()`` — or a type carrying a
# ``contract_version`` field of its own (today ``DesignSnapshot``,
# ``ProvenanceRecord``, ``InspectionProvenance``, ``NativeValidationProvenance``).
# The first clause protects the engine from a surface it cannot see changing
# under it; the second protects a stamped record from claiming a schema version
# whose shape it no longer has. 2.4a's new types satisfy neither clause.
CONTRACT_VERSION = "snapshot-2.0.0"

# --- Enumerated value sets fixed verbatim by System Design §2 ----------------

# InspectionSection.read_status (§2 inspection bullet)
ReadStatus = Literal["ok", "not_readable"]

# SolveState.convergence_status (§2 solve_state: "converged/stopped status")
ConvergenceStatus = Literal["converged", "stopped"]

# Finding.source (§2 Finding — Identity). TWO members, where §2 still lists
# three: ``hfss_native`` was REMOVED by the ADR-23 amendment, and §2 is being
# edited to match. A native HFSS message is not a Finding and cannot be made
# into one — we own no rule id, rule version, calculation, or machine-checked
# applicability behind it, so most of Finding's required fields would have to
# be faked to carry one. Native validation travels as its own structural block
# (``tool_io.NativeValidationBlock``) instead. Removing the member is what
# makes that separation true at the TYPE level rather than a label that can be
# wrong: with it gone, a finding returned across the wrapper→engine seam cannot
# claim native origin at all, so W-10's seven-field receipt gate stays
# unconditional — there is no source for which it could be relaxed, and no call
# site to miss.
FindingSource = Literal["gate", "engine_rule"]

# Finding.outcome — the five states (§2 Finding — Judgment)
FindingOutcome = Literal[
    "pass", "fail", "warning", "not_evaluated", "insufficient_evidence"
]

# Finding.classification — field 6, mapped onto the five states (§2 Finding)
FindingClassification = Literal["error", "warning", "judgment_call"]

# IntentObject.threshold_type (§2 IntentObject)
ThresholdType = Literal["s11", "vswr"]

# AuditRecord.risk_tier — the three tiers locked in §6.1 (safe is the whole MVP
# surface; medium/high exist for Tier 2.3 but are unreachable today).
RiskTier = Literal["safe", "medium", "high"]

# AuditRecord.outcome (§2 AuditRecord). The first four are §2 verbatim and are
# never renamed; ``unknown_capability`` is the gap-9 amendment addition — the
# broker can now audit a dispatch of a name the registry does not hold, which
# previously could not be represented at all (a record with no honest tier to
# state). It is the ONLY outcome permitted to carry ``risk_tier=None``, and it
# must: see AuditRecord's both-or-neither validator.
AuditOutcome = Literal[
    "ok",
    "typed_error",
    "cannot_evaluate",
    "refused_by_gate",
    "unknown_capability",
]


class StrictModel(BaseModel):
    """Base for every contract schema.

    ``extra="forbid"`` makes each schema the exact, auditable statement of its
    fields (W-8): an unexpected key is a contract violation surfaced loudly,
    not silently absorbed. This is validation policy only — the contract
    subpackage carries no behaviour beyond validation (W-12).
    """

    model_config = ConfigDict(extra="forbid")


class Variation(StrictModel):
    """A first-class key carried everywhere (§2).

    A variation is a canonical variable-name -> value map plus a stable hash of
    that map. The hash is supplied by the producer (the snapshot module); the
    contract only carries it — computing it would be behaviour beyond
    validation, which W-12 forbids here.
    """

    values: dict[str, str]
    variation_hash: str
