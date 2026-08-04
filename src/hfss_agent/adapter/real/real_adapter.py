"""RealAdapter (W-3): the PyAEDT-backed ``Adapter`` — implemented PyAEDT-free.

This module imports NO AEDT API. It receives a ``LiveSession`` seam (real impl:
``real/session.py``, the one AEDT-API file; tests: a hand-written double) and
reads the bound ``Hfss`` handle duck-typed. That keeps the whole mapping layer —
PyAEDT-attribute → contract type, the per-section ``not_readable`` degradation,
the typed ``cannot_evaluate`` gaps, frequency-unit normalisation — unit-testable
in license-free CI.

Honest limitation (do not round up): the test double mimics PyAEDT's object
shape, so it can be wrong in exactly the way our API assumptions can be wrong.
These tests verify our WIRING, not PyAEDT correctness — every operation stays
``mock-only`` in docs/pyaedt-coverage.md until live validation (Phase 5.2). The
strong, structural guarantee ("no dynamic dispatch, finite audited surface, so
no arbitrary or mutating method is reachable") is enforced by the AST tests; the
weaker "each authored call is believed read-only pending live verification" is
exactly that — weaker, and labeled so.

CHANGE-1 (ADR): ``_select`` records the choice and changes NO AEDT active-
selection state — no ``SetActiveProject`` / ``set_active_design`` call exists.
Reads are scoped by binding an app to ``(project, design)`` via the seam. The one
live call ``_select`` makes is reading ``solution_type`` (a getter) off a bound
handle when a design is chosen.
"""

from __future__ import annotations

import hashlib
import json
import platform
from datetime import datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _package_version
from typing import Any, Protocol

from hfss_agent.adapter.base import Adapter
from hfss_agent.adapter.results import (
    AdapterCannotEvaluate,
    AdapterInternalError,
    AdapterOutcome,
    AdapterResult,
)
from hfss_agent.adapter.selection import downstream_reset
from hfss_agent.adapter.watchdog import DEFAULT_TIMEOUT_SECONDS
from hfss_agent.contract import (
    ComplexSample,
    Environment,
    FreshnessEvidence,
    InspectionSection,
    NativeValidation,
    Project,
    SolutionExists,
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

# "PyAEDT gave us a shape we could not read" errors. Caught narrowly (not bare
# Exception) so a genuine bug in our own code still propagates to the watchdog as
# an internal error rather than being mislabeled a readability limitation.
_UNAVAILABLE = (AttributeError, KeyError, TypeError, IndexError, ValueError)

# Frequency units PyAEDT may report a sweep in → multiplier to Hz. SolvedData
# carries plain floats, so the sweep unit must be normalised on read.
_HZ_PER_UNIT = {"Hz": 1.0, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9, "THz": 1e12}


class LiveSession(Protocol):
    """The AEDT-touching seam ``RealAdapter`` depends on (duck-typed).

    Real implementation: ``real/session.py``. Tests inject a fake. ``application``
    returns a bound ``Hfss`` handle that ``RealAdapter`` reads duck-typed; the
    other methods are project/desktop-level reads and the file-I/O-avoiding native
    validation (see ``session.validate_native``).
    """

    def attach(self, process_id: int) -> None: ...
    def reset_bindings(self) -> None: ...
    def aedt_version(self) -> str: ...
    def pyaedt_version(self) -> str: ...
    def project_names(self) -> list[str]: ...
    def project_path(self, project: str) -> str: ...
    def design_names(self, project: str) -> list[str]: ...
    def application(self, project: str, design: str) -> Any: ...
    def validate_native(self, project: str, design: str) -> list[str]: ...


def _not_readable(limitation: str) -> InspectionSection:
    """A section PyAEDT could not read — the specific limitation named, never
    papered over (contract ``read_status='not_readable'``)."""
    return InspectionSection(
        data=None, read_status="not_readable", limitation=limitation
    )


def _parse_variation(variation_string: str) -> dict[str, str]:
    # PyAEDT variation strings look like "w='2mm' h='1.6mm'"; parse into a
    # name->value map. Shape uncertain (live-verify); unparseable input yields {}.
    values: dict[str, str] = {}
    for token in variation_string.split():
        if "=" in token:
            name, _, value = token.partition("=")
            values[name.strip()] = value.strip().strip("'\"")
    return values


def _variation_hash(values: dict[str, str]) -> str:
    # THE CANONICAL VARIATION HASH. This is its one and only implementation.
    #
    # RESOLVED (ADR-29, Step 2.5b). The comment that stood here from Step 1.2
    # flagged a cross-module coupling: System Design §2 assigned the canonical
    # hash to the W-8 snapshot module, and said this "MUST be reconciled with
    # that convention when W-8 lands so the two agree byte-for-byte". W-8 has
    # landed, and the reconciliation is that there was never a second
    # implementation to reconcile WITH — §2's assignment is what was wrong, and
    # it is being corrected.
    #
    # WHY OWNERSHIP STAYS HERE. Two constraints, either of which alone decides
    # it. W-8 imports ``contract`` ONLY (ADR-28), so it cannot reach this
    # function or any other adapter code. And the ``Variation`` must exist at
    # select / list_options time — it is a field on ``SelectionChain`` and so on
    # every ``SessionStatus`` — which is long before any snapshot is assembled;
    # a hash minted by W-8 would arrive too late for the session that has
    # already published one.
    #
    # SO W-8 RECEIVES THIS VALUE AS DATA AND COMPUTES NO HASH AT ALL. It does not
    # recompute-and-compare either, and that was decided on measurement rather
    # than taste: ``_resolve_variation`` below carries an unparseable variation
    # token through AS the hash, so a comparison would fire on legitimate data.
    #
    # CHANGING THE CANONICALIZATION RE-KEYS EVERY VARIATION IN THE PRODUCT, and
    # the three ways to do it by accident are dropping ``sort_keys``, letting
    # ``json.dumps`` use its default separators, and changing the encoding. All
    # three are pinned by golden vectors in tests/adapter/test_variation_hash.py,
    # which records six one-line-different canonicalizations producing six
    # different digests. Deterministic sort keeps it stable across insertion
    # orders.
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _resolve_variation(token: str) -> Variation:
    values = _parse_variation(token)
    if values:
        return Variation(values=values, variation_hash=_variation_hash(values))
    # Unparseable token: carry it as the hash rather than inventing values
    # (mirrors FakeAdapter._resolve_variation).
    return Variation(values={}, variation_hash=token)


class RealAdapter(Adapter):
    """PyAEDT-backed ``Adapter``. Holds the session seam + the partial selection
    chain; the ABC's template path adds the watchdog and sanitisation."""

    def __init__(
        self,
        session: LiveSession,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(timeout_seconds=timeout_seconds)
        self._session = session
        self._selection = SelectionChain()

    # --- selection helpers ----------------------------------------------------

    def _wrapper_version(self) -> str:
        try:
            return _package_version("hfss-agent")
        except PackageNotFoundError:
            return "0.0.0"

    def _scope(self) -> tuple[str, str] | AdapterCannotEvaluate | AdapterInternalError:
        """The selected (project, design), or a typed outcome when it can't bind.

        Two distinct non-bind cases, kept distinct on purpose (ADR-17 #3):
          * project and/or design simply not chosen yet -> ``cannot_evaluate``,
            a normal state the caller acts on by selecting;
          * a design present with NO project -> ``internal_error``. A
            correctly-ordered selection always sets project before design, so a
            design with no project means our own selection bookkeeping — or an
            out-of-order caller — left an incoherent scope. We refuse to bind it
            rather than mislabel it a user-actionable ``cannot_evaluate``: it is
            our bug, not the user's process dying.

        These are two separate mechanisms, not one. This guard handles only the
        design-without-project incoherence above. The different hazard of a stale
        design left under a re-selected project is prevented upstream by
        ``downstream_reset`` (which clears the design whenever the project
        changes), so that shape never reaches this method at all.
        """
        selection = self._selection
        if selection.design is not None and selection.project is None:
            return AdapterInternalError(
                detail=(
                    "incoherent selection scope: a design is bound with no "
                    "project — the adapter's selection state is inconsistent"
                )
            )
        if selection.project is None or selection.design is None:
            return AdapterCannotEvaluate(
                reason="incomplete selection",
                limitation="a project and design must be selected first",
            )
        return (selection.project.name, selection.design)

    # --- primitives -----------------------------------------------------------

    def _attach(self, process_id: int) -> AdapterResult[Environment]:
        self._session.attach(process_id)
        # Re-attach binds a NEW desktop; any Hfss handle the seam cached against a
        # prior desktop is now stale (the "stray second session handle" the
        # predecessor project was fragile on). Drop them so the next read binds
        # fresh against the process we just attached. This is CI-verified via the
        # seam double; the real clear's live effect is Phase 5.2 (pyaedt-coverage).
        self._session.reset_bindings()
        self._selection = SelectionChain(process_id=process_id)
        return Environment(
            aedt_version=self._session.aedt_version(),
            pyaedt_version=self._session.pyaedt_version(),
            python_version=platform.python_version(),
            wrapper_version=self._wrapper_version(),
        )

    def _list_options(
        self, stage: SelectionStage
    ) -> AdapterResult[list[SelectionOption]]:
        selection = self._selection
        if stage == "project":
            return [
                SelectionOption(value=name, display=name)
                for name in self._session.project_names()
            ]
        if stage == "design":
            if selection.project is None:
                return AdapterCannotEvaluate(
                    reason="incomplete selection",
                    limitation="select a project before listing designs",
                )
            return [
                SelectionOption(value=name, display=name)
                for name in self._session.design_names(selection.project.name)
            ]
        scope = self._scope()
        if isinstance(scope, AdapterOutcome):
            return scope
        app = self._session.application(*scope)
        if stage == "setup":
            return [SelectionOption(value=s, display=s) for s in app.setup_names]
        if stage == "sweep":
            if selection.setup is None:
                return AdapterCannotEvaluate(
                    reason="incomplete selection",
                    limitation="select a setup before listing sweeps",
                )
            return [
                SelectionOption(value=s, display=s)
                for s in app.get_sweeps(selection.setup)
            ]
        return self._list_variations(app)

    def _list_variations(self, app: Any) -> AdapterResult[list[SelectionOption]]:
        try:
            strings = app.available_variations.get_variation_strings()
        except _UNAVAILABLE:
            strings = None
        if not strings:
            return AdapterCannotEvaluate(
                reason="variation enumeration unavailable",
                limitation=(
                    "PyAEDT does not expose a readable variation list for this "
                    "design/setup"
                ),
            )
        return [
            SelectionOption(value=s, variation=_resolve_variation(s)) for s in strings
        ]

    def _select(
        self, stage: SelectionStage, choice: str
    ) -> AdapterResult[SelectionChain]:
        # No AEDT active-selection mutation (CHANGE-1): record the choice; reads
        # are scoped by binding an app to (project, design) at read time. The only
        # live call is reading solution_type (a getter) when a design is chosen.
        # Selecting a stage clears everything below it (downstream_reset) so the
        # cached chain never leaves a stale downstream entry for _scope to bind.
        chain = self._selection
        if stage == "project":
            path = self._session.project_path(choice)
            chain = chain.model_copy(
                update={
                    "project": Project(name=choice, path=path),
                    **downstream_reset("project"),
                }
            )
        elif stage == "design":
            chain = chain.model_copy(
                update={"design": choice, **downstream_reset("design")}
            )
            if chain.project is not None:
                app = self._session.application(chain.project.name, choice)
                chain = chain.model_copy(
                    update={"solution_type": app.solution_type}
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
                    "variation": _resolve_variation(choice),
                    **downstream_reset("variation"),
                }
            )
        self._selection = chain
        return chain

    def _inspect(
        self, sections: list[InspectionSectionName] | None
    ) -> AdapterResult[dict[InspectionSectionName, InspectionSection]]:
        scope = self._scope()
        if isinstance(scope, AdapterOutcome):
            return scope
        app = self._session.application(*scope)
        readers = {
            "variables": self._inspect_variables,
            "objects": self._inspect_objects,
            "materials": self._inspect_materials,
            "boundaries": self._inspect_boundaries,
            "excitations_ports": self._inspect_ports,
            "setups": self._inspect_setups,
            "sweeps": self._inspect_sweeps,
            "available_results": self._inspect_results,
        }
        wanted = list(readers) if sections is None else sections
        # Each reader degrades in-band to not_readable, so a partially-readable
        # design is reported section by section rather than failing whole.
        return {name: readers[name](app) for name in wanted if name in readers}

    def _inspect_variables(self, app: Any) -> InspectionSection:
        try:
            return InspectionSection(
                data=dict(app.variable_manager.variables), read_status="ok"
            )
        except _UNAVAILABLE:
            return _not_readable(
                "design variables are not exposed by PyAEDT for this design"
            )

    def _inspect_objects(self, app: Any) -> InspectionSection:
        try:
            return InspectionSection(
                data=list(app.modeler.object_names), read_status="ok"
            )
        except _UNAVAILABLE:
            return _not_readable(
                "the geometry object list is not exposed by PyAEDT for this design"
            )

    def _inspect_materials(self, app: Any) -> InspectionSection:
        try:
            detail = {
                name: {"permittivity": str(material.permittivity.value)}
                for name, material in app.materials.material_keys.items()
            }
            return InspectionSection(data=detail, read_status="ok")
        except _UNAVAILABLE:
            return _not_readable(
                "material property details (e.g. permittivity) are not exposed by "
                "PyAEDT in a readable form"
            )

    def _inspect_boundaries(self, app: Any) -> InspectionSection:
        try:
            return InspectionSection(
                data=[boundary.name for boundary in app.boundaries], read_status="ok"
            )
        except _UNAVAILABLE:
            return _not_readable(
                "boundary definitions are not exposed by PyAEDT for this design"
            )

    def _inspect_ports(self, app: Any) -> InspectionSection:
        try:
            # `excitation_names` (not `excitations`) — verified against installed
            # pyaedt 1.2.0 (tests/adapter/test_pyaedt_api_contract.py).
            return InspectionSection(
                data=list(app.excitation_names), read_status="ok"
            )
        except _UNAVAILABLE:
            return _not_readable(
                "excitations/ports are not exposed by PyAEDT for this design"
            )

    def _inspect_setups(self, app: Any) -> InspectionSection:
        try:
            return InspectionSection(data=list(app.setup_names), read_status="ok")
        except _UNAVAILABLE:
            return _not_readable(
                "analysis setups are not exposed by PyAEDT for this design"
            )

    def _inspect_sweeps(self, app: Any) -> InspectionSection:
        try:
            sweeps = {setup: list(app.get_sweeps(setup)) for setup in app.setup_names}
            return InspectionSection(data=sweeps, read_status="ok")
        except _UNAVAILABLE:
            return _not_readable(
                "frequency sweeps are not exposed by PyAEDT for this design"
            )

    def _inspect_results(self, app: Any) -> InspectionSection:
        try:
            return InspectionSection(
                data=list(app.post.all_report_names), read_status="ok"
            )
        except _UNAVAILABLE:
            return _not_readable(
                "available result reports are not exposed by PyAEDT for this design"
            )

    def _validate_native(self) -> AdapterResult[NativeValidation]:
        scope = self._scope()
        if isinstance(scope, AdapterOutcome):
            return scope
        # WHY THIS GUARD EXISTS, and exactly how far it reaches — both stated,
        # because the narrowness is deliberate and must not be read as a claim
        # about the rest of this file.
        #
        # Without it, a ValidateDesign/GetMessages that is missing or raises
        # escapes to the watchdog's broad handler and comes back as
        # AdapterInternalError — a SessionFault, which marks the session SUSPECT
        # and tells the user the agent hit an internal error in its own
        # bookkeeping. That is an honesty inversion: an unavailable HFSS
        # validator would be reported as our fault rather than as what it is.
        # AdapterCannotEvaluate states the real thing — PyAEDT/HFSS could not
        # run or return the native validation — and leaves the session healthy.
        #
        # DELIBERATELY NARROW: this path only. Unguarded live-seam calls of the
        # same kind remain in _attach (the desktop-level version reads),
        # _list_options, _select, _read_solve_state, _find_setup, and all of
        # _read_solved_data; _inspect's own application() bind is unguarded too,
        # and only its per-section readers are guarded. Their being unguarded is
        # NOT a statement that they are known safe — it says only that this step
        # did not touch them. Those seven are accurate as of this change and are
        # not maintained here: the authoritative list lives with the Phase 6.1
        # sweep, so trust that one over this if the two ever disagree. The
        # adapter-wide guard policy is Phase 6.1 work and is tracked as a
        # standing blocker; widening it here would rework an earlier step from
        # inside a branch scoped to this one.
        #
        # ONE ASYMMETRY THIS CREATES, named rather than left to be discovered:
        # the two odesign calls live in real/session.py, which cannot import
        # AdapterCannotEvaluate, so the guard has to sit here — around the whole
        # seam call. It therefore also covers the Hfss(...) bind that
        # LiveSession.validate_native performs internally. That SAME bind
        # failing under _inspect still surfaces as AdapterInternalError. One
        # underlying failure, two different outcomes, decided by which path
        # reached it. Reconciling that is part of the Phase 6.1 sweep, not of
        # this guard.
        try:
            raw_output = self._session.validate_native(*scope)
        except _UNAVAILABLE:
            return AdapterCannotEvaluate(
                reason="native validation unavailable",
                limitation=(
                    "HFSS's own design validator could not be run, or its "
                    "messages could not be read back, through PyAEDT for this "
                    "design. This names a limitation of what PyAEDT could do "
                    "here: it is not a statement about the design, and it is "
                    "not the same as a validator that ran and reported nothing."
                ),
            )
        return NativeValidation(raw_output=raw_output)

    def _read_solve_state(self) -> AdapterResult[SolveState]:
        scope = self._scope()
        if isinstance(scope, AdapterOutcome):
            return scope
        selection = self._selection
        if (
            selection.setup is None
            or selection.sweep is None
            or selection.variation is None
        ):
            return AdapterCannotEvaluate(
                reason="incomplete selection",
                limitation=(
                    "a setup, sweep, and variation must all be selected before "
                    "reading solve state"
                ),
            )
        app = self._session.application(*scope)
        setup = self._find_setup(app, selection.setup)
        if setup is None:
            return AdapterCannotEvaluate(
                reason="setup not found",
                limitation=f"setup {selection.setup!r} is not present in the design",
            )

        solution_exists = [
            SolutionExists(
                setup=selection.setup,
                sweep=selection.sweep,
                variation=selection.variation,
                exists=bool(setup.is_solved),
            )
        ]

        # Convergence history / status: approved cannot_evaluate gap — we do NOT
        # reach past what PyAEDT hands back, and never fabricate empty lists or a
        # guessed status. The specific limitation is named, not a generic message.
        convergence = self._read_convergence(setup)
        if convergence is None:
            return AdapterCannotEvaluate(
                reason="convergence history unavailable",
                limitation=(
                    "per-pass convergence history and convergence status are not "
                    "exposed by PyAEDT for this setup type"
                ),
            )
        passes, deltas, status, messages = convergence

        # Solve-completion timestamp: approved cannot_evaluate gap.
        timestamp = self._read_solve_timestamp(setup)
        if timestamp is None:
            return AdapterCannotEvaluate(
                reason="solve timestamp unavailable",
                limitation=(
                    "solve-completion timestamps are not exposed by PyAEDT for "
                    "this setup/sweep"
                ),
            )

        return SolveState(
            solution_exists=solution_exists,
            adaptive_pass_history=passes,
            delta_s_progression=deltas,
            convergence_status=status,
            solve_timestamps={f"{selection.setup}:{selection.sweep}": timestamp},
            solver_messages=messages,
            # Freshness: approved default — PyAEDT exposes no reliable
            # design-modified-since-solve signal, so we report determinable=False
            # with empty signals rather than guess (ADR-4). The freshness gate
            # then returns insufficient_evidence honestly.
            freshness_evidence=FreshnessEvidence(
                available_signals={}, determinable=False
            ),
        )

    @staticmethod
    def _find_setup(app: Any, name: str) -> Any | None:
        for setup in app.setups:
            if str(setup.name) == name:
                return setup
        return None

    @staticmethod
    def _read_convergence(
        setup: Any,
    ) -> tuple[list[Any], list[float], str, list[str]] | None:
        # Assumed PyAEDT convergence shape (mock-only; live-verify Phase 5.2):
        # get_convergence_data() -> mapping with per-pass rows, a delta-S series,
        # a converged flag, and optional solver messages, or a falsy value when
        # unavailable.
        try:
            data = setup.get_convergence_data()
            if not data:
                return None
            passes = list(data["passes"])
            deltas = [float(value) for value in data["delta_s"]]
            status = "converged" if data["converged"] else "stopped"
            messages = [str(message) for message in data.get("messages", [])]
        except _UNAVAILABLE:
            return None
        return passes, deltas, status, messages

    @staticmethod
    def _read_solve_timestamp(setup: Any) -> datetime | None:
        # Assumed shape (mock-only; live-verify): get_profile() -> a datetime of
        # solve completion, or a falsy value when unavailable.
        try:
            profile = setup.get_profile()
        except _UNAVAILABLE:
            return None
        return profile if isinstance(profile, datetime) else None

    def _read_solved_data(self) -> AdapterResult[SolvedData]:
        scope = self._scope()
        if isinstance(scope, AdapterOutcome):
            return scope
        selection = self._selection
        if selection.setup is None or selection.sweep is None:
            return AdapterCannotEvaluate(
                reason="incomplete selection",
                limitation=(
                    "a setup and sweep must be selected before reading solved "
                    "S-parameters"
                ),
            )
        app = self._session.application(*scope)
        # `excitation_names` verified against installed pyaedt 1.2.0.
        ports = list(app.excitation_names)
        expressions = [f"S({a},{b})" for a in ports for b in ports]
        setup_sweep = f"{selection.setup} : {selection.sweep}"
        variations = selection.variation.values if selection.variation else None
        data = app.post.get_solution_data(
            expressions=expressions,
            setup_sweep_name=setup_sweep,
            variations=variations,
        )
        if data is None:
            return AdapterCannotEvaluate(
                reason="no solved data",
                limitation=(
                    f"no solved S-parameter data is available for {setup_sweep}"
                ),
            )
        factor = _HZ_PER_UNIT.get(str(data.primary_sweep_unit))
        if factor is None:
            return AdapterCannotEvaluate(
                reason="unknown frequency unit",
                limitation=(
                    f"frequency sweep unit {data.primary_sweep_unit!r} is not "
                    "recognised for Hz normalisation"
                ),
            )
        frequencies = [float(value) * factor for value in data.primary_sweep_values]
        s_parameters = {
            expression: [
                ComplexSample(real=float(real), imag=float(imag))
                for real, imag in zip(
                    data.data_real(expression),
                    data.data_imag(expression),
                    strict=True,
                )
            ]
            for expression in data.expressions
        }
        return SolvedData(frequencies=frequencies, s_parameters=s_parameters)
