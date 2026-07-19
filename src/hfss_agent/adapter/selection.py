"""Selection-chain downstream-reset semantics, shared by both adapters (W-3).

Selecting a stage invalidates every stage below it (process -> project ->
design -> setup -> sweep -> variation). Both ``FakeAdapter`` and ``RealAdapter``
clear those downstream entries on ``_select`` so neither ever holds an
incoherent partial chain — e.g. a design still bound under a project that was
just re-selected, which is exactly the stale-scope hazard ``RealAdapter._scope``
now refuses to bind.

This is defensive hygiene local to the adapter's *own* cached selection, NOT a
selection state machine: order enforcement and re-selection remain the session
module's job (W-2). Keeping the reset in one place is what keeps the fake a
faithful double of the real adapter's post-select chain shape.

``solution_type`` is read from HFSS at the design stage and travels with the
design, so it clears together with the design and is not a stage of its own.
"""

from __future__ import annotations

from hfss_agent.contract.tool_io import SelectionStage

# Boundary (do not re-derive): this module is cache hygiene ONLY — clearing the
# fields below a stage. Stage-order enforcement, prerequisite validation, and
# invalidation-on-change belong to the session module (W-2). The adapter
# deliberately permits out-of-order selection because ordering is not its job.

# Fields cleared to None when a given stage is (re)selected — everything below
# it in the chain. Selecting a stage never clears itself or an upstream stage.
_DOWNSTREAM_OF: dict[SelectionStage, tuple[str, ...]] = {
    "project": ("design", "solution_type", "setup", "sweep", "variation"),
    "design": ("setup", "sweep", "variation"),
    "setup": ("sweep", "variation"),
    "sweep": ("variation",),
    "variation": (),
}


def downstream_reset(stage: SelectionStage) -> dict[str, None]:
    """The ``field -> None`` update that clears every stage below ``stage``.

    Merge it into the ``model_copy(update=...)`` that sets ``stage`` so the
    resulting chain carries no stale entry beneath the stage just chosen.
    """
    return {field: None for field in _DOWNSTREAM_OF[stage]}
