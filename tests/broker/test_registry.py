"""ADR-5 registration enforcement: no declared tier, no registration —
structurally, at construction time (the adapter-ABC precedent), never at first
call."""

from __future__ import annotations

import dataclasses

import pytest

from hfss_agent.broker import CapabilityRegistry, CapabilitySpec


def _handler(**kwargs: object) -> object:
    return kwargs


def _spec(name: str = "x", tier: str = "safe") -> CapabilitySpec:
    return CapabilitySpec(
        name=name,
        tier=tier,  # type: ignore[arg-type] — tests pass invalid tiers on purpose
        handler=_handler,
        description="test capability",
    )


def test_spec_without_tier_is_a_construction_typeerror() -> None:
    # The load-bearing ADR-5 claim: omitting the tier fails from the dataclass
    # itself, before any registration or call — no sentinel, no default.
    with pytest.raises(TypeError):
        CapabilitySpec(  # type: ignore[call-arg]
            name="x", handler=_handler, description="test capability"
        )


def test_no_spec_field_carries_a_default() -> None:
    # Structural proof the TypeError above can never rot: EVERY field is
    # required, so none can be silently omitted.
    for field in dataclasses.fields(CapabilitySpec):
        assert field.default is dataclasses.MISSING, field.name
        assert field.default_factory is dataclasses.MISSING, field.name


def test_bogus_tier_is_rejected_at_registry_construction() -> None:
    with pytest.raises(ValueError, match="safeish"):
        CapabilityRegistry((_spec(tier="safeish"),))


def test_tier_validation_is_exact_not_case_insensitive() -> None:
    # "Safe" is not a tier; the RiskTier literal is lowercase and exact.
    with pytest.raises(ValueError, match="Safe"):
        CapabilityRegistry((_spec(tier="Safe"),))


def test_duplicate_capability_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        CapabilityRegistry((_spec(name="x"), _spec(name="x")))


def test_lookup_returns_the_spec_and_none_for_unknown() -> None:
    spec = _spec(name="x")
    registry = CapabilityRegistry((spec,))
    assert registry.get("x") is spec
    assert registry.get("unregistered") is None
    assert registry.specs == (spec,)


def test_all_three_tiers_are_valid_registry_values() -> None:
    # The taxonomy ships complete (plan revision 1): medium and high REGISTER
    # fine and carry into the audit log — only dispatch refuses them. The
    # tier-surface proof that the production registry is 100% safe-tier lives
    # in tests/prohibited_ops/ (Part 5).
    specs = tuple(_spec(name=tier, tier=tier) for tier in ("safe", "medium", "high"))
    registry = CapabilityRegistry(specs)
    assert [spec.tier for spec in registry.specs] == ["safe", "medium", "high"]


def test_empty_registry_is_valid() -> None:
    # Composition may legitimately start empty (tests do); emptiness is not an
    # error — completeness against the tool surface is Step 2.8's test.
    assert CapabilityRegistry(()).specs == ()
