"""Adapter ABC (W-3): the capability boundary's enforced-complete interface.

An ABC, not a Protocol, for two structural guarantees:

1. Construction-time completeness — an implementation that omits an operation
   fails at instantiation (``@abstractmethod``), not at first call. The single
   trusted boundary is provably complete or it does not construct.
2. Template-method for the cross-cutting guarantees — the per-call watchdog AND
   untrusted-string sanitization (ADR-9) live in the concrete public methods
   here, so every implementation (``FakeAdapter`` now, the real PyAEDT adapter
   later) inherits both and cannot forget either.

The public methods return lean ``DesignSnapshot`` sub-models (plus
``SelectionOption`` / ``SelectionChain``) — never the ``tool_io`` response types,
which carry ``template_text``, provenance, the suspect flag, and the
downstream-computed findings/metrics assembled above this layer.

These seven operations are the whole surface the ten PyAEDT-reaching tools need:
  * attach                    -> attach
  * list_options              -> list_selection_options
  * select                    -> select
  * inspect                   -> inspect_design
  * validate_native           -> validate_setup (native passthrough only)
  * read_solve_state          -> check_solution_validity, get_solve_health,
                                 compute_metrics (gate), export_diagnostics_bundle
  * read_solved_data          -> compute_metrics, export_results,
                                 check_solution_validity (freq axis),
                                 export_diagnostics_bundle
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from hfss_agent.adapter.results import AdapterResult
from hfss_agent.adapter.sanitize import sanitize_result
from hfss_agent.adapter.watchdog import DEFAULT_TIMEOUT_SECONDS, run_with_watchdog
from hfss_agent.contract import (
    Environment,
    InspectionSection,
    NativeValidation,
    SolvedData,
    SolveState,
)
from hfss_agent.contract.tool_io import (
    InspectionSectionName,
    SelectionChain,
    SelectionOption,
    SelectionStage,
)


class Adapter(ABC):
    """The capability boundary. Subclasses implement the ``_`` primitives; the
    public methods wrap each primitive with the watchdog and sanitization."""

    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    # --- public capability surface: every call watchdog-guarded + sanitized ---

    def attach(self, process_id: int) -> AdapterResult[Environment]:
        """Attach-only connect to a running AEDT process; report version identity."""
        return self._run("attach", lambda: self._attach(process_id))

    def list_options(
        self, stage: SelectionStage
    ) -> AdapterResult[list[SelectionOption]]:
        """Enumerate the choices for a selectable stage."""
        return self._run("list_options", lambda: self._list_options(stage))

    def select(
        self, stage: SelectionStage, choice: str
    ) -> AdapterResult[SelectionChain]:
        """Set the active project/design/setup/sweep/variation; return the chain."""
        return self._run("select", lambda: self._select(stage, choice))

    def inspect(
        self, sections: list[InspectionSectionName] | None = None
    ) -> AdapterResult[dict[InspectionSectionName, InspectionSection]]:
        """Read the requested inspection sections (or all eight when None)."""
        return self._run("inspect", lambda: self._inspect(sections))

    def validate_native(self) -> AdapterResult[NativeValidation]:
        """Run HFSS ValidateDesign; return the raw, attributed passthrough."""
        return self._run("validate_native", lambda: self._validate_native())

    def read_solve_state(self) -> AdapterResult[SolveState]:
        """Read the solve-state block for the current selection."""
        return self._run("read_solve_state", lambda: self._read_solve_state())

    def read_solved_data(self) -> AdapterResult[SolvedData]:
        """Read the raw S-parameter series scoped to the current selection."""
        return self._run("read_solved_data", lambda: self._read_solved_data())

    # --- template path: watchdog then sanitize, on every call -----------------

    def _run(
        self, name: str, primitive: Callable[[], AdapterResult[object]]
    ) -> AdapterResult[object]:
        raw = run_with_watchdog(primitive, self._timeout_seconds, name)
        # Sanitize the returned data (and any string fields on a fault outcome)
        # before it leaves the capability boundary — ADR-9's enforcement point.
        return sanitize_result(raw)

    # --- primitives every implementation must provide -------------------------

    @abstractmethod
    def _attach(self, process_id: int) -> AdapterResult[Environment]: ...

    @abstractmethod
    def _list_options(
        self, stage: SelectionStage
    ) -> AdapterResult[list[SelectionOption]]: ...

    @abstractmethod
    def _select(
        self, stage: SelectionStage, choice: str
    ) -> AdapterResult[SelectionChain]: ...

    @abstractmethod
    def _inspect(
        self, sections: list[InspectionSectionName] | None
    ) -> AdapterResult[dict[InspectionSectionName, InspectionSection]]: ...

    @abstractmethod
    def _validate_native(self) -> AdapterResult[NativeValidation]: ...

    @abstractmethod
    def _read_solve_state(self) -> AdapterResult[SolveState]: ...

    @abstractmethod
    def _read_solved_data(self) -> AdapterResult[SolvedData]: ...
