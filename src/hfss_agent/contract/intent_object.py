"""IntentObject — the minimal, optional design intent (§2, spec Point 24)."""

from hfss_agent.contract.common import StrictModel, ThresholdType


class IntentObject(StrictModel):
    """Target frequency plus one S11-or-VSWR threshold (§2 IntentObject).

    Deliberately minimal: richer intent is Tier 2. Persisted as a plain JSON
    file written atomically via the broker — the write itself is the broker's
    concern, not this schema's.
    """

    target_frequency: float
    threshold_type: ThresholdType
    threshold_value: float
