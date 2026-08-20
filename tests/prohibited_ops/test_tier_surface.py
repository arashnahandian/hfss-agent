"""The medium/high-tier unreachability proof (§6.1; ADR-5; plan §5).

What this proves: every capability in the production registry is safe-tier,
so NO input to any shipped tool can reach the confirmation path; and the
floors below that proof fail closed independently — the Tier 1 default
confirmer refuses everything (deny-by-default, asserted here), and a
misregistered HIGH tier is refused unconditionally at dispatch BEFORE the
confirmer is even consulted (Part 2's pipeline, proven in
``tests/broker/test_confirmation.py`` with synthetic capabilities).

The tier check ITERATES THE REGISTRY, never a hardcoded name list, so tools
registered later are covered the moment their factory joins the production
surface.

LIFTED AT STEP 2.8, AS THIS DOCSTRING INSTRUCTED. It used to say: "Until 2.8
provides a single composition root, the factory list here IS the production
surface; when that root exists, this test should build the registry through it
instead so the two can never diverge." That root now exists
(``hfss_agent.server.build_composition``) and this file builds through it. The
local factory list is gone -- deliberately, not merely unused: a second way to
compose the surface is exactly the divergence the instruction was written to
prevent, and leaving it here as a convenience would recreate it.

The lift was verified to be behaviour-preserving before it was made: the old
factory list and ``build_composition`` produced the same ten (name, tier) pairs
in the same order, so no assertion below changed meaning.

WHAT THIS PROOF DOES NOT COVER, and where the rest of it lives. The registry
holds CAPABILITIES, which is not the same set as the tools a client is offered:
``preflight_environment`` reaches no capability at all, and ``inspect_design``
and ``export_diagnostics_bundle`` are assemblers whose registry entries are the
things they dispatch. ``test_mcp_tier_surface.py`` iterates the exposed tool
surface and closes that gap.
"""

from __future__ import annotations

from pathlib import Path

from hfss_agent.adapter.fake import FakeAdapter
from hfss_agent.broker import (
    CapabilityRegistry,
    ConfirmationRequest,
    RefuseAllConfirmer,
)
from hfss_agent.server import build_composition


def _production_registry(tmp_path: Path) -> CapabilityRegistry:
    """The production capability surface, built through the composition root.

    ``build_composition`` is what ``__main__`` calls, so this proof and the
    shipped server cannot describe different surfaces. The adapter is the fake
    because the registry's SHAPE does not depend on which backend is behind it
    -- registration closes over bound methods without calling any of them -- and
    a live adapter would make this test require the ``live`` extra for nothing.
    """
    return build_composition(FakeAdapter(), data_dir=str(tmp_path)).registry


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
