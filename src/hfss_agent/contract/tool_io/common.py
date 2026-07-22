"""Shared tool_io primitives (System Design §3, API / tool contracts).

The §2 enumerations live in ``contract.common``; these are the §3 ones — the
selection stages, inspection-section names, export format, and engine-presence
status used across the tool I/O schemas — plus the two cross-cutting result
shapes more than one tool group returns: the typed ``cannot_evaluate`` outcome
and the ``ExportResult`` union.

Nothing here imports anything I/O-capable; ``contract.tool_io`` inherits the
contract subpackage's import-purity constraint (ADR-3).
"""

from typing import Annotated, Literal

from pydantic import Field

from hfss_agent.contract.common import StrictModel

# --- §3 enumerations ---------------------------------------------------------

# list_selection_options / select stage. Process is *attached* (attach()), not
# "selected", so the selectable stages are project→…→variation (§3, W-2).
SelectionStage = Literal["project", "design", "setup", "sweep", "variation"]

# inspect_design section names — exactly the eight sections of
# DesignSnapshot.Inspection (§2), so a requested subset can name only real
# sections (Literal-validated dict keys in InspectionResult).
InspectionSectionName = Literal[
    "variables",
    "objects",
    "materials",
    "boundaries",
    "excitations_ports",
    "setups",
    "sweeps",
    "available_results",
]

# export_results format (§3).
ExportFormat = Literal["touchstone", "csv"]

# validate_setup engine-presence notice (§3 graceful degradation).
EngineStatus = Literal["present", "absent"]


class CannotEvaluate(StrictModel):
    """The typed "cannot evaluate via PyAEDT" outcome (§3; spec Point 6; ADR-7).

    Threaded as a union arm on exactly the tools that reach PyAEDT through the
    adapter — never improvised, never a hang. It names the limitation the way
    ``InspectionSection.limitation`` does: where PyAEDT cannot read or evaluate
    something, we say so.

    Deliberate deviation (logged as an ADR + a §3 edit at this step's end): §3's
    prose says *every* tool can return ``cannot_evaluate``; we narrow it to the
    adapter-backed tools only. The broker-owned record tools (design intent,
    audit log) never reach PyAEDT, so a failure there is a typed *file* error,
    not a ``cannot_evaluate`` — giving them the arm would misattribute the
    failure, not add safety.

    ``outcome`` is the shared discriminator across every tool_io result union,
    so this one class slots into each of them as the same tagged member.
    """

    outcome: Literal["cannot_evaluate"] = "cannot_evaluate"
    reason: str
    limitation: str
    template_text: str


class ExportWritten(StrictModel):
    """export_* success arm: the file was written (§6.5, ADR-8)."""

    outcome: Literal["written"] = "written"
    path: str
    bytes_written: int
    template_text: str


class ExportRefused(StrictModel):
    """export_* refusal arm: the write was refused UP FRONT, before anything on
    disk was touched (§6.5, ADR-8 — no silent overwrite).

    A distinct typed outcome, not an exception and not a silently-true success
    flag: refusal is a normal, representable result the caller inspects. The
    three values name the caller's REMEDY, so the caller can act on the tag
    alone; the specific kind (which path rule, which network form) stays in the
    prose ``reason``:

      * ``refused_existing_path`` — the path exists and ``overwrite`` was not
        set: retry with ``overwrite=true``;
      * ``refused_invalid_path`` — the path string itself is unacceptable: fix
        the path;
      * ``refused_network_path`` — the path leaves this machine, which the
        zero-egress policy forbids: choose a local path.

    ``outcome`` has no default: a refusal must say which remedy applies, and a
    defaulted discriminator would let a new refusal site silently inherit
    "existing path" and mislead the caller into retrying with ``overwrite``.
    """

    outcome: Literal[
        "refused_existing_path", "refused_invalid_path", "refused_network_path"
    ]
    path: str
    reason: str
    template_text: str


class ExportFailed(StrictModel):
    """export_* failure arm: a write that BROKE MID-OPERATION — distinct from
    ``ExportRefused``, which declines before touching the disk. Disk full, a
    permission loss between open and write, a device error: the operation was
    attempted and did not complete.

    ``orphaned_temp`` carries the temp file a temp-then-replace write left
    behind when it failed after the temp already existed (``None`` when no temp
    was created, or when the failure happened before it was). No deletion path
    exists in this codebase, so naming it here is what keeps a file left behind
    on the user's disk from being silent.
    """

    outcome: Literal["write_failed"]
    path: str
    reason: str
    orphaned_temp: str | None = None
    template_text: str


# export_results / export_diagnostics_bundle share one result type covering
# every outcome: written, refused up front (three remedies), failed mid-write,
# and cannot_evaluate (the adapter read that feeds the export failed).
# Discriminated on ``outcome`` so exactly one arm is ever inhabited.
ExportResult = Annotated[
    ExportWritten | ExportRefused | ExportFailed | CannotEvaluate,
    Field(discriminator="outcome"),
]
