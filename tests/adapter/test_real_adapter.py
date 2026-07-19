"""RealAdapter unit tests (W-3) — driven against a hand-written PyAEDT double.

Honest scope (see real_adapter.py docstring): the double mimics PyAEDT's object
shape, so these verify our WIRING — attribute → contract mapping, per-section
not_readable degradation, the typed cannot_evaluate solve-state gaps, frequency
unit normalisation, and that _select mutates no AEDT active-selection state — NOT
that the assumed PyAEDT API is correct. That stays mock-only until live.
"""

from __future__ import annotations

import platform
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from hfss_agent.adapter.real import RealAdapter
from hfss_agent.adapter.results import AdapterCannotEvaluate, AdapterInternalError
from hfss_agent.contract import Environment, SolvedData, SolveState
from hfss_agent.contract.tool_io import SelectionChain, SelectionOption

_CONVERGENCE = {
    "passes": [{"pass": 1, "delta_s": 0.05}, {"pass": 2, "delta_s": 0.02}],
    "delta_s": [0.05, 0.02],
    "converged": True,
    "messages": ["Adaptive passes converged at pass 2."],
}
_PROFILE = datetime(2026, 7, 17, 9, 30, tzinfo=timezone.utc)


# --- the PyAEDT double -------------------------------------------------------


class FakeSolutionData:
    def __init__(self, freqs: list[float], unit: str, s: dict[str, list[tuple]]):
        self.primary_sweep_values = freqs
        self.primary_sweep_unit = unit
        self._s = s

    @property
    def expressions(self) -> list[str]:
        return list(self._s)

    def data_real(self, expression: str) -> list[float]:
        return [real for real, _ in self._s[expression]]

    def data_imag(self, expression: str) -> list[float]:
        return [imag for _, imag in self._s[expression]]


class FakeSetup:
    def __init__(
        self, name, *, is_solved=True, convergence=_CONVERGENCE, profile=_PROFILE
    ):
        self.name = name
        self.is_solved = is_solved
        self._convergence = convergence
        self._profile = profile

    def get_convergence_data(self):
        return self._convergence

    def get_profile(self):
        return self._profile


def _default_solution_data() -> FakeSolutionData:
    return FakeSolutionData(
        freqs=[2.4, 2.5],
        unit="GHz",
        s={"S(1,1)": [(-0.5, 0.1), (-0.2, 0.05)]},
    )


class FakeApp:
    """Duck-typed stand-in for a bound ``Hfss`` handle."""

    def __init__(self, **overrides):
        self.solution_type = overrides.get("solution_type", "DrivenModal")
        self.setup_names = overrides.get("setup_names", ["Setup1"])
        self._sweeps = overrides.get("sweeps", {"Setup1": ["Sweep1"]})
        self.excitation_names = overrides.get("excitation_names", ["1"])
        self.boundaries = overrides.get("boundaries", [SimpleNamespace(name="Rad1")])
        self.variable_manager = SimpleNamespace(
            variables=overrides.get("variables", {"width": "2.0mm"})
        )
        self.modeler = SimpleNamespace(
            object_names=overrides.get("object_names", ["Patch", "Substrate"])
        )
        self.materials = SimpleNamespace(
            material_keys=overrides.get(
                "materials",
                {"FR4": SimpleNamespace(permittivity=SimpleNamespace(value="4.4"))},
            )
        )
        self.setups = overrides.get("setups", [FakeSetup("Setup1")])
        self._reports = overrides.get("reports", ["S Parameter Plot 1"])
        self._variation_strings = overrides.get(
            "variation_strings", ["w='2mm' h='1.6mm'"]
        )
        self._solution_data = overrides.get("solution_data", _default_solution_data())

    def get_sweeps(self, setup: str) -> list[str]:
        return self._sweeps.get(setup, [])

    @property
    def available_variations(self):
        return SimpleNamespace(get_variation_strings=lambda: self._variation_strings)

    @property
    def post(self):
        return SimpleNamespace(
            all_report_names=self._reports,
            get_solution_data=lambda **kwargs: self._solution_data,
        )


class FakeSession:
    """Duck-typed ``LiveSession`` seam. Deliberately has NO set_active_* method:
    if RealAdapter ever reached for one, the call would fail rather than pass."""

    def __init__(self, app: FakeApp | None = None):
        self.app = app if app is not None else FakeApp()
        self.attached: int | None = None
        self.application_calls: list[tuple[str, str]] = []
        self.reset_bindings_calls = 0

    def attach(self, process_id: int) -> None:
        self.attached = process_id

    def reset_bindings(self) -> None:
        # Record that RealAdapter invalidated the seam's bindings on (re)attach.
        # Part 3 asserts re-attach drives this; the real clear's effect is live.
        self.reset_bindings_calls += 1

    def aedt_version(self) -> str:
        return "2026.1"

    def pyaedt_version(self) -> str:
        return "1.2.0"

    def project_names(self) -> list[str]:
        return ["patch_antenna"]

    def project_path(self, project: str) -> str:
        return r"C:\proj\patch_antenna.aedt"

    def design_names(self, project: str) -> list[str]:
        return ["HFSSDesign1"]

    def application(self, project: str, design: str) -> FakeApp:
        self.application_calls.append((project, design))
        return self.app

    def validate_native(self, project: str, design: str) -> list[str]:
        return ["Design validation completed. 0 errors, 0 warnings."]


def _adapter(app: FakeApp | None = None) -> tuple[RealAdapter, FakeSession]:
    session = FakeSession(app)
    return RealAdapter(session), session


def _fully_selected(app: FakeApp | None = None) -> tuple[RealAdapter, FakeSession]:
    adapter, session = _adapter(app)
    adapter.attach(1234)
    adapter.select("project", "patch_antenna")
    adapter.select("design", "HFSSDesign1")
    adapter.select("setup", "Setup1")
    adapter.select("sweep", "Sweep1")
    adapter.select("variation", "w='2mm'")
    return adapter, session


# --- attach ------------------------------------------------------------------


def test_attach_reports_environment_identity() -> None:
    adapter, session = _adapter()
    result = adapter.attach(4321)
    assert isinstance(result, Environment)
    assert session.attached == 4321
    assert result.aedt_version == "2026.1"
    assert result.pyaedt_version == "1.2.0"
    assert result.python_version == platform.python_version()
    assert result.wrapper_version == "0.0.0"


# --- list_options ------------------------------------------------------------


def test_list_options_projects() -> None:
    adapter, _ = _adapter()
    adapter.attach(1)
    options = adapter.list_options("project")
    assert [o.value for o in options] == ["patch_antenna"]


def test_list_options_design_requires_a_project_first() -> None:
    adapter, _ = _adapter()
    adapter.attach(1)
    result = adapter.list_options("design")
    assert isinstance(result, AdapterCannotEvaluate)
    assert "project" in result.limitation


def test_list_options_setups_and_sweeps() -> None:
    adapter, _ = _adapter()
    adapter.attach(1)
    adapter.select("project", "patch_antenna")
    adapter.select("design", "HFSSDesign1")
    assert [o.value for o in adapter.list_options("setup")] == ["Setup1"]
    adapter.select("setup", "Setup1")
    assert [o.value for o in adapter.list_options("sweep")] == ["Sweep1"]


def test_list_options_variations_parses_and_hashes() -> None:
    adapter, _ = _adapter()
    adapter.attach(1)
    adapter.select("project", "patch_antenna")
    adapter.select("design", "HFSSDesign1")
    options = adapter.list_options("variation")
    assert isinstance(options[0], SelectionOption)
    assert options[0].variation is not None
    assert options[0].variation.values == {"w": "2mm", "h": "1.6mm"}
    assert options[0].variation.variation_hash.startswith("sha256:")


def test_list_options_variations_unavailable_is_cannot_evaluate() -> None:
    adapter, _ = _adapter(FakeApp(variation_strings=[]))
    adapter.attach(1)
    adapter.select("project", "patch_antenna")
    adapter.select("design", "HFSSDesign1")
    result = adapter.list_options("variation")
    assert isinstance(result, AdapterCannotEvaluate)
    assert "variation" in result.limitation


# --- select (no active-selection mutation, CHANGE-1) -------------------------


def test_select_records_chain_and_reads_solution_type_without_mutation() -> None:
    adapter, session = _adapter()
    adapter.attach(1)
    adapter.select("project", "patch_antenna")
    chain = adapter.select("design", "HFSSDesign1")
    # A SelectionChain came back (not a fault) — so RealAdapter never reached for
    # a set_active_* method the seam does not define.
    assert isinstance(chain, SelectionChain)
    assert chain.project is not None and chain.project.name == "patch_antenna"
    assert chain.design == "HFSSDesign1"
    assert chain.solution_type == "DrivenModal"
    # solution_type was read by binding an app to (project, design), not by
    # activating anything.
    assert ("patch_antenna", "HFSSDesign1") in session.application_calls


# --- inspect -----------------------------------------------------------------


def test_inspect_all_sections_ok() -> None:
    adapter, _ = _adapter()
    adapter.attach(1)
    adapter.select("project", "patch_antenna")
    adapter.select("design", "HFSSDesign1")
    result = adapter.inspect(None)
    assert set(result) == {
        "variables",
        "objects",
        "materials",
        "boundaries",
        "excitations_ports",
        "setups",
        "sweeps",
        "available_results",
    }
    assert all(section.read_status == "ok" for section in result.values())
    assert result["boundaries"].data == ["Rad1"]
    assert result["materials"].data == {"FR4": {"permittivity": "4.4"}}


def test_inspect_subset_only_returns_requested_sections() -> None:
    adapter, _ = _adapter()
    adapter.attach(1)
    adapter.select("project", "patch_antenna")
    adapter.select("design", "HFSSDesign1")
    result = adapter.inspect(["objects"])
    assert set(result) == {"objects"}


def test_inspect_degrades_unreadable_section_in_band() -> None:
    # A material without a readable permittivity → not_readable for that section
    # only, with the specific limitation named; the design does not fail whole.
    app = FakeApp(materials={"FR4": object()})
    adapter, _ = _adapter(app)
    adapter.attach(1)
    adapter.select("project", "patch_antenna")
    adapter.select("design", "HFSSDesign1")
    result = adapter.inspect(None)
    assert result["materials"].read_status == "not_readable"
    assert "permittivity" in result["materials"].limitation
    # Other sections still read fine.
    assert result["objects"].read_status == "ok"


def test_inspect_without_selection_is_cannot_evaluate() -> None:
    adapter, _ = _adapter()
    adapter.attach(1)
    result = adapter.inspect(None)
    assert isinstance(result, AdapterCannotEvaluate)


# --- validate_native ---------------------------------------------------------


def test_validate_native_passthrough() -> None:
    adapter, _ = _adapter()
    adapter.attach(1)
    adapter.select("project", "patch_antenna")
    adapter.select("design", "HFSSDesign1")
    result = adapter.validate_native()
    assert result.source == "hfss_native"
    assert result.raw_output == ["Design validation completed. 0 errors, 0 warnings."]


# --- read_solve_state (approved cannot_evaluate gaps) ------------------------


def test_read_solve_state_success_has_freshness_undeterminable() -> None:
    adapter, _ = _fully_selected()
    result = adapter.read_solve_state()
    assert isinstance(result, SolveState)
    assert result.solution_exists[0].exists is True
    assert result.convergence_status == "converged"
    assert result.delta_s_progression == [0.05, 0.02]
    assert "Setup1:Sweep1" in result.solve_timestamps
    # Approved default: PyAEDT exposes no reliable freshness signal.
    assert result.freshness_evidence.determinable is False
    assert result.freshness_evidence.available_signals == {}


def test_read_solve_state_missing_convergence_is_specific_cannot_evaluate() -> None:
    app = FakeApp(setups=[FakeSetup("Setup1", convergence=None)])
    adapter, _ = _fully_selected(app)
    result = adapter.read_solve_state()
    assert isinstance(result, AdapterCannotEvaluate)
    assert result.limitation  # non-empty
    assert "convergence" in result.limitation
    assert result.limitation != "cannot evaluate"


def test_read_solve_state_missing_timestamp_is_specific_cannot_evaluate() -> None:
    app = FakeApp(setups=[FakeSetup("Setup1", profile=None)])
    adapter, _ = _fully_selected(app)
    result = adapter.read_solve_state()
    assert isinstance(result, AdapterCannotEvaluate)
    assert result.limitation
    assert "timestamp" in result.limitation


def test_read_solve_state_requires_full_selection() -> None:
    adapter, _ = _adapter()
    adapter.attach(1)
    adapter.select("project", "patch_antenna")
    adapter.select("design", "HFSSDesign1")
    result = adapter.read_solve_state()
    assert isinstance(result, AdapterCannotEvaluate)


# --- read_solved_data --------------------------------------------------------


def test_read_solved_data_normalises_frequency_to_hz() -> None:
    adapter, _ = _fully_selected()
    result = adapter.read_solved_data()
    assert isinstance(result, SolvedData)
    assert result.frequencies == [2.4e9, 2.5e9]
    samples = result.s_parameters["S(1,1)"]
    assert (samples[0].real, samples[0].imag) == (-0.5, 0.1)


def test_read_solved_data_unknown_unit_is_cannot_evaluate() -> None:
    app = FakeApp(
        solution_data=FakeSolutionData([2.4], "furlongs", {"S(1,1)": [(-0.5, 0.1)]})
    )
    adapter, _ = _fully_selected(app)
    result = adapter.read_solved_data()
    assert isinstance(result, AdapterCannotEvaluate)
    assert "furlongs" in result.limitation


def test_read_solved_data_requires_setup_and_sweep() -> None:
    adapter, _ = _adapter()
    adapter.attach(1)
    adapter.select("project", "patch_antenna")
    adapter.select("design", "HFSSDesign1")
    result = adapter.read_solved_data()
    assert isinstance(result, AdapterCannotEvaluate)


@pytest.mark.parametrize("process_id", [1, 999])
def test_attach_resets_selection(process_id: int) -> None:
    # Re-attach starts a fresh selection chain (mirrors FakeAdapter semantics).
    adapter, _ = _fully_selected()
    adapter.attach(process_id)
    result = adapter.inspect(None)
    assert isinstance(result, AdapterCannotEvaluate)


# --- stale-scope fix: downstream reset + incoherent-scope guard --------------


def test_reselecting_project_clears_downstream_scope() -> None:
    # After a full chain, re-selecting the project drops every stage below it, so
    # _scope can never bind (new_project, stale_design).
    adapter, _ = _fully_selected()
    chain = adapter.select("project", "patch_antenna")
    assert chain.design is None
    assert chain.solution_type is None
    assert chain.setup is None
    assert chain.sweep is None
    assert chain.variation is None


def test_incoherent_scope_is_internal_error_not_cannot_evaluate() -> None:
    # A design bound with no project can only come from an out-of-order/stale
    # select — our bug, not the user's process dying (ADR-17 #3). A read over that
    # scope returns AdapterInternalError, never a user-actionable cannot_evaluate.
    adapter, session = _adapter()
    adapter.attach(1)
    adapter.select("design", "HFSSDesign1")  # no project selected first
    result = adapter.inspect(None)
    assert isinstance(result, AdapterInternalError)
    assert not isinstance(result, AdapterCannotEvaluate)
    assert "incoherent" in result.detail
    # It refused to bind: no app was ever requested for the incoherent scope.
    assert session.application_calls == []


def test_scope_is_pure_and_needs_no_live_handle() -> None:
    # _scope reads only self._selection — it binds no app and touches no handle,
    # so its logic is fully exercisable license-free (answering the design
    # question: yes, the scope-computation logic is testable without a live
    # handle). Drive it directly and confirm no binding was attempted.
    adapter, session = _adapter()
    adapter.attach(1)
    adapter.select("design", "HFSSDesign1")  # incoherent: design without project
    scope = adapter._scope()
    assert isinstance(scope, AdapterInternalError)
    assert session.application_calls == []
