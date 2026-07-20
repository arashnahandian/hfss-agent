"""The medium/high-tier unreachability proof (§6.1; ADR-5; plan §5).

What this proves: every capability in the production registry is safe-tier,
so NO input to any shipped tool can reach the confirmation path; and the
floors below that proof fail closed independently — the Tier 1 default
confirmer refuses everything (deny-by-default, asserted here), and a
misregistered HIGH tier is refused unconditionally at dispatch BEFORE the
confirmer is even consulted (Part 2's pipeline, proven in
``tests/broker/test_confirmation.py`` with synthetic capabilities).

The tier check ITERATES THE REGISTRY, never a hardcoded name list, so tools
registered later (Step 2.8) are covered the moment their factory joins the
production list below. Until 2.8 provides a single composition root, the
factory list here IS the production surface; when that root exists, this test
should build the registry through it instead so the two can never diverge.
"""

from __future__ import annotations

from pathlib import Path

from hfss_agent.adapter.fake import FakeAdapter
from hfss_agent.broker import (
    CapabilityRegistry,
    ConfirmationRequest,
    IntentStore,
    RefuseAllConfirmer,
    audit_capabilities,
    intent_capabilities,
    session_routed_specs,
)
from hfss_agent.session import Session


def _production_registry(tmp_path: Path) -> CapabilityRegistry:
    """The full production capability surface, composed the way Step 2.8
    will. Registration touches no file — the paths are only closed over — so
    building this in a test is side-effect-free."""
    session = Session(FakeAdapter())
    store = IntentStore(str(tmp_path / "intent.json"))
    log_path = str(tmp_path / "audit-log.jsonl")
    return CapabilityRegistry(
        session_routed_specs(session)
        + intent_capabilities(store, session)
        + audit_capabilities(log_path)
    )


def test_every_production_capability_is_safe_tier(tmp_path: Path) -> None:
    registry = _production_registry(tmp_path)
    assert registry.specs, "an empty registry would make this proof vacuous"
    non_safe = [
        (spec.name, spec.tier) for spec in registry.specs if spec.tier != "safe"
    ]
    assert not non_safe, (
        f"non-safe capabilities in the shipped surface: {non_safe} — the MVP "
        "surface is 100% safe-tier (§6.1); a medium/high tool is Tier 2.3 "
        "work behind the confirmation flow and (for high) the ADR-6 snapshot "
        "provider"
    )


def test_the_tier_one_default_confirmer_refuses_everything() -> None:
    # The confirmer is constructor-required on the Broker; the designated
    # Tier 1 composition default is RefuseAllConfirmer. Deny-by-default means
    # that even a misregistered medium tier cannot obtain approval.
    request = ConfirmationRequest(
        capability="anything",
        tier="medium",
        description="anything",
        sanitized_arguments={},
    )
    assert RefuseAllConfirmer().confirm(request) is False


def test_production_surface_has_not_silently_shrunk(tmp_path: Path) -> None:
    # A positive floor, not an enumeration: the tier proof above iterates the
    # registry, and THIS check only guards it against vacuous shrinkage — the
    # eight Parts 2-4 capabilities must be present (a SUBSET assertion, so
    # 2.8 additions extend the surface without touching this test).
    names = {spec.name for spec in _production_registry(tmp_path).specs}
    assert {
        "attach",
        "list_selection_options",
        "select",
        "get_session_status",
        "set_design_intent",
        "get_design_intent",
        "clear_design_intent",
        "get_audit_log",
    } <= names
