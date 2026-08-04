"""A snapshot assembled from the objects W-5 and W-6 ACTUALLY return.

THE ONE FILE IN THIS SUITE THAT HOLDS A BROKER, and the exception is deliberate.
``snapshot_helpers`` opens by stating that no ``FakeAdapter``, ``Session`` or
``Broker`` appears anywhere in the W-8 suite, because W-8 dispatches through
nothing and imports only ``contract`` — so the honest unit test of it is a test
over constructed data. That reasoning is correct and unchanged. It just does not
cover ONE question, which is the question this file exists for:

    every other test in this suite hands ``assemble_snapshot`` an object the TEST
    built. Whether W-5 and W-6 actually produce objects of that shape was, until
    now, true by reading and by nothing else.

That is a SEAM assumption, not a W-8 property, and a seam can only be tested from
both sides. The narrowings here have a hard dependency on it: ``_inspection``
REFUSES a subset read, so if ``inspect_design`` ever returns fewer than eight
sections by default, W-8 refuses every snapshot in the product — and no
constructed-input test would notice, because it would keep building all eight
itself.

WHAT IS REAL HERE AND WHAT IS NOT. Four of the six inputs are genuine upstream
outputs: ``inspect_design(broker)``, ``validate_native(broker)``, and the
``SelectionChain`` and ``Environment`` read off the same broker. The two solve
fields are constructed absence arms, and that is not a shortcut — their refusal
type is ``AdapterCannotEvaluate``, which lives in ``hfss_agent.adapter``, and
mapping it onto the contract's ``SolveDataUnavailable`` is explicitly the
CALLER's job (see ``assemble_snapshot``'s docstring). No W-layer produces that
mapping today, so there is no real output to take.

THE BROKER SETUP BELOW IS A DELIBERATE ~30-LINE DUPLICATE of
``tests/inspect/inspect_helpers.scoped_broker``, and it must stay one. Promoting
that helper to a shared location is a TESTS-INFRASTRUCTURE decision: it affects
every suite, it needs a home that pytest's prepend import mode can actually reach
from all of them (there are no ``__init__.py`` files under ``tests/``, so sibling
suite directories are not on each other's import path), and it should be made
once, deliberately, when the server layer needs to compose several modules in one
test. Making it as a side effect of a snapshot step is how infrastructure
decisions get made by accident — the promotion happens, nobody reviews it as a
promotion, and the next suite inherits a shape nobody chose. Thirty duplicated
lines are the cheaper mistake, and they are visible.

NAMED FOR THE PRODUCERS, NOT THE MECHANISM. What could break this file is a
change on W-5's or W-6's side, so it is named for their outputs rather than for
the broker it happens to need to obtain them.
"""

from __future__ import annotations

from hfss_agent.adapter.fake import FakeAdapter, Scenario
from hfss_agent.broker import (
    Broker,
    CapabilityRegistry,
    RefuseAllConfirmer,
    session_routed_specs,
)
from hfss_agent.contract import (
    AuditRecord,
    DesignSnapshot,
    Environment,
    Inspection,
    NativeValidation,
    Selection,
    SolveDataUnavailable,
)
from hfss_agent.contract.tool_io import (
    InspectionResult,
    NativeValidationBlock,
    SelectionChain,
    SessionStatus,
)
from hfss_agent.inspect import inspect_design
from hfss_agent.session import Session
from hfss_agent.snapshot import SnapshotAssemblyError, assemble_snapshot
from hfss_agent.validate_native import validate_native

# The default ``Scenario``'s own values, so a drift in the fake surfaces as a
# named assertion here rather than as a puzzling refusal.
DEFAULT_PID = 1234
PROJECT = "patch_antenna"
DESIGN = "HFSSDesign1"


class _RecordingSink:
    """In-memory ``AuditSink``: appends to a list, never touches a file. Four
    lines, re-declared for the reason the module docstring gives."""

    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


def _selected_broker() -> Broker:
    """A broker over the licence-free ``FakeAdapter`` with all five stages chosen.

    The attach/select drive calls the session DIRECTLY rather than dispatching,
    so the audit sink holds only what the test's own W-5/W-6 calls produced.
    ``solution_type`` is not selected: the adapter fills it in at the design
    stage, which is exactly the kind of upstream detail this file exists to stop
    guessing about.
    """
    fake = FakeAdapter()
    session = Session(fake)
    session.attach(DEFAULT_PID)
    session.select("project", PROJECT)
    session.select("design", DESIGN)
    session.select("setup", "Setup1")
    session.select("sweep", "Sweep1")
    # Taken from the scenario rather than transcribed: the variation stage is
    # keyed by the hash the adapter minted, and hardcoding a digest here would
    # duplicate the pin that ``tests/adapter/test_variation_hash.py`` owns.
    session.select("variation", Scenario().options["variation"][0].value)
    return Broker(
        session=session,
        registry=CapabilityRegistry(session_routed_specs(session)),
        audit_sink=_RecordingSink(),
        confirmer=RefuseAllConfirmer(),
    )


def _real_upstream_outputs() -> tuple[
    InspectionResult, NativeValidationBlock, SelectionChain, Environment
]:
    """The four genuine outputs, each checked for SHAPE before composition.

    THE CHECKS ARE HERE, NOT LEFT TO ``assemble_snapshot``, and that is the whole
    design of this file. W-8 already refuses a subset inspection with a clear
    message — but that message says "the inspection carries 7 of 8 sections", and
    a maintainer reading it would go looking in the snapshot module, which would
    be the one place that had not changed. Every assertion below names the
    PRODUCING side, so a failure points at the module that moved.

    WHICH LAYER THE EIGHT-SECTION GUARD WATCHES, measured by mutation rather than
    assumed. Deleting a section from the fake adapter's canned data does NOT
    reach it: W-5 synthesizes an explicit ``not_readable`` entry for any section
    the adapter omitted, so its output stays eight-wide and the snapshot stays
    assemblable — which is W-5 behaving correctly. What DOES fire it is a change
    to W-5 itself; dropping a name from ``inspect.assembler._CANONICAL_ORDER``
    produces "missing ['boundaries']" here. That is the right layer: an adapter
    that cannot read a section is an expected, already-handled condition, and a
    W-5 that stops reporting one is the seam break.
    """
    broker = _selected_broker()

    inspection = inspect_design(broker)
    assert isinstance(inspection, InspectionResult), (
        f"W-5 CHANGED: inspect_design returned {type(inspection).__name__}, not an "
        "InspectionResult. W-8 accepts the refusal arms deliberately, so this is "
        "not a W-8 defect — a fully-selected session over the default fake "
        "scenario refused a read it used to complete."
    )
    missing = set(Inspection.model_fields) - set(inspection.sections)
    assert not missing, (
        f"W-5 CHANGED: inspect_design's default read no longer returns all eight "
        f"sections; it is missing {sorted(missing)}. W-8 REFUSES a subset read by "
        "design (Inspection has no absence arm), so this breaks every snapshot in "
        "the product, not just this test. Fix W-5 or change the contract — do not "
        "relax the narrowing."
    )

    native = validate_native(broker)
    assert isinstance(native, NativeValidationBlock), (
        f"W-6 CHANGED: validate_native returned {type(native).__name__}, not a "
        "NativeValidationBlock, for a session that is attached and fully selected."
    )
    assert isinstance(native.validation, NativeValidation), (
        f"W-6 CHANGED: NativeValidationBlock.validation is now a "
        f"{type(native.validation).__name__}. W-8 unwraps this field and puts it "
        "straight on the snapshot, so its type is load-bearing across the seam."
    )

    status = broker.dispatch("get_session_status")
    assert isinstance(status, SessionStatus), (
        f"THE SESSION LAYER CHANGED: get_session_status returned "
        f"{type(status).__name__}, not a SessionStatus."
    )
    chain = status.selection
    absent = [
        stage for stage in Selection.model_fields if getattr(chain, stage) is None
    ]
    assert not absent, (
        f"THE SESSION/ADAPTER SIDE CHANGED: a chain with all five selectable "
        f"stages chosen still has no {absent}. W-8 requires all seven and refuses "
        "rather than inventing one; 'solution_type' in this list means the "
        "adapter stopped filling it in at the design stage."
    )

    return inspection, native, chain, broker.require_environment()


# --- the seam ------------------------------------------------------------------


def test_real_w5_and_w6_outputs_assemble_into_a_snapshot() -> None:
    """THE CLAUSE THIS FILE EXISTS FOR: the objects the upstream steps really
    produce compose, without any of W-8's four refusals firing."""
    inspection, native, chain, environment = _real_upstream_outputs()

    snapshot = assemble_snapshot(
        inspection=inspection,
        native_validation=native,
        solve_state=SolveDataUnavailable(
            reason="not_exposed_by_pyaedt",
            limitation="per-pass convergence history and convergence status are "
            "not exposed by PyAEDT for this setup type",
        ),
        solved_data=SolveDataUnavailable(
            reason="no_solution",
            limitation="no solved S-parameter data is available for Setup1 : Sweep1",
        ),
        selection=chain,
        environment=environment,
    )

    assert isinstance(snapshot, DesignSnapshot)
    assert isinstance(snapshot.inspection, Inspection)
    assert isinstance(snapshot.selection, Selection)
    assert isinstance(snapshot.native_validation, NativeValidation)


def test_the_real_sections_cross_as_the_same_objects() -> None:
    """W-5's own ``InspectionSection``s reach the artifact unrebuilt, including
    the ``read_status`` and ``limitation`` the adapter set on each."""
    inspection, native, chain, environment = _real_upstream_outputs()
    snapshot = assemble_snapshot(
        inspection=inspection,
        native_validation=native,
        solve_state=SolveDataUnavailable(reason="no_solution", limitation="x"),
        solved_data=SolveDataUnavailable(reason="no_solution", limitation="x"),
        selection=chain,
        environment=environment,
    )
    for name in Inspection.model_fields:
        assert getattr(snapshot.inspection, name) is inspection.sections[name]
    assert snapshot.native_validation is native.validation


def test_the_real_chain_loses_its_path_and_keeps_everything_else() -> None:
    """The path drop, executed on a chain the SESSION built rather than one the
    test did — the shape the decision was actually written about."""
    inspection, native, chain, environment = _real_upstream_outputs()
    assert chain.project is not None
    assert chain.project.path, "the fake scenario stopped supplying a project path"

    snapshot = assemble_snapshot(
        inspection=inspection,
        native_validation=native,
        solve_state=SolveDataUnavailable(reason="no_solution", limitation="x"),
        solved_data=SolveDataUnavailable(reason="no_solution", limitation="x"),
        selection=chain,
        environment=environment,
    )

    assert snapshot.selection.project == PROJECT
    assert chain.project.path not in str(snapshot.model_dump(mode="json")["selection"])
    # Everything else crossed unchanged, so the drop is a drop and not a reset.
    assert snapshot.selection.design == chain.design
    assert snapshot.selection.setup == chain.setup
    assert snapshot.selection.sweep == chain.sweep
    assert snapshot.selection.solution_type == chain.solution_type
    assert snapshot.selection.variation is chain.variation


def test_the_real_environment_is_the_attached_sessions_own() -> None:
    """``Environment`` crosses as the object the broker read through to the
    session, not a copy this suite built."""
    inspection, native, chain, environment = _real_upstream_outputs()
    snapshot = assemble_snapshot(
        inspection=inspection,
        native_validation=native,
        solve_state=SolveDataUnavailable(reason="no_solution", limitation="x"),
        solved_data=SolveDataUnavailable(reason="no_solution", limitation="x"),
        selection=chain,
        environment=environment,
    )
    assert snapshot.environment is environment
    assert snapshot.environment.aedt_version


def test_a_real_snapshot_round_trips_through_json() -> None:
    """The artifact built from real upstream outputs survives the seam it was
    built to cross — asserted here too, because the constructed-input round trip
    can only prove it for shapes this suite invents."""
    inspection, native, chain, environment = _real_upstream_outputs()
    snapshot = assemble_snapshot(
        inspection=inspection,
        native_validation=native,
        solve_state=SolveDataUnavailable(reason="no_solution", limitation="x"),
        solved_data=SolveDataUnavailable(reason="no_solution", limitation="x"),
        selection=chain,
        environment=environment,
    )
    reloaded = DesignSnapshot.model_validate_json(snapshot.model_dump_json())
    assert reloaded == snapshot


def test_a_subset_read_from_the_real_w5_still_refuses() -> None:
    """The dependency stated in the module docstring, exercised rather than
    argued: a REAL three-section ``inspect_design`` call produces a real
    ``InspectionResult``, and W-8 refuses it.

    This is what makes the eight-section assertion above load-bearing — the
    narrowing is not theoretical, and if W-5's default ever shrinks, this is the
    behaviour the whole product gets.
    """
    broker = _selected_broker()
    subset = inspect_design(broker, ["variables", "objects", "materials"])
    assert isinstance(subset, InspectionResult)
    assert len(subset.sections) == 3

    try:
        assemble_snapshot(
            inspection=subset,
            native_validation=validate_native(broker),  # type: ignore[arg-type]
            solve_state=SolveDataUnavailable(reason="no_solution", limitation="x"),
            solved_data=SolveDataUnavailable(reason="no_solution", limitation="x"),
            selection=broker.dispatch("get_session_status").selection,  # type: ignore[union-attr]
            environment=broker.require_environment(),
        )
    except SnapshotAssemblyError as error:
        assert "carries 3 of 8 sections" in str(error)
    else:  # pragma: no cover - the assertion below is the failure report
        raise AssertionError(
            "W-8 accepted a three-section inspection; Inspection has no absence "
            "arm, so the missing five would have to be invented"
        )
