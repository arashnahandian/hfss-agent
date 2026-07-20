"""Capability registry (W-4): the action allowlist with mandatory risk tiers.

ADR-5 locks in that "every future tool must declare a tier at registration or
it does not register." Enforcement here is STRUCTURAL, at construction time —
the adapter-ABC precedent (ADR-17 decision 2), not the decorator-plus-
reflection pattern (ADR-18 decision 8): ``tier`` is a required field with no
default on a frozen dataclass, so omitting it is a ``TypeError`` from the
dataclass itself, before any registration or call; and the registry validates
every declared tier against the contract's ``RiskTier`` literal set when it is
constructed, so an invalid registry never exists to dispatch against. There is
no code path that produces a registered capability without a declared tier,
because the registration API cannot express one.

What stays CI-enforced (the weaker claim, stated honestly per ADR-18
decision 8): that every tool the server exposes is registered here at all.
Registry completeness against the documented tool surface is Step 2.8's test;
this module guarantees only that whatever IS registered carries a valid tier.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import get_args

from hfss_agent.contract import RiskTier

# Valid tier values derived from the contract literal (§6.1: safe / medium /
# high), so this module can never drift from the pinned taxonomy.
_VALID_TIERS = frozenset(get_args(RiskTier))


@dataclass(frozen=True)
class CapabilitySpec:
    """One registered capability: name, risk tier, handler, description.

    Every field is required — no defaults, no sentinels — so a spec missing
    its tier (or any field) fails at construction with a ``TypeError``, not at
    first dispatch. ``description`` is the human-readable action wording a
    ``ConfirmationRequest`` carries for the medium/high confirmation flow.
    """

    name: str
    tier: RiskTier
    handler: Callable[..., object]
    description: str


class CapabilityRegistry:
    """The action allowlist: an immutable name -> ``CapabilitySpec`` mapping.

    Constructed ONCE from a tuple of specs at composition time — no mutable
    global, no post-construction registration. All three tiers are valid
    registry values (the taxonomy ships complete); what a tier may DO at
    dispatch time is the broker's concern, not the registry's.
    """

    def __init__(self, specs: tuple[CapabilitySpec, ...]) -> None:
        by_name: dict[str, CapabilitySpec] = {}
        for spec in specs:
            if spec.tier not in _VALID_TIERS:
                raise ValueError(
                    f"capability {spec.name!r} declares invalid tier "
                    f"{spec.tier!r}; valid tiers: {sorted(_VALID_TIERS)}"
                )
            if spec.name in by_name:
                raise ValueError(f"duplicate capability name: {spec.name!r}")
            by_name[spec.name] = spec
        self._by_name = by_name
        self._specs = tuple(specs)

    @property
    def specs(self) -> tuple[CapabilitySpec, ...]:
        """Every registered spec, in registration order. The Part 5
        tier-surface proof iterates this to show the shipped surface is 100%
        safe-tier."""
        return self._specs

    def get(self, name: str) -> CapabilitySpec | None:
        """The spec registered under ``name``, or None — the dispatcher maps
        None to its typed unknown-capability failure rather than raising."""
        return self._by_name.get(name)
