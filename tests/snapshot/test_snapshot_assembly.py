"""W-8 assembly: ``assemble_snapshot`` composes, narrows, or refuses.

The suite is organised around the four narrowings and the three refusal reasons,
because those are what W-8 actually does — everything else it touches is passed
through untouched, and the tests that matter are the ones asserting that a value
crossed unchanged or did not cross at all.

THE PATH DROP HAS ITS OWN FILE (``test_path_is_dropped.py``). ADR-28's decision
that the project's filesystem path never reaches the engine was, until this step,
a decision no code executed; ``_selection`` is the first code that does. It is
separated so that deleting the assertion deletes a file rather than a line in a
long suite.

NAMED ``test_snapshot_assembly.py``, NOT ``test_assembly.py``, and the reason is
worth one line because the failure it avoids is loud but easy to mis-diagnose.
There are no ``__init__.py`` files under ``tests/``, so pytest's prepend import
mode requires every test module's BASENAME to be unique across the whole suite —
``tests/inspect/test_assembly.py`` already holds that name, and a second one
makes collection fail with an "import file mismatch" error for the whole run
while each directory still passes when run alone. ``test_metrics_assembly.py``
and ``test_native_assembly.py`` are named for the same reason; this file follows
them.
"""

from __future__ import annotations

import ast
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from snapshot_helpers import (
    ALL_SECTIONS,
    ALL_STAGES,
    DESIGN,
    PROJECT_NAME,
    chain,
    inputs,
    inspection_result,
    native_block,
    unavailable,
    variation,
)

from hfss_agent.contract import (
    CONTRACT_VERSION,
    DesignSnapshot,
    Inspection,
    IntentObject,
    NativeValidation,
    NativeValidationUnavailable,
    Selection,
    SolveDataUnavailable,
    SolvedData,
)
from hfss_agent.contract.tool_io import (
    CannotEvaluate,
    SelectionChain,
    SelectionRefused,
)
from hfss_agent.snapshot import SnapshotAssemblyError, assemble_snapshot
from hfss_agent.snapshot.assembler import _SNAPSHOT_ID_PREFIX

# --- the refusal arms, built once ---------------------------------------------


def _cannot_evaluate() -> CannotEvaluate:
    return CannotEvaluate(
        reason="native validation unavailable",
        limitation="HFSS's own design validator could not be run",
        template_text="cannot evaluate",
    )


def _selection_refused() -> SelectionRefused:
    return SelectionRefused(
        outcome="refused_incomplete_selection",
        reason="a project and design must be selected first",
        limitation="select a project, then a design, then retry",
        template_text="refused",
    )


# --- 1. the happy path --------------------------------------------------------


def test_a_complete_input_set_assembles() -> None:
    snapshot = assemble_snapshot(**inputs())  # type: ignore[arg-type]

    assert isinstance(snapshot, DesignSnapshot)
    assert isinstance(snapshot.selection, Selection)
    assert isinstance(snapshot.inspection, Inspection)
    assert isinstance(snapshot.native_validation, NativeValidation)
    assert isinstance(snapshot.solved_data, SolvedData)
    assert isinstance(snapshot.solve_state, SolveDataUnavailable)
    assert snapshot.intent is None


def test_the_intent_is_carried_when_one_is_supplied() -> None:
    """``intent`` is the one optional field: a snapshot is valid with or without
    a design intent, and ``None`` is an honest value rather than a gap."""
    intent = IntentObject(
        target_frequency_hz=2.4e9, threshold_type="s11", threshold_value=-10.0
    )
    snapshot = assemble_snapshot(**inputs(intent=intent))  # type: ignore[arg-type]
    assert snapshot.intent == intent


def test_contract_version_is_the_imported_constant_not_a_literal() -> None:
    """Asserted against the IMPORTED constant, never against its current value.

    A test spelling ``"snapshot-3.0.0"`` here would pass whether the assembler
    imported the constant or hardcoded the same string, so it could not
    distinguish the two — and the whole point is that the value lives in one
    place. ``tests/schemas/test_schema_instantiation.py`` owns the pin on the
    literal itself.
    """
    snapshot = assemble_snapshot(**inputs())  # type: ignore[arg-type]
    assert snapshot.contract_version == CONTRACT_VERSION


# --- 2. the refusal arms (narrowing d) ----------------------------------------


@pytest.mark.parametrize("field", ["inspection", "native_validation"])
@pytest.mark.parametrize(
    ("arm_name", "arm_factory"),
    [("CannotEvaluate", _cannot_evaluate), ("SelectionRefused", _selection_refused)],
)
def test_a_refusal_arm_on_either_union_input_refuses_the_whole_snapshot(
    field: str, arm_name: str, arm_factory: object
) -> None:
    """ADR-28 decision 8, applied to both union-typed inputs.

    "``SelectionRefused`` therefore means 'no snapshot,' not 'a snapshot with an
    absence arm.'" The same holds for ``CannotEvaluate``: neither field has an
    arm that could carry "the upstream step declined", and inventing one would
    let a refusal render as a completed capture.

    Parametrised over BOTH arms and BOTH fields — four cases — because the arms
    are different types reached by different gates, and a branch that handled one
    and fell through on the other would be invisible to a single-case test.
    """
    with pytest.raises(SnapshotAssemblyError) as caught:
        assemble_snapshot(**inputs(**{field: arm_factory()}))  # type: ignore[arg-type,operator]

    message = str(caught.value)
    assert "a refusal arm was supplied" in message
    assert field in message
    assert arm_name in message


def test_the_refusal_message_names_the_tag_so_the_four_cases_are_distinguishable() -> (
    None
):
    """``outcome`` is a closed ``Literal`` on both refusal types, so interpolating
    it carries no text from HFSS while still telling the four cases apart."""
    with pytest.raises(SnapshotAssemblyError) as caught:
        assemble_snapshot(**inputs(inspection=_selection_refused()))  # type: ignore[arg-type]
    assert "'refused_incomplete_selection'" in str(caught.value)

    with pytest.raises(SnapshotAssemblyError) as caught:
        assemble_snapshot(**inputs(inspection=_cannot_evaluate()))  # type: ignore[arg-type]
    assert "'cannot_evaluate'" in str(caught.value)


def test_no_refusal_message_carries_the_arms_untrusted_strings() -> None:
    """An exception message is a line-oriented renderer, and these arms carry
    ``reason``/``limitation``/``template_text`` strings that can interpolate
    values read from HFSS.

    This follows W-5's precedent at its own provenance-failure site: with an
    untrusted value in hand, name the FIELD and not the value. Asserted with a
    planted marker rather than by reading the assembler, so a future edit that
    starts interpolating the refusal's prose fails here.
    """
    planted = "MARKER-e8f1-untrusted-hfss-text"
    refusal = CannotEvaluate(
        reason=planted, limitation=planted, template_text=planted
    )
    with pytest.raises(SnapshotAssemblyError) as caught:
        assemble_snapshot(**inputs(native_validation=refusal))  # type: ignore[arg-type]
    assert planted not in str(caught.value)


# --- 3. the seven-stage narrowing (narrowing a, completeness half) ------------


@pytest.mark.parametrize("stage", ALL_STAGES)
def test_an_incomplete_chain_refuses_on_every_stage(stage: str) -> None:
    """All seven, one at a time.

    ``SelectionChain`` declares every stage optional because it is built stage by
    stage and reset downstream on any change; ``Selection`` requires all seven.
    Parametrised rather than spot-checked because the narrowing is a loop, and a
    loop that skipped one stage would pass any test that only removed a different
    one.
    """
    with pytest.raises(SnapshotAssemblyError) as caught:
        assemble_snapshot(**inputs(selection=chain(**{stage: None})))  # type: ignore[arg-type]

    message = str(caught.value)
    assert "the selection chain does not name a" in message
    assert stage in message


def test_the_stage_list_matches_the_two_contract_types() -> None:
    """The assembler derives its seven stages from ``Selection.model_fields`` and
    reads them off ``SelectionChain`` with ``getattr``, so the two field-name sets
    must stay equal or the loop silently stops checking a stage.

    Asserted against a list written out independently in the helpers, so a
    contract change surfaces here rather than as an ``AttributeError`` at
    assembly time.
    """
    assert set(Selection.model_fields) == set(ALL_STAGES)
    assert set(SelectionChain.model_fields) == set(ALL_STAGES)


def test_an_empty_chain_names_every_missing_stage_at_once() -> None:
    """A caller who supplied nothing gets one message listing all seven, not
    seven rounds of fixing one stage at a time."""
    with pytest.raises(SnapshotAssemblyError) as caught:
        assemble_snapshot(**inputs(selection=SelectionChain()))  # type: ignore[arg-type]
    message = str(caught.value)
    for stage in ALL_STAGES:
        assert stage in message


# --- 4. the subset-inspection narrowing (narrowing b) ------------------------


def test_a_subset_inspection_refuses() -> None:
    """THE THIRD RAISE REASON. ``Inspection`` requires all eight sections and has
    no absence arm (ADR-28), so a seven-section read-out cannot be completed
    without padding it with a section nobody looked at."""
    with pytest.raises(SnapshotAssemblyError) as caught:
        assemble_snapshot(
            **inputs(inspection=inspection_result(ALL_SECTIONS[:7]))  # type: ignore[arg-type]
        )
    message = str(caught.value)
    assert "carries 7 of 8 sections" in message
    assert ALL_SECTIONS[7] in message


@pytest.mark.parametrize("dropped", ALL_SECTIONS)
def test_every_section_is_individually_required(dropped: str) -> None:
    """One at a time, for the reason the stage test is parametrised: the check is
    a loop over a derived tuple, and a loop that skipped one section would pass a
    test that only ever removed a different one."""
    kept = tuple(name for name in ALL_SECTIONS if name != dropped)
    with pytest.raises(SnapshotAssemblyError) as caught:
        assemble_snapshot(**inputs(inspection=inspection_result(kept)))  # type: ignore[arg-type]
    assert dropped in str(caught.value)


def test_the_section_list_matches_the_contract_type() -> None:
    assert set(Inspection.model_fields) == set(ALL_SECTIONS)


def test_the_sections_cross_as_the_same_objects() -> None:
    """W-5's ``InspectionSection``s are reused, not rebuilt: a section's
    ``read_status`` and ``limitation`` are the adapter's own, and a re-shaping
    step is a place they could be lost."""
    result = inspection_result()
    snapshot = assemble_snapshot(**inputs(inspection=result))  # type: ignore[arg-type]
    for name in ALL_SECTIONS:
        assert getattr(snapshot.inspection, name) is result.sections[name]


# --- 5. the native-validation narrowing (narrowing c) ------------------------


def test_the_block_is_unwrapped_and_its_provenance_is_dropped() -> None:
    """The messages cross; W-6's stamp does not.

    That provenance describes ONE validation run — its project, design, instant
    and AEDT version — and the snapshot has no field for it. It carries no
    ``snapshot_id`` and could not: W-6 emits no snapshot, and W-8 is what mints
    that id, so the two records describe different events.
    """
    block = native_block(["Design validation completed. 0 errors, 0 warnings."])
    snapshot = assemble_snapshot(**inputs(native_validation=block))  # type: ignore[arg-type]

    # The same object, not a copy — no re-shaping step to misrepresent anything.
    assert snapshot.native_validation is block.validation
    assert snapshot.native_validation.raw_output == [
        "Design validation completed. 0 errors, 0 warnings."
    ]
    # And nothing anywhere in the emitted artifact carries the run's stamp.
    dumped = snapshot.model_dump(mode="json")
    assert "validated_at" not in str(dumped)
    assert "validated_under_aedt_version" not in str(dumped)


def test_the_absence_arm_passes_through_untouched() -> None:
    """ADR-28 gave ``native_validation`` an absence arm; this is its path into a
    snapshot. Passing it through is not the adapter-reason mapping — that stays
    the caller's — it is accepting an already-mapped value, exactly as
    ``solve_state`` does."""
    absent = NativeValidationUnavailable(
        reason="not_exposed_by_pyaedt",
        limitation="HFSS's own design validator could not be run",
    )
    snapshot = assemble_snapshot(**inputs(native_validation=absent))  # type: ignore[arg-type]
    assert snapshot.native_validation is absent


def test_an_absent_native_validation_is_not_an_empty_one() -> None:
    """The misread ADR-23 most guards against, asserted at the assembly seam
    rather than only at the schema: ``raw_output=[]`` is a validator that RAN and
    reported nothing, and the two must not become the same snapshot."""
    ran = assemble_snapshot(**inputs(native_validation=native_block([])))  # type: ignore[arg-type]
    could_not_run = assemble_snapshot(
        **inputs(  # type: ignore[arg-type]
            native_validation=NativeValidationUnavailable(
                reason="not_exposed_by_pyaedt", limitation="x"
            )
        )
    )
    assert isinstance(ran.native_validation, NativeValidation)
    assert isinstance(could_not_run.native_validation, NativeValidationUnavailable)


# --- 6. the pass-through inputs ----------------------------------------------


def test_the_solve_fields_cross_as_the_same_objects_on_both_arms() -> None:
    """Neither field is re-wrapped on either arm. A ``SolveDataUnavailable`` is
    already the honest artifact for "there is none", and wrapper text over a
    reason the adapter worded correctly would only add a second voice."""
    absent = unavailable("not_exposed_by_pyaedt")
    solved = SolvedData(frequencies=[1.0], s_parameters={})
    snapshot = assemble_snapshot(
        **inputs(solve_state=absent, solved_data=solved)  # type: ignore[arg-type]
    )
    assert snapshot.solve_state is absent
    assert snapshot.solved_data is solved


def test_the_environment_crosses_as_the_same_object() -> None:
    kwargs = inputs()
    snapshot = assemble_snapshot(**kwargs)  # type: ignore[arg-type]
    assert snapshot.environment is kwargs["environment"]


# --- 7. the variation, propagated and never computed -------------------------


def test_the_variation_crosses_byte_for_byte() -> None:
    supplied = variation(
        values={"w": "2mm", "h": "1.6mm"},
        variation_hash="sha256:f400eee42dafcdaae80b572bdb42818735e2843b804b5bd68896a7b341b54a88",
    )
    snapshot = assemble_snapshot(**inputs(selection=chain(variation=supplied)))  # type: ignore[arg-type]
    assert snapshot.selection.variation is supplied
    assert snapshot.selection.variation.variation_hash == supplied.variation_hash
    assert snapshot.selection.variation.values == {"w": "2mm", "h": "1.6mm"}


def test_a_non_digest_variation_token_crosses_unchanged() -> None:
    """THE MEASURED CASE THAT RULES OUT RECOMPUTE-AND-COMPARE.

    ``_resolve_variation`` carries an unparseable PyAEDT variation string through
    AS the hash: ``_parse_variation("nominal")`` returns ``{}``, so the adapter
    emits ``Variation(values={}, variation_hash="nominal")``. A W-8 that
    recomputed a digest over the values and compared would raise on that — the
    sha256 of ``{}`` is ``sha256:44136fa3...``, which is not ``"nominal"`` — so
    it would fire on legitimate data.

    W-8 therefore computes no hash at all, and this asserts the consequence: the
    field is a stable handle supplied by its producer, not something this module
    may assume is a digest.
    """
    token = variation(values={}, variation_hash="nominal")
    snapshot = assemble_snapshot(**inputs(selection=chain(variation=token)))  # type: ignore[arg-type]
    assert snapshot.selection.variation.variation_hash == "nominal"
    assert not snapshot.selection.variation.variation_hash.startswith("sha256:")


def test_the_assembler_computes_no_digest() -> None:
    """Asserted structurally as well as behaviourally: no hashing primitive is
    reachable from this module at all, so there is no second canonicalization to
    drift from the adapter's.

    THE IMPORT AUDIT DOES NOT COVER THIS, which is the reason this test survived
    Part 8's cleanup. Measured, not assumed: adding ``import hashlib`` to the
    assembler leaves all ten tests in
    ``tests/boundary/test_snapshot_import_audit.py`` GREEN, and this is the only
    assertion in the whole suite that fails. ``hashlib`` sits in the blind spot
    both of that file's axes share — it is not an ``hfss_agent`` module, so the
    allowed-roots check never considers it, and it reaches no file, socket,
    environment or process, so it is not host-capable either. It is pure
    computation, and pure computation is exactly what W-8 must not do here.

    PARSED, NOT GREPPED, and that is Part 8's fix. This read the raw source text
    for the substring ``"hashlib"`` until now, docstrings included — so the next
    person to write a comment explaining why W-8 does not hash would have failed
    it, and the honest fix would have looked like deleting the test. The AST sees
    imports and calls; prose about hashing is now free to exist.
    """
    from hfss_agent.snapshot import assembler

    tree = ast.parse(Path(assembler.__file__).read_text(encoding="utf-8"))

    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            # Both spellings: ``sha256(...)`` and ``hashlib.sha256(...)``.
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)

    for module in ("hashlib", "hmac", "zlib"):
        assert module not in imported, (
            f"the assembler imports {module!r}; the canonical variation hash is "
            "the adapter's and W-8 computes none"
        )
    for primitive in ("sha256", "sha1", "sha512", "md5", "blake2b", "blake2s", "new"):
        assert primitive not in called, (
            f"the assembler calls {primitive!r}; the canonical variation hash is "
            "the adapter's and W-8 computes none"
        )


# --- 8. snapshot_id -----------------------------------------------------------


def test_the_snapshot_id_has_the_declared_form() -> None:
    """The PREFIX comes from the assembler's own constant, the SHAPE is spelled
    out here. ``_SNAPSHOT_ID_PREFIX`` exists so the form is stated in one place,
    and a test restating ``"snap-"`` would make that claim false — the hex width
    is a different matter, and is written independently on purpose."""
    snapshot = assemble_snapshot(**inputs())  # type: ignore[arg-type]
    assert re.fullmatch(
        re.escape(_SNAPSHOT_ID_PREFIX) + r"[0-9a-f]{32}", snapshot.snapshot_id
    ), f"unexpected snapshot_id form: {snapshot.snapshot_id!r}"


def test_two_assemblies_from_identical_inputs_get_different_ids() -> None:
    """THE PROPERTY THE ID EXISTS FOR. It identifies a CAPTURE EVENT, not a
    design state: two captures of an unchanged design are two captures, and an
    audit log that cited one id for both could not say which call produced which.

    A content hash would make this assertion false, which is precisely why the id
    is not one.
    """
    kwargs = inputs()
    first = assemble_snapshot(**kwargs)  # type: ignore[arg-type]
    second = assemble_snapshot(**kwargs)  # type: ignore[arg-type]
    assert first.snapshot_id != second.snapshot_id


def test_the_id_carries_no_host_fact() -> None:
    """``uuid4`` draws from ``os.urandom`` and embeds nothing about the machine.
    ``uuid1`` would embed the MAC address; this asserts the id is not one, by
    checking the RFC 4122 version nibble rather than by reading the source.
    """
    snapshot = assemble_snapshot(**inputs())  # type: ignore[arg-type]
    assert snapshot.snapshot_id[len(_SNAPSHOT_ID_PREFIX) :][12] == "4"


# --- 9. created_at ------------------------------------------------------------


def test_created_at_is_timezone_aware_utc() -> None:
    """Property-based, following ``test_read_at_is_timezone_aware_utc`` and
    ``test_validated_at_is_timezone_aware_utc``: no clock is injected anywhere in
    this package, so the assertion is about the value's shape rather than its
    instant."""
    snapshot = assemble_snapshot(**inputs())  # type: ignore[arg-type]
    assert snapshot.created_at.tzinfo is not None
    assert snapshot.created_at.utcoffset().total_seconds() == 0


def test_created_at_is_stamped_at_assembly_not_taken_from_an_input() -> None:
    """The field means "when the pieces were composed", and every input carries
    an earlier instant of its own. W-5's read and W-6's run are both stamped in
    2026-08-03 by the helpers; the snapshot's own instant must be neither.
    """
    before = datetime.now(timezone.utc)
    snapshot = assemble_snapshot(**inputs())  # type: ignore[arg-type]
    after = datetime.now(timezone.utc)

    assert before <= snapshot.created_at <= after
    assert snapshot.created_at != datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
    assert snapshot.created_at != datetime(2026, 8, 3, 9, 30, tzinfo=timezone.utc)


def test_a_refused_assembly_never_reads_the_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE STAMP ORDERING, OBSERVED RATHER THAN ASSUMED.

    Until Part 7 this test was named ``test_a_refused_assembly_stamps_nothing``
    and its whole body was ``pytest.raises(SnapshotAssemblyError)`` — which is
    true of every refusal test in this file and says nothing about WHEN the
    stamp is taken. Moving ``created_at = datetime.now(...)`` to the top of
    ``assemble_snapshot`` left it green, so the one regression it was named for
    was the one it could not see.

    With no injectable clock, the observable is the clock CALL itself. Patching
    the module-level ``datetime`` name the assembler imported follows the
    precedent in ``tests/preflight/test_assembler.py``, which patches
    ``assembler_module._aedt_check`` the same way.

    What this pins: a refusal must not put a time on an artifact that was never
    produced, and the assembler must not take one speculatively "in case" it
    succeeds. Both halves are here — the refusal path reads no clock, and the
    success path reads exactly one.
    """
    from hfss_agent.snapshot import assembler

    calls: list[object] = []

    class RecordingDatetime:
        @staticmethod
        def now(tz: object) -> datetime:
            calls.append(tz)
            return datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(assembler, "datetime", RecordingDatetime)

    with pytest.raises(SnapshotAssemblyError):
        assemble_snapshot(**inputs(selection=SelectionChain()))  # type: ignore[arg-type]
    assert calls == [], "a refused assembly read the clock before it refused"

    # The control: the same patched clock, a complete input set, one read. Both
    # in one test so neither half can be deleted alone — without the success
    # case, a ``datetime`` the assembler never called at all would pass.
    snapshot = assemble_snapshot(**inputs())  # type: ignore[arg-type]
    assert len(calls) == 1
    assert snapshot.created_at == datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


# --- 10. the artifact survives the seam ---------------------------------------


def test_the_snapshot_round_trips_through_json_unchanged() -> None:
    """The snapshot crosses ``evaluate()`` as JSON, so anything that did not
    survive serialization is a defect invisible in-process."""
    snapshot = assemble_snapshot(**inputs())  # type: ignore[arg-type]
    reloaded = DesignSnapshot.model_validate_json(snapshot.model_dump_json())
    assert reloaded == snapshot


def test_both_absence_arms_round_trip_as_their_own_types() -> None:
    """The never-solved shape, assembled rather than hand-built: an arm that
    collapsed into its sibling on the way through JSON would be invisible
    in-process."""
    snapshot = assemble_snapshot(
        **inputs(  # type: ignore[arg-type]
            solve_state=unavailable("not_exposed_by_pyaedt"),
            solved_data=unavailable("no_solution"),
            native_validation=NativeValidationUnavailable(
                reason="not_exposed_by_pyaedt", limitation="x"
            ),
        )
    )
    reloaded = DesignSnapshot.model_validate_json(snapshot.model_dump_json())

    assert isinstance(reloaded.solve_state, SolveDataUnavailable)
    assert isinstance(reloaded.solved_data, SolveDataUnavailable)
    assert isinstance(reloaded.native_validation, NativeValidationUnavailable)
    assert reloaded.solve_state.reason == "not_exposed_by_pyaedt"
    assert reloaded.solved_data.reason == "no_solution"
    # Nothing in a never-solved snapshot claims the design converged or stopped.
    assert "convergence_status" not in str(snapshot.model_dump(mode="json"))


# --- 11. the four reasons are distinguishable, and none renames the work ------

# EVERY MESSAGE THAT CAN REACH A CALLER, not one per reason — the two union-typed
# inputs each produce their own text for the refusal and wiring reasons, so four
# REASONS yield six MESSAGES. The distinction matters twice below: the
# distinguishability test is about reasons and groups these, while the
# vocabulary test is about what a caller can be shown and must see all six.
def _all_messages() -> dict[str, str]:
    """Every distinct refusal message, collected through the real entry point."""
    messages: dict[str, str] = {}
    for label, kwargs in (
        ("refusal_inspection", inputs(inspection=_cannot_evaluate())),
        ("refusal_native", inputs(native_validation=_cannot_evaluate())),
        ("incomplete_chain", inputs(selection=chain(setup=None))),
        ("subset_inspection", inputs(inspection=inspection_result(ALL_SECTIONS[:7]))),
        ("wiring_inspection", inputs(inspection=object())),
        ("wiring_native", inputs(native_validation=object())),
    ):
        with pytest.raises(SnapshotAssemblyError) as caught:
            assemble_snapshot(**kwargs)  # type: ignore[arg-type]
        messages[label] = str(caught.value)
    return messages


def test_the_four_raise_reasons_are_distinguishable_from_the_message_alone() -> None:
    """FOUR REASONS, and the wiring guard is the fourth.

    It was excluded from this property until Part 7, on the reading that a
    wiring bug is a different category from a refusal. It is not: it raises the
    same type, emits no snapshot, and reaches a caller exactly as the other
    three do. What IS different is only that no correctly-typed caller can
    reach it — which is a statement about who sees the message, not about
    whether it must be legible when they do.
    """
    messages = _all_messages()
    # Six distinct texts: the two union inputs each name themselves.
    assert len(set(messages.values())) == 6
    # And each phrase identifies exactly one REASON — one label for the two
    # single-site reasons, two for the two that either union input can raise.
    for phrase, owners in (
        ("a refusal arm was supplied", ["refusal_inspection", "refusal_native"]),
        ("the selection chain does not name a", ["incomplete_chain"]),
        ("sections and is missing", ["subset_inspection"]),
        (
            "is not a type this parameter is declared to accept",
            ["wiring_inspection", "wiring_native"],
        ),
    ):
        found = sorted(label for label, text in messages.items() if phrase in text)
        assert found == sorted(owners), f"{phrase!r} identified {found}"


def test_no_message_calls_the_composition_a_read_or_a_run() -> None:
    """W-8 performs neither. Calling the composition a "read" would borrow W-5's
    word for something no adapter call happened for, and "run" would borrow
    W-6's; a message that misnames the work sends a maintainer to the wrong
    module. Every message says "no snapshot is assembled" instead.

    Covers all SIX reachable messages. The two wiring-guard texts were outside
    this property until Part 7 and satisfied it only by luck.
    """
    messages = _all_messages()
    assert len(messages) == 6
    for label, message in messages.items():
        lowered = message.lower()
        assert "read" not in lowered, f"{label} message calls the work a read"
        assert "run" not in lowered, f"{label} message calls the work a run"
        assert "no snapshot is assembled" in lowered


# --- 12. the wiring guard -----------------------------------------------------


@pytest.mark.parametrize("field", ["inspection", "native_validation"])
def test_a_wrong_typed_union_input_is_a_named_wiring_failure(field: str) -> None:
    """Not folded into the refusal case: a value of an undeclared type is a
    wiring bug, and reporting it as a refusal would relabel a broken call path as
    an upstream decline."""
    with pytest.raises(SnapshotAssemblyError) as caught:
        assemble_snapshot(**inputs(**{field: object()}))  # type: ignore[arg-type]
    message = str(caught.value)
    assert "is not a type this parameter is declared to accept" in message
    assert field in message


def test_the_helpers_project_and_design_survive_into_the_snapshot() -> None:
    """A guard on the suite itself: if the helpers ever stopped supplying real
    names, several assertions above would pass vacuously."""
    snapshot = assemble_snapshot(**inputs())  # type: ignore[arg-type]
    assert snapshot.selection.project == PROJECT_NAME
    assert snapshot.selection.design == DESIGN
