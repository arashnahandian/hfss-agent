"""The seventeen-name accounting table, and the self-invalidating deferrals.

WHAT MAKES THE DEFERRAL TESTS WORTH HAVING. A list of what IS registered cannot
notice a tool that should have been. These tests take the opposite shape: for
each deferred row, they assert THE NAMED MISSING PIECE IS STILL MISSING. The day
Step 3.3 or 3.4 builds one, the corresponding test fails and forces the row to
be updated and the tool registered -- instead of the deferral quietly outliving
its reason.

EVERY CHECK IS AST-BASED OVER ``src/``, NEVER A TEXT SEARCH. Every one of these
names appears in prose somewhere -- ``get_solve_health`` is in a docstring in
``adapter/base.py``, ``list_aedt_processes`` is named in the contract and in
``docs/pyaedt-coverage.md`` -- so a substring grep would report every deferral as
already built. The walks below look for a real ``def`` or a real constructor
call, which is what "the piece exists" actually means.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hfss_agent.server.tool_surface import (
    DEFERRED_TOOLS,
    REGISTERED_TOOLS,
    TOOL_SURFACE,
    ToolBinding,
    binding_for,
)

_SRC = Path(__file__).resolve().parents[2] / "src" / "hfss_agent"
_ADAPTER = _SRC / "adapter"

# The seventeen §3 names, written out independently of TOOL_SURFACE so the table
# is checked against the specification rather than against itself.
_SECTION_3_TOOLS = (
    "preflight_environment",
    "list_aedt_processes",
    "attach",
    "list_selection_options",
    "select",
    "get_session_status",
    "inspect_design",
    "validate_setup",
    "check_solution_validity",
    "compute_metrics",
    "get_solve_health",
    "export_results",
    "set_design_intent",
    "get_design_intent",
    "clear_design_intent",
    "get_audit_log",
    "export_diagnostics_bundle",
)


def _sources() -> list[Path]:
    files = sorted(_SRC.rglob("*.py"))
    assert files, f"no sources discovered under {_SRC}"
    return files


def _defines_function(name: str) -> list[str]:
    """Files defining a function (sync or async) called ``name``."""
    hits = []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == name:
                    hits.append(str(path.relative_to(_SRC)))
    return sorted(set(hits))


def _constructs(type_name: str) -> list[str]:
    """Files containing a call to ``type_name(...)``.

    Matches a bare name only. ``contract/tool_io`` DEFINES these classes but
    never calls them, so a definition does not register as a construction --
    which is the distinction the deferral rests on.
    """
    hits = []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == type_name:
                    hits.append(str(path.relative_to(_SRC)))
    return sorted(set(hits))


def _calls_attribute_outside_adapter(method: str) -> list[str]:
    """Files OUTSIDE ``adapter/`` that call ``<anything>.method(...)``.

    This is the check behind the four solve-data deferrals. Their shared missing
    piece is not a composer but an ACQUISITION PATH: ``Adapter`` exposes
    ``read_solve_state`` and ``read_solved_data``, and nothing above Layer 2
    calls either, so no module can obtain a ``SolveState`` or ``SolvedData`` at
    all. It is deliberately name-agnostic about what the new caller would be
    called -- a ``Session.read_solve_state``, a ``Session.solve_health``, a new
    capability -- because whatever its name, it must reach one of these two
    adapter operations, and that is what this notices.
    """
    hits = []
    for path in _sources():
        if path.is_relative_to(_ADAPTER):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == method:
                    hits.append(str(path.relative_to(_SRC)))
    return sorted(set(hits))


# --- the table itself --------------------------------------------------------


def test_the_table_carries_every_section_3_tool_exactly_once() -> None:
    names = [binding.name for binding in TOOL_SURFACE]
    assert sorted(names) == sorted(_SECTION_3_TOOLS)
    assert len(names) == len(set(names)), "a §3 name appears twice"


def test_every_row_is_safe_tier() -> None:
    """§6.1: the entire MVP surface is safe tier. Asserted over the TOOL table,
    which is a different collection from the capability registry the tier proof
    iterates -- the two are cross-checked in Part 7, neither trusting the other."""
    non_safe = [(b.name, b.tier) for b in TOOL_SURFACE if b.tier != "safe"]
    assert not non_safe, f"non-safe tools declared: {non_safe}"


def test_registered_and_deferred_partition_the_surface() -> None:
    assert set(REGISTERED_TOOLS) | set(DEFERRED_TOOLS) == set(_SECTION_3_TOOLS)
    assert not set(REGISTERED_TOOLS) & set(DEFERRED_TOOLS)
    assert len(REGISTERED_TOOLS) == 11
    assert len(DEFERRED_TOOLS) == 6


def test_a_deferred_row_must_name_its_missing_piece() -> None:
    """Structural, at construction time -- the ``CapabilitySpec.tier`` trick.
    A deferral nothing can check for is a deferral nobody will notice going
    stale."""
    with pytest.raises(ValueError, match="names no missing piece"):
        ToolBinding(name="x", tier="safe", status="deferred", summary="s")


def test_a_registered_row_must_reach_the_registry_somehow() -> None:
    with pytest.raises(ValueError, match="neither a direct capability"):
        ToolBinding(name="x", tier="safe", status="registered", summary="s")


def test_an_assembler_row_states_inner_capabilities_or_declares_none() -> None:
    """"Reaches no capability" and "nobody filled this in" are different facts;
    an empty tuple cannot tell them apart, so the row must say which."""
    with pytest.raises(ValueError, match="names no inner capabilities"):
        ToolBinding(
            name="x",
            tier="safe",
            status="registered",
            summary="s",
            assembler="a.b.c",
        )
    with pytest.raises(ValueError, match="claims to reach none"):
        ToolBinding(
            name="x",
            tier="safe",
            status="registered",
            summary="s",
            assembler="a.b.c",
            inner_capabilities=("k",),
            reaches_no_capability=True,
        )


# --- the three-hop mapping (ADR-24 decision 2) -------------------------------


def test_the_three_hop_mapping_is_expressible_for_validate_setup() -> None:
    """tool ``validate_setup`` -> assembler ``validate_native`` -> capability
    ``validate_native``. Three things, and the tool name matches neither of the
    other two -- which is why a one-hop, name-keyed mapping cannot express it.

    Asserted even though the tool is DEFERRED: the mapping is what makes the
    deferral reviewable, and it is known now.
    """
    binding = binding_for("validate_setup")
    assert binding is not None
    assert binding.status == "deferred"
    assert binding.assembler == "hfss_agent.validate_native.assembler.validate_native"
    assert "validate_native" in binding.inner_capabilities
    assert binding.name != binding.inner_capabilities[0]


def test_one_name_meaning_three_things_is_expressible_for_inspect_design() -> None:
    """The harder case: tool, assembler and capability are ALL spelled
    ``inspect_design``, the assembler is deliberately not the capability, and it
    dispatches a SECOND capability to build its provenance stamp."""
    binding = binding_for("inspect_design")
    assert binding is not None
    assert binding.assembler == "hfss_agent.inspect.assembler.inspect_design"
    assert binding.capability is None, (
        "inspect_design must NOT be recorded as a direct capability mapping: the "
        "registered capability of that name is Session.inspect, a different and "
        "differently-shaped thing from the W-5 assembler this tool calls."
    )
    assert set(binding.inner_capabilities) == {"inspect_design", "get_session_status"}


def test_every_assembler_path_is_importable() -> None:
    """A dotted path that does not resolve is an accounting entry describing
    nothing."""
    import importlib

    for binding in TOOL_SURFACE:
        if binding.assembler is None:
            continue
        module_path, _, attribute = binding.assembler.rpartition(".")
        module = importlib.import_module(module_path)
        assert hasattr(module, attribute), (
            f"{binding.name}: assembler {binding.assembler!r} does not resolve"
        )


# --- the self-invalidating deferrals -----------------------------------------


def test_list_aedt_processes_still_has_no_callable() -> None:
    """FAILS WHEN: anyone defines a function called ``list_aedt_processes`` in
    ``src/``. That is the whole missing piece -- there is no partial
    implementation to distinguish from a finished one."""
    defined = _defines_function("list_aedt_processes")
    assert not defined, (
        f"list_aedt_processes is now defined in {defined}. Register the tool and "
        "update its tool_surface row -- the deferral has expired."
    )


def test_validate_setup_still_has_no_validation_report_composer() -> None:
    """FAILS WHEN: anything in ``src/`` constructs a ``ValidationReport``.

    W-6 produces the native block and nothing more; composing the report's four
    fields needs judgments findings/render.py assigns to Step 3.3.
    """
    composes = _constructs("ValidationReport")
    assert not composes, (
        f"ValidationReport is now constructed in {composes}. validate_setup can "
        "be registered; update its tool_surface row."
    )


def test_check_solution_validity_still_has_no_report_composer() -> None:
    """FAILS WHEN: anything in ``src/`` constructs a ``SolutionValidityReport``.
    gating/gates.py assigns that composition to Step 3.4 in as many words."""
    composes = _constructs("SolutionValidityReport")
    assert not composes, (
        f"SolutionValidityReport is now constructed in {composes}. "
        "check_solution_validity can be registered."
    )


def test_get_solve_health_still_has_no_assembler() -> None:
    """FAILS WHEN: anything in ``src/`` constructs a ``SolveHealthReport``."""
    composes = _constructs("SolveHealthReport")
    assert not composes, (
        f"SolveHealthReport is now constructed in {composes}. get_solve_health "
        "can be registered."
    )


def test_export_results_still_has_no_entry_point() -> None:
    """FAILS WHEN: anyone defines ``export_results`` in ``src/``.

    Note this is NOT satisfied by ``export_diagnostics_bundle``, which exists and
    is registered -- a different name for a different tool.
    """
    defined = _defines_function("export_results")
    assert not defined, (
        f"export_results is now defined in {defined}. Register the tool and "
        "update its tool_surface row."
    )


@pytest.mark.parametrize("operation", ["read_solve_state", "read_solved_data"])
def test_no_solve_data_acquisition_path_exists_above_the_adapter(
    operation: str,
) -> None:
    """THE SHARED MISSING PIECE behind four deferrals, checked once per adapter
    operation.

    ``compute_metrics`` is fully built and still cannot be registered, because
    nothing above Layer 2 can obtain a ``SolvedData`` to hand it: ``Session``
    exposes no solve read, so no capability exists, so no assembler can dispatch
    one. FAILS WHEN: any module outside ``adapter/`` calls either operation --
    whatever the new caller is named. Name-agnostic on purpose: the acquisition
    must go through one of these two operations, so this notices it arriving
    without having to guess what someone will call it.
    """
    callers = _calls_attribute_outside_adapter(operation)
    assert not callers, (
        f"{operation} is now called outside adapter/ in {callers}. A solve-data "
        "acquisition path exists, so compute_metrics, get_solve_health, "
        "export_results and check_solution_validity may now be registerable; "
        "re-check each tool_surface row rather than assuming."
    )


def test_the_absence_detectors_actually_detect_presence() -> None:
    """META-TEST: the detectors above are only worth having if they FIRE.

    Each is pointed at something that genuinely exists in ``src/`` today, so a
    detector that silently matched nothing -- a bad AST walk, a wrong node type,
    a path that discovered no files -- shows up here rather than as six
    permanently-green deferral tests.
    """
    assert _defines_function("compute_metrics"), "FunctionDef walk found nothing"
    assert _defines_function("export_diagnostics_bundle"), "FunctionDef walk broken"
    assert _constructs("SelectionChain"), "Call walk found no known construction"
    assert _calls_attribute_outside_adapter("dispatch"), "attribute walk broken"
