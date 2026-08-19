"""Registry completeness (ADR-19 as amended by ADR-33), proved against real objects.

THE CLAIM BEING PROVED: every tool the server exposes is accounted for in the
tier system -- directly if it maps to a capability, or transitively through a
named assembler whose every inner dispatch is a registered capability. ADR-19
records this as the WEAKER of its two claims: "no tier means no registration" is
structural (a ``CapabilitySpec`` without a tier is a ``TypeError``), while "every
tool is accounted for at all" is CI-enforced, by this file.

WHAT MAKES THIS NOT A TAUTOLOGY. Three different objects are compared, none of
them derived from the others at test time:

  * the tools actually registered on a real ``MCPServer``, read back from the
    server via ``list_tools()`` -- the same call a client makes;
  * the ``TOOL_SURFACE`` accounting table;
  * the ``CapabilityRegistry`` built by the production ``build_composition``.

A test that read ``TOOL_SURFACE`` and asserted ``TOOL_SURFACE`` was self-
consistent would prove nothing, so every assertion below has at least one side
that is a live object.

ONE DIRECTION IS PARTLY GUARANTEED BY CONSTRUCTION, AND SAYING SO IS THE POINT.
``app._describe()`` looks a tool's description up in ``TOOL_SURFACE`` and raises
``KeyError`` for a name with no row, so "every registered tool has a row" is
already hard to violate through ``build_app``. That makes
``test_every_registered_tool_has_a_row`` a belt on top of braces rather than the
only guard -- it still catches a tool registered by any path that does not use
``_describe`` (see the module docstring's WHAT THIS CANNOT SEE). The reverse
direction, and every capability and tier check below, are not guaranteed by
anything and are where the real work is.

WHAT THIS CANNOT SEE, stated so nobody reads a green run as more than it is:
tools registered on some OTHER ``MCPServer`` instance, or added to this one
after ``build_app`` returns. This file proves the surface that ``build_app``
produces; it cannot prove that ``build_app`` is the only thing that ever
registers a tool.
"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest
from server_helpers import composed_app

from hfss_agent.server.tool_surface import TOOL_SURFACE, ToolBinding, binding_for


def _rows() -> tuple[ToolBinding, ...]:
    return TOOL_SURFACE


# --- direction 1: live server -> table ---------------------------------------


def test_every_registered_tool_has_a_row(tmp_path: Path) -> None:
    """Read the tools back OFF THE SERVER, not off a list written here.

    Partly guaranteed by ``_describe`` raising for an unknown name (see the
    module docstring); kept because that guarantee only covers registration
    that goes through ``_describe``.
    """
    _, registered = composed_app(tmp_path)
    accounted = {binding.name for binding in _rows()}
    unaccounted = sorted(registered - accounted)
    assert not unaccounted, (
        f"tools registered with no TOOL_SURFACE row: {unaccounted}. ADR-33 "
        "requires every exposed tool to be accounted for in the tier system."
    )


# --- direction 2: table -> live server ---------------------------------------


def test_every_row_marked_registered_is_actually_registered(tmp_path: Path) -> None:
    """The direction nothing guarantees: a row can CLAIM to be registered while
    no handler exists. Nothing in ``build_app`` would notice."""
    _, registered = composed_app(tmp_path)
    claimed = {b.name for b in _rows() if b.status == "registered"}
    missing = sorted(claimed - registered)
    assert not missing, (
        f"rows marked 'registered' with no tool on the server: {missing}. "
        "Either register them or mark them deferred with a missing piece."
    )


def test_every_deferred_row_is_absent_from_the_server(tmp_path: Path) -> None:
    """The other half: a deferred row must not be exposed. A tool that is live
    while its row says 'deferred, missing X' means the deferral is a lie and
    the self-invalidating check in test_tool_surface is guarding nothing."""
    _, registered = composed_app(tmp_path)
    deferred = {b.name for b in _rows() if b.status == "deferred"}
    leaked = sorted(deferred & registered)
    assert not leaked, (
        f"tools exposed while their row says deferred: {leaked}."
    )


def test_the_two_directions_together_are_an_exact_match(tmp_path: Path) -> None:
    """Subset in each direction is set equality; asserted directly so a failure
    reports the symmetric difference rather than one half of it."""
    _, registered = composed_app(tmp_path)
    claimed = {b.name for b in _rows() if b.status == "registered"}
    assert claimed == registered, (
        f"table says {sorted(claimed)}; server exposes {sorted(registered)}"
    )


# --- the tier system: rows -> the real registry -------------------------------


def test_every_declared_capability_exists_in_the_production_registry(
    tmp_path: Path,
) -> None:
    """Direct mappings resolve against the registry ``build_composition``
    actually builds -- not a list of names written in this file."""
    composition, _ = composed_app(tmp_path)
    known = {spec.name for spec in composition.registry.specs}
    dangling = [
        (b.name, b.capability)
        for b in _rows()
        if b.capability is not None and b.capability not in known
    ]
    assert not dangling, (
        f"rows naming capabilities the registry does not hold: {dangling}"
    )


def test_every_inner_capability_exists_in_the_production_registry(
    tmp_path: Path,
) -> None:
    """THE TRANSITIVE HALF OF ADR-33. An assembler-backed tool is accounted for
    only if every capability it dispatches is registered -- otherwise the tool
    reaches something with no declared tier, which is the exact hole ADR-5
    exists to close."""
    composition, _ = composed_app(tmp_path)
    known = {spec.name for spec in composition.registry.specs}
    dangling = {
        b.name: sorted(set(b.inner_capabilities) - known)
        for b in _rows()
        if set(b.inner_capabilities) - known
    }
    assert not dangling, (
        f"assembler rows dispatching unregistered capabilities: {dangling}"
    )


def test_declared_tiers_match_the_registry_where_both_exist(tmp_path: Path) -> None:
    """TWO INDEPENDENT DECLARATIONS, COMPARED. ``TOOL_SURFACE`` states a tool's
    tier; ``CapabilitySpec`` states its capability's. Nothing derives one from
    the other, so they can disagree -- and a tool advertised safe over a
    medium-tier capability is precisely the misregistration ADR-5 refuses."""
    composition, _ = composed_app(tmp_path)
    mismatched = []
    for binding in _rows():
        if binding.capability is None:
            continue
        spec = composition.registry.get(binding.capability)
        assert spec is not None, f"{binding.name}: capability vanished mid-test"
        if spec.tier != binding.tier:
            mismatched.append((binding.name, binding.tier, spec.name, spec.tier))
    assert not mismatched, (
        f"tool tier disagrees with its capability's tier: {mismatched}"
    )


def test_no_safe_tool_dispatches_a_non_safe_capability(tmp_path: Path) -> None:
    """A tool cannot be safer than what it reaches. Vacuous today because the
    whole surface is safe tier -- and it stops being vacuous the moment a
    medium-tier capability is added, which is when it matters."""
    composition, _ = composed_app(tmp_path)
    escalations = []
    for binding in _rows():
        if binding.tier != "safe":
            continue
        for name in binding.inner_capabilities:
            spec = composition.registry.get(name)
            if spec is not None and spec.tier != "safe":
                escalations.append((binding.name, name, spec.tier))
    assert not escalations, (
        f"safe-tier tools dispatching non-safe capabilities: {escalations}"
    )


def test_every_row_declares_a_tier() -> None:
    """Structural at construction (a required field with no default), so this
    can only fail if the dataclass changes. Kept as the statement of the rule."""
    assert all(binding.tier for binding in _rows())


# --- the assembler-path audit (Part 6 §10) ------------------------------------


def test_no_assembler_lives_inside_the_server_package() -> None:
    """THE CHECK THAT KEEPS THE NO-COMPOSITION RULE FROM BECOMING DECORATION.

    ``app`` forbids composition in a handler, and Part 6 measured that the rule
    held: no helper module appeared, and ``validate_setup`` deferred rather than
    the rule bending. But the rule only stays real if the composition someone
    eventually writes lands BELOW Layer 7. If the ``ValidationReport`` composer
    is dropped into ``hfss_agent/server/``, every handler stays two lines while
    the assembly it was supposed to keep out moves in next door under a
    different filename.

    FAILS WHEN: any ``TOOL_SURFACE`` row names an assembler whose module is
    inside ``hfss_agent.server``.
    """
    inside = [
        (b.name, b.assembler)
        for b in _rows()
        if b.assembler is not None
        and b.assembler.startswith("hfss_agent.server.")
    ]
    assert not inside, (
        f"assemblers inside the server package: {inside}. Layer 7 is "
        "scaffolding; the assembly belongs in a feature module below it."
    )


def test_every_assembler_path_resolves_to_a_real_callable() -> None:
    """A dotted path that does not import is an accounting entry describing
    nothing, and would let the audit above pass by naming a fiction."""
    for binding in _rows():
        if binding.assembler is None:
            continue
        module_path, _, attribute = binding.assembler.rpartition(".")
        module = importlib.import_module(module_path)
        resolved = getattr(module, attribute, None)
        assert callable(resolved), (
            f"{binding.name}: assembler {binding.assembler!r} is not a callable"
        )


# --- floors: the checks that stop the ones above going vacuous ----------------


def test_the_surface_is_not_empty(tmp_path: Path) -> None:
    """Every assertion above is a "no offenders" check, and all of them pass
    trivially against an empty surface. This is what makes them mean something."""
    composition, registered = composed_app(tmp_path)
    assert len(registered) == 11, f"expected 11 registered tools, got {len(registered)}"
    assert len(_rows()) == 17, "the §3 surface is seventeen names"
    assert composition.registry.specs, "an empty registry would vacate the tier checks"


def test_reading_the_server_back_agrees_with_reading_the_manager(
    tmp_path: Path,
) -> None:
    """``list_tools()`` is what a client sees; ``_tool_manager`` is what the
    server holds. The completeness proof uses the former, so this pins that the
    two agree -- a divergence would mean the proof describes a surface no client
    is offered."""
    app, registered = composed_app(tmp_path, want_app=True)
    held = set(app._tool_manager._tools)
    assert held == registered


@pytest.mark.parametrize("name", ["inspect_design", "export_diagnostics_bundle"])
def test_assembler_backed_tools_are_accounted_for_transitively(
    name: str, tmp_path: Path
) -> None:
    """The two registered assembler-backed tools, checked end to end: exposed on
    the server, no direct capability, and every capability they dispatch present
    in the real registry."""
    composition, registered = composed_app(tmp_path)
    binding = binding_for(name)
    assert binding is not None and binding.name in registered
    assert binding.assembler is not None
    known = {spec.name for spec in composition.registry.specs}
    assert set(binding.inner_capabilities) <= known
    assert binding.inner_capabilities, "would be vacuous with an empty tuple"


def test_the_one_tool_that_reaches_no_capability_is_named_and_singular(
    tmp_path: Path,
) -> None:
    """``preflight_environment``'s safe tier rests on ``TOOL_SURFACE`` ALONE.

    It dispatches nothing -- it reads injected probes and the broker's
    non-dispatchable ``require_environment`` accessor -- so no ``CapabilitySpec``
    corroborates its tier, and ``test_declared_tiers_match_the_registry_where_
    both_exist`` skips it by construction. That is a real, narrow gap in the
    cross-check, and this test exists to keep it NARROW: exactly one tool may be
    in that position, and it must be this one. A second uncorroborated tool
    appearing is a change to how much of the surface the registry can vouch for,
    and should be a decision rather than a discovery.
    """
    _, registered = composed_app(tmp_path)
    uncorroborated = sorted(
        b.name
        for b in _rows()
        if b.status == "registered" and b.reaches_no_capability
    )
    assert uncorroborated == ["preflight_environment"], (
        f"tools whose tier no capability corroborates: {uncorroborated}. Only "
        "preflight_environment is authorised to be in that position; anything "
        "else needs a decision about how its tier is vouched for."
    )
    assert "preflight_environment" in registered


def test_asyncio_list_tools_is_the_client_visible_surface(tmp_path: Path) -> None:
    """Sanity floor for the read-back helper itself: it must return names, not
    Tool objects or an empty set, or every subset assertion above passes for the
    wrong reason."""
    _, registered = composed_app(tmp_path)
    assert registered
    assert all(isinstance(name, str) for name in registered)
    assert "attach" in registered


def test_list_tools_is_awaitable_and_stable_across_calls(tmp_path: Path) -> None:
    """Two reads of the same server return the same surface -- so a completeness
    result is a property of the server, not of when it was asked."""
    app, first = composed_app(tmp_path, want_app=True)
    second = {tool.name for tool in asyncio.run(app.list_tools())}
    assert first == second
