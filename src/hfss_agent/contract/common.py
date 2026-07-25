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
CONTRACT_VERSION = "snapshot-1.0.0"

# --- Enumerated value sets fixed verbatim by System Design §2 ----------------

# InspectionSection.read_status (§2 inspection bullet)
ReadStatus = Literal["ok", "not_readable"]

# SolveState.convergence_status (§2 solve_state: "converged/stopped status")
ConvergenceStatus = Literal["converged", "stopped"]

# Finding.source (§2 Finding — Identity)
FindingSource = Literal["hfss_native", "gate", "engine_rule"]

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
