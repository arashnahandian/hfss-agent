"""FakeAdapter (W-3): the licence-free Adapter used by all public CI.

Implements the ``Adapter`` primitives with configurable canned data (a
``Scenario``) and independent per-operation fault injection. Holds NO ``pyaedt`` —
that is the whole point: every downstream module (session, inspect, gating,
metrics, …) tests against it. It keeps minimal internal selection state so a
realistic ``attach -> select xN -> inspect`` drive works.

Fault/hang/raise injection happens in the primitives, so it runs INSIDE the
watchdog (a hang is abandoned; a raise is caught) and BEFORE sanitization (a
fault outcome's strings are sanitized too, on the public path).
"""

from __future__ import annotations

import threading

from hfss_agent.adapter.base import Adapter
from hfss_agent.adapter.fake.scenario import OpBehavior, Scenario
from hfss_agent.adapter.results import AdapterOutcome, AdapterResult
from hfss_agent.adapter.selection import downstream_reset
from hfss_agent.adapter.watchdog import DEFAULT_TIMEOUT_SECONDS
from hfss_agent.contract import (
    Environment,
    InspectionSection,
    NativeValidation,
    Project,
    SolvedData,
    SolveState,
    Variation,
)
from hfss_agent.contract.tool_io import (
    InspectionSectionName,
    SelectionChain,
    SelectionOption,
    SelectionStage,
)


class FakeAdapter(Adapter):
    """Scriptable, licence-free ``Adapter`` implementation."""

    def __init__(
        self,
        scenario: Scenario | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(timeout_seconds=timeout_seconds)
        self._scenario = scenario if scenario is not None else Scenario()
        self._selection = SelectionChain()
        # A simulated hang parks a worker thread on this event; close() releases
        # any parked threads so a test suite leaks none.
        self._hang_release = threading.Event()
        # Calls made so far per op — indexes into a scripted behavior_sequence so
        # "fault on call 1, recover on call 2" resolves per call.
        self._call_counts: dict[str, int] = {}

    def close(self) -> None:
        """Release any worker threads parked in a simulated hang (test hygiene)."""
        self._hang_release.set()

    # --- per-operation injection dispatch -------------------------------------

    def _injected(self, op: str) -> AdapterOutcome | None:
        """Return an injected outcome for ``op``, or None to fall through to data.

        Raises the scripted exception (to exercise the watchdog's catch-all) and
        blocks on a hang (to exercise the watchdog's timeout) as side effects.
        The behavior governing this call comes from the scripted per-call
        sequence if one is present and unexhausted, otherwise the static per-op
        override; either way the per-op call index advances by one.
        """
        index = self._call_counts.get(op, 0)
        self._call_counts[op] = index + 1
        behavior = self._behavior_for(op, index)
        if behavior is None:
            return None
        if behavior.raises is not None:
            raise behavior.raises
        if behavior.hang:
            # No real sleep: wait on an event the test never sets, so the watchdog
            # abandons us. Only returns if close() releases the thread.
            self._hang_release.wait()
            return None
        return behavior.fault

    def _behavior_for(self, op: str, index: int) -> OpBehavior | None:
        """The behavior for the ``index``-th call to ``op``: a scripted sequence
        entry while one remains, else the static per-op override (else None)."""
        sequence = self._scenario.behavior_sequence.get(op)
        if sequence is not None and index < len(sequence):
            return sequence[index]
        return self._scenario.behavior.get(op)

    def _resolve_variation(self, choice: str) -> Variation:
        for option in self._scenario.options.get("variation", []):
            if option.value == choice and option.variation is not None:
                return option.variation
        # Unknown hash: carry it as-is rather than inventing values.
        return Variation(values={}, variation_hash=choice)

    # --- primitives -----------------------------------------------------------

    def _attach(self, process_id: int) -> AdapterResult[Environment]:
        injected = self._injected("attach")
        if injected is not None:
            return injected
        self._selection = SelectionChain(process_id=process_id)
        return self._scenario.environment

    def _list_options(
        self, stage: SelectionStage
    ) -> AdapterResult[list[SelectionOption]]:
        injected = self._injected("list_options")
        if injected is not None:
            return injected
        return list(self._scenario.options.get(stage, []))

    def _select(
        self, stage: SelectionStage, choice: str
    ) -> AdapterResult[SelectionChain]:
        injected = self._injected("select")
        if injected is not None:
            return injected
        # Selecting a stage clears everything below it (downstream_reset), so the
        # cached chain never carries a stale downstream entry after a re-select.
        chain = self._selection
        if stage == "project":
            chain = chain.model_copy(
                update={
                    "project": Project(name=choice, path=self._scenario.project_path),
                    **downstream_reset("project"),
                }
            )
        elif stage == "design":
            # Selecting a design also reveals its solution type (read from HFSS).
            chain = chain.model_copy(
                update={
                    "design": choice,
                    "solution_type": self._scenario.solution_type,
                    **downstream_reset("design"),
                }
            )
        elif stage == "setup":
            chain = chain.model_copy(
                update={"setup": choice, **downstream_reset("setup")}
            )
        elif stage == "sweep":
            chain = chain.model_copy(
                update={"sweep": choice, **downstream_reset("sweep")}
            )
        elif stage == "variation":
            chain = chain.model_copy(
                update={
                    "variation": self._resolve_variation(choice),
                    **downstream_reset("variation"),
                }
            )
        self._selection = chain
        return chain

    def _inspect(
        self, sections: list[InspectionSectionName] | None
    ) -> AdapterResult[dict[InspectionSectionName, InspectionSection]]:
        injected = self._injected("inspect")
        if injected is not None:
            return injected
        available = self._scenario.inspection
        if sections is None:
            return dict(available)
        return {name: available[name] for name in sections if name in available}

    def _validate_native(self) -> AdapterResult[NativeValidation]:
        injected = self._injected("validate_native")
        if injected is not None:
            return injected
        return self._scenario.native_validation

    def _read_solve_state(self) -> AdapterResult[SolveState]:
        injected = self._injected("read_solve_state")
        if injected is not None:
            return injected
        return self._scenario.solve_state

    def _read_solved_data(self) -> AdapterResult[SolvedData]:
        injected = self._injected("read_solved_data")
        if injected is not None:
            return injected
        return self._scenario.solved_data
