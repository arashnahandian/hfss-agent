"""The medium/high-tier unreachability proof for the MCP SURFACE (§6.1; ADR-33).

WHY A SECOND TIER PROOF EXISTS, AND WHAT THE FIRST ONE STRUCTURALLY CANNOT SEE.
``test_tier_surface.py`` iterates the ``CapabilityRegistry``. That proves every
CAPABILITY is safe tier, and it is the stronger of the two proofs because a
capability's tier is enforced structurally -- a ``CapabilitySpec`` without one is
a ``TypeError`` before registration.

But the registry is not the tool surface. Three registered tools do not appear in
it as themselves:

  * ``preflight_environment`` -- dispatches NOTHING. It reads injected probes
    and the broker's non-dispatchable ``require_environment`` accessor.
  * ``inspect_design`` -- the W-5 assembler, deliberately NOT a capability. The
    registry entry of that name is ``Session.inspect``, a different and
    differently-shaped thing.
  * ``export_diagnostics_bundle`` -- the W-11 assembler; the registry holds only
    the ``get_audit_log`` it dispatches.

So iterating the registry and concluding "the tool surface is safe" would be an
inference across a gap. This file closes it by iterating the tools a client is
actually offered.

THE HONEST WEAKNESS OF THIS PROOF, STATED PLAINLY. An MCP tool carries NO tier at
registration -- ``MCPServer.tool()`` has no such parameter and the protocol has
no such field. A tool's tier is declared in ``TOOL_SURFACE`` and nowhere else.
So for a tool that maps to a capability, "safe" is CORROBORATED by an
independent declaration (``tests/server/test_completeness.py`` compares them);
for ``preflight_environment``, which corroborates against nothing, "safe" rests
on that table alone. That is a real limit, not a formality, and the completeness
suite pins the number of tools in that position at exactly one so it cannot grow
unnoticed.

SELF-CONTAINED ON PURPOSE. The prohibited-operations suite is the one that must
stay green under every pressure, so it builds its own objects rather than
importing a helper from another test package whose shape could change.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from hfss_agent.adapter.fake import FakeAdapter
from hfss_agent.contract import RiskTier
from hfss_agent.server import FAKE, build_composition
from hfss_agent.server.app import build_app
from hfss_agent.server.tool_surface import TOOL_SURFACE

# The tiers that require a confirmation flow. Named here rather than written as
# ``!= "safe"`` so the assertion says what it is refusing.
_TIERS_REQUIRING_CONFIRMATION: tuple[RiskTier, ...] = ("medium", "high")


def _exposed_tool_names(tmp_path: Path) -> set[str]:
    """The tools a client is offered, read off a production-composed server."""
    composition = build_composition(FakeAdapter(), data_dir=str(tmp_path))
    app = build_app(composition, adapter_kind=FAKE)
    return {tool.name for tool in asyncio.run(app.list_tools())}


def _rows_by_name() -> dict[str, object]:
    return {binding.name: binding for binding in TOOL_SURFACE}


def test_every_exposed_tool_is_safe_tier(tmp_path: Path) -> None:
    """THE PROOF. Iterates the EXPOSED SURFACE, never a hardcoded name list, so
    a tool registered later is covered the moment it appears."""
    exposed = _exposed_tool_names(tmp_path)
    assert exposed, "an empty tool surface would make this proof vacuous"
    rows = _rows_by_name()
    non_safe = []
    for name in sorted(exposed):
        binding = rows.get(name)
        assert binding is not None, (
            f"tool {name!r} is exposed with no TOOL_SURFACE row, so it declares "
            "no tier at all -- which ADR-5 refuses outright."
        )
        if binding.tier != "safe":  # type: ignore[attr-defined]
            non_safe.append((name, binding.tier))  # type: ignore[attr-defined]
    assert not non_safe, (
        f"non-safe tools exposed over MCP: {non_safe} -- the MVP surface is "
        "100% safe-tier (§6.1). A medium/high tool is Tier 2.3 work behind the "
        "confirmation flow and (for high) the ADR-6 snapshot provider."
    )


def test_no_tool_is_exposed_at_a_tier_requiring_confirmation(
    tmp_path: Path,
) -> None:
    """The same fact from the other side, and it is not a restatement.

    The check above asks "is every tier safe". This asks "is any tier one that
    would need a user prompt" -- which is the question that actually matters,
    because how a confirmation reaches a user over MCP is DELIBERATELY
    UNRESOLVED (``broker/confirmation.py``: a Tier 2.3 decision, elicitation the
    candidate). A medium-tier tool would therefore be unusable rather than
    merely risky: the default confirmer refuses everything, so it would be
    exposed to a client and then refuse every call.
    """
    exposed = _exposed_tool_names(tmp_path)
    rows = _rows_by_name()
    needing_confirmation = sorted(
        name
        for name in exposed
        if rows[name].tier in _TIERS_REQUIRING_CONFIRMATION  # type: ignore[attr-defined]
    )
    assert not needing_confirmation, (
        f"tools exposed that would require confirmation: {needing_confirmation}. "
        "No confirmation channel to a user exists yet, so such a tool would be "
        "advertised and then refuse every call."
    )


def test_the_exposed_surface_is_a_subset_of_the_accounted_surface(
    tmp_path: Path,
) -> None:
    """No tool may be exposed without a row, because a row is the ONLY place an
    MCP tool's tier is written down. This is the load-bearing half of the
    weakness the module docstring names: without it, "every exposed tool is safe"
    could pass by a tool having no tier to be unsafe."""
    exposed = _exposed_tool_names(tmp_path)
    accounted = set(_rows_by_name())
    assert exposed <= accounted, (
        f"exposed but unaccounted: {sorted(exposed - accounted)}"
    )


def test_preflight_environment_tier_is_uncorroborated_and_that_is_known(
    tmp_path: Path,
) -> None:
    """NAMING THE GAP RATHER THAN LEAVING IT IMPLICIT (Part 6 §4).

    ``preflight_environment`` reaches no capability, so no ``CapabilitySpec``
    exists whose tier could be compared with its own. Its safe tier is a claim
    made by ``TOOL_SURFACE`` and checked against nothing else in the system.

    This test does not fix that -- it cannot; the tool genuinely dispatches
    nothing. What it does is make the situation ASSERTED rather than incidental,
    so a reader of the tier proofs knows exactly which part of the surface the
    registry vouches for and which part it does not. The completeness suite
    separately pins that exactly one tool is in this position.
    """
    exposed = _exposed_tool_names(tmp_path)
    binding = _rows_by_name()["preflight_environment"]
    assert "preflight_environment" in exposed
    assert binding.reaches_no_capability is True  # type: ignore[attr-defined]
    assert binding.capability is None  # type: ignore[attr-defined]
    assert binding.inner_capabilities == ()  # type: ignore[attr-defined]
    assert binding.tier == "safe"  # type: ignore[attr-defined]
