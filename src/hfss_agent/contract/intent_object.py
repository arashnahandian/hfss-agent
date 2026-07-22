"""IntentObject — the minimal, optional design intent (§2, spec Point 24)."""

from pydantic import Field

from hfss_agent.contract.common import StrictModel, ThresholdType


class IntentObject(StrictModel):
    """Target frequency plus one S11-or-VSWR threshold (§2 IntentObject).

    Deliberately minimal: richer intent is Tier 2. Persisted as a plain JSON
    file written atomically via the broker — the write itself is the broker's
    concern, not this schema's.
    """

    # The unit lives in the FIELD NAME, not only in a description: a caller
    # reading the schema, a rendered template, or an on-disk intent file all
    # see "hz" without having to find prose that states the assumption.
    target_frequency_hz: float = Field(description="Target frequency in Hz.")
    threshold_type: ThresholdType
    threshold_value: float
