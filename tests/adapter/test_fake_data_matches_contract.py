"""FakeAdapter canned data validates against the real contract schemas (W-3).

Every operation returns an existing contract sub-model (or a list/dict of them);
each is a valid instance AND round-trips through plain JSON-serializable data
(model_dump -> model_validate), which is what the W-8 snapshot needs. Also
covers the "a design section that fails to read" data shape.
"""

from hfss_agent.adapter.fake import FakeAdapter, Scenario
from hfss_agent.contract import (
    Environment,
    InspectionSection,
    NativeValidation,
    SolvedData,
    SolveState,
)
from hfss_agent.contract.tool_io import SelectionChain, SelectionOption


def _round_trips(model) -> bool:
    return type(model).model_validate(model.model_dump(mode="python")) == model


def _drive_full_selection(adapter: FakeAdapter) -> SelectionChain:
    """attach + select every stage on the default scenario; return the chain."""
    adapter.attach(4321)
    adapter.select("project", "patch_antenna")
    adapter.select("design", "HFSSDesign1")
    adapter.select("setup", "Setup1")
    adapter.select("sweep", "Sweep1")
    return adapter.select("variation", "sha256:defaultvariation")


def test_attach_returns_environment(fake: FakeAdapter) -> None:
    env = fake.attach(4321)
    assert isinstance(env, Environment)
    assert _round_trips(env)


def test_list_options_returns_selection_options(fake: FakeAdapter) -> None:
    options = fake.list_options("design")
    assert isinstance(options, list)
    assert all(isinstance(o, SelectionOption) for o in options)
    assert options[0].value == "HFSSDesign1"


def test_select_accumulates_a_valid_chain(fake: FakeAdapter) -> None:
    chain = _drive_full_selection(fake)
    assert isinstance(chain, SelectionChain)
    assert chain.process_id == 4321
    assert chain.project is not None and chain.project.name == "patch_antenna"
    assert chain.design == "HFSSDesign1"
    assert chain.solution_type == "DrivenModal"
    assert chain.setup == "Setup1"
    assert chain.sweep == "Sweep1"
    assert chain.variation is not None
    assert _round_trips(chain)


def test_inspect_full_returns_all_eight_sections(fake: FakeAdapter) -> None:
    sections = fake.inspect()
    assert set(sections) == {
        "variables",
        "objects",
        "materials",
        "boundaries",
        "excitations_ports",
        "setups",
        "sweeps",
        "available_results",
    }
    for section in sections.values():
        assert isinstance(section, InspectionSection)
        assert section.read_status == "ok"
        assert _round_trips(section)


def test_inspect_subset_returns_only_requested(fake: FakeAdapter) -> None:
    sections = fake.inspect(["variables", "objects"])
    assert set(sections) == {"variables", "objects"}


def test_inspect_reports_a_not_readable_section() -> None:
    # The "a design section that fails to read" shape is data, not a fault: the
    # section carries read_status="not_readable" and names the PyAEDT limitation.
    scenario = Scenario()
    scenario.inspection["boundaries"] = InspectionSection(
        data=None,
        read_status="not_readable",
        limitation="PyAEDT get_boundaries() raised for this design type.",
    )
    fake = FakeAdapter(scenario)
    boundaries = fake.inspect(["boundaries"])["boundaries"]
    assert boundaries.read_status == "not_readable"
    assert "PyAEDT" in boundaries.limitation


def test_validate_native_returns_native_validation(fake: FakeAdapter) -> None:
    native = fake.validate_native()
    assert isinstance(native, NativeValidation)
    assert native.source == "hfss_native"
    assert _round_trips(native)


def test_read_solve_state_returns_solve_state(fake: FakeAdapter) -> None:
    state = fake.read_solve_state()
    assert isinstance(state, SolveState)
    assert state.convergence_status == "converged"
    assert _round_trips(state)


def test_read_solved_data_returns_solved_data(fake: FakeAdapter) -> None:
    data = fake.read_solved_data()
    assert isinstance(data, SolvedData)
    assert data.frequencies and "S(1,1)" in data.s_parameters
    assert _round_trips(data)
