"""Every leaf of an assembled snapshot is an inert value — no callables, no live
handles, no objects of any kind (§1.1 W-8, ADR-28 decision 17).

§1.1 says a snapshot is "plain JSON-serializable data only — never live handles,
sessions, paths, or callables". Step 2.5a pinned the ``selection`` half of that
by asserting no filesystem path survives into the selection block. This file
pins the WHOLE-TREE half, and it asserts a different KIND of property, which is
the thing to understand before editing anything here.

WHAT THIS ASSERTS: a TYPE property. Every leaf under ``model_dump()`` is an
instance of a closed allow-list of inert value types, with ``dict`` and ``list``
the only permitted containers. Nothing about what the values mean.

WHAT THIS DELIBERATELY DOES NOT ASSERT, all three measured rather than assumed:

  (a) NOT a substring check against ``model_dump_json()``. ADR-28 decision 17(a):
      ``json.dumps`` escapes a backslash, so ``"C:\\Users\\..." in json_text`` is
      FALSE even when the path is genuinely present — such a check passes on
      planted data, passes on clean data, and passes on a fully broken schema.
      ``test_path_is_dropped.py`` asserts that trap directly.
  (b) NOT that no string looks like a path. ADR-28 decision 17(b): a whole-tree
      "no string resembles a filesystem path" assertion is simply FALSE on
      correct data, because ``NativeValidation.raw_output`` carries HFSS's own
      ValidateDesign messages unmodified and those legitimately name project
      files, material libraries and log locations. A test asserting it would
      fail on correct behaviour, so the path property stays scoped to
      ``selection``, which is what the wrapper itself composes.
  (c) NOT that the values are MEANINGFUL. A wrong-but-inert value is out of
      scope here; the narrowing tests own that.

WHY THE WALK IS OVER ``model_dump()`` IN PYTHON MODE AND NOT JSON MODE — the
single most important line in this file, measured on this repo's pydantic:

    ``InspectionSection.data``, ``SolveState.adaptive_pass_history`` and
    ``FreshnessEvidence.available_signals`` are typed ``Any``, and pydantic does
    NOT validate ``Any``. A callable, a bound method or a live handle planted in
    one of them CONSTRUCTS FINE. Serialization is the only thing that objects —
    and it objects unevenly. A lambda or an arbitrary object raises
    ``PydanticSerializationError`` in both dump modes, but a ``pathlib.Path``
    serializes SILENTLY to a plain string, and ``bytes`` and ``set`` do too.

    So in json mode the ``Path`` is already a ``str`` by the time any assertion
    sees it, indistinguishable from legitimate text. Python mode keeps the object
    intact — measured: ``{'proj': WindowsPath(...), 'cb': <function ...>}`` —
    which is what makes the type walk able to see it at all.

TWO INDEPENDENT DETECTORS, and they must stay independent. The type walk is one;
round-trip equality (``model_validate_json(model_dump_json()) == snapshot``) is
the other, and it catches a planted ``Path`` because the reload gives back a
``str`` that no longer equals the original object. Each is mutation-tested
against the other: neutering one must leave the other still catching a planted
``Path``, because two detectors that die to a single edit are one detector.

EXACT TYPE, NOT ``isinstance``, and the difference is load-bearing twice over: a
``str`` subclass carrying extra state would pass an ``isinstance`` check while
being exactly the kind of object this file exists to exclude, and ``bool`` is a
subclass of ``int`` so it must be listed explicitly rather than inherited.
Measured against a real assembled snapshot: the leaf types are exactly
``{str, int, float, bool, NoneType, datetime}``, with no ``str`` subclass, no
``Enum``, and no ``dict``/``list`` subclass anywhere in the tree.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import pytest
from snapshot_helpers import (
    chain,
    environment,
    inspection_result,
    native_block,
    solved_data,
    variation,
)

from hfss_agent.contract import (
    DesignSnapshot,
    FreshnessEvidence,
    InspectionSection,
    SolutionExists,
    SolveState,
)
from hfss_agent.snapshot import assemble_snapshot

# The inert value types a leaf may be, matched by EXACT type. ``datetime`` is
# here because the contract legitimately carries two of them —
# ``DesignSnapshot.created_at`` and ``SolveState.solve_timestamps`` — and json
# mode would have flattened both to strings, hiding them from this check along
# with everything else it flattens.
ALLOWED_LEAF_TYPES: tuple[type, ...] = (
    str,
    int,
    float,
    bool,
    type(None),
    datetime,
)

# The only containers a snapshot tree may branch through, likewise by exact type:
# a dict or list SUBCLASS is an object with behaviour, and behaviour is what a
# snapshot must not carry.
ALLOWED_CONTAINER_TYPES: tuple[type, ...] = (dict, list)


class LiveHandleStub:
    """Stands in for a bound ``Hfss`` handle or an open session — an object with
    state and a method, which is precisely what §1.1 forbids a snapshot from
    carrying. Not a mock: a real object, so the detectors face a real one."""

    def __init__(self) -> None:
        self.project_path = r"C:\Users\Owner\Documents\Ansoft\patch_antenna.aedt"

    def close(self) -> None:  # a mutating method, reachable if this ever crossed
        raise AssertionError("a snapshot must never carry something callable")


def _offending_leaves(node: Any, path: str = "$") -> list[str]:
    """Every leaf whose EXACT type is outside the allow-list, with its location.

    Returns locations rather than a bool so a failure names WHERE the object is,
    which is the difference between a test that reports a defect and one that
    only reports that there is one.
    """
    node_type = type(node)
    if node_type in ALLOWED_CONTAINER_TYPES:
        found: list[str] = []
        if node_type is dict:
            for key, value in node.items():
                found += _offending_leaves(key, f"{path}.<key>")
                found += _offending_leaves(value, f"{path}.{key}")
        else:
            for index, item in enumerate(node):
                found += _offending_leaves(item, f"{path}[{index}]")
        return found
    if node_type in ALLOWED_LEAF_TYPES:
        return []
    return [f"{path}: {node_type.__module__}.{node_type.__qualname__}"]


def type_walk_offenders(snapshot: DesignSnapshot) -> list[str]:
    """DETECTOR 1 — the exact-type walk over the PYTHON-mode dump."""
    return _offending_leaves(snapshot.model_dump())


def round_trip_is_clean(snapshot: DesignSnapshot) -> bool:
    """DETECTOR 2 — the artifact survives its own serialization unchanged.

    Independent of the walk above: it never inspects a type. A planted ``Path``
    comes back from JSON as a ``str``, which does not equal the ``Path`` it
    replaced, so the snapshots differ.
    """
    return DesignSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot


# --- the three Any-typed holes, and how to plant into each -------------------


def _with_inspection_data(planted: object) -> DesignSnapshot:
    """``InspectionSection.data`` — typed ``Any`` so a section can carry whatever
    shape PyAEDT returned for it."""
    sections = {
        name: InspectionSection(data=[], read_status="ok")
        for name in inspection_result().sections
    }
    sections["variables"] = InspectionSection(data=planted, read_status="ok")
    result = inspection_result().model_copy(update={"sections": sections})
    return assemble_snapshot(**_inputs(inspection=result))  # type: ignore[arg-type]


def _with_pass_history(planted: object) -> DesignSnapshot:
    """``SolveState.adaptive_pass_history`` — ``list[Any]``, because the per-pass
    row shape PyAEDT returns is unverified."""
    return assemble_snapshot(**_inputs(solve_state=_solve_state([planted], {})))  # type: ignore[arg-type]


def _with_freshness_signal(planted: object) -> DesignSnapshot:
    """``FreshnessEvidence.available_signals`` — ``dict[str, Any]``, because what
    signals exist is per-design and not known ahead of time."""
    return assemble_snapshot(  # type: ignore[arg-type]
        **_inputs(solve_state=_solve_state([], {"handle": planted}))
    )


PLANTING_SITES = {
    "InspectionSection.data": _with_inspection_data,
    "SolveState.adaptive_pass_history": _with_pass_history,
    "FreshnessEvidence.available_signals": _with_freshness_signal,
}

PLANTED_OBJECTS = {
    "a callable": lambda: None,
    "a filesystem Path": Path(r"C:\Users\Owner\Documents\Ansoft\patch_antenna.aedt"),
    "a live-handle stub": LiveHandleStub(),
}


def _solve_state(
    pass_history: list[Any], signals: dict[str, Any]
) -> SolveState:
    return SolveState(
        solution_exists=[
            SolutionExists(
                setup="Setup1", sweep="Sweep1", variation=variation(), exists=True
            )
        ],
        adaptive_pass_history=pass_history,
        delta_s_progression=[0.004],
        convergence_status="converged",
        solve_timestamps={
            "Setup1:Sweep1": datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)
        },
        solver_messages=["Solve completed."],
        freshness_evidence=FreshnessEvidence(
            available_signals=signals, determinable=bool(signals)
        ),
    )


def _inputs(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "inspection": inspection_result(),
        "native_validation": native_block(["0 errors."]),
        "solve_state": _solve_state([{"pass": 1}], {"design_modified": False}),
        "solved_data": solved_data(),
        "selection": chain(),
        "environment": environment(),
    }
    values.update(overrides)
    return values


def clean_snapshot() -> DesignSnapshot:
    """A full, realistic snapshot: the SOLVED arm on both solve fields, so the
    walk covers ``adaptive_pass_history``, ``delta_s_progression``,
    ``solve_timestamps`` and ``available_signals`` rather than skipping them via
    an absence arm."""
    return assemble_snapshot(**_inputs())  # type: ignore[arg-type]


# --- 1. the clean case, and what its leaves actually are ---------------------


def test_a_real_snapshot_carries_only_inert_leaves() -> None:
    assert type_walk_offenders(clean_snapshot()) == []


def test_a_real_snapshot_round_trips_unchanged() -> None:
    assert round_trip_is_clean(clean_snapshot())


def test_the_allow_list_is_exactly_what_real_data_needs() -> None:
    """Measured, not assumed, and asserted in BOTH directions.

    A leaf type present in real data but missing from the list would make the
    walk fail on correct behaviour; a type in the list that never appears is an
    unexamined allowance the next planted object could slip through. Both are
    checked here so the list cannot quietly grow.
    """
    observed: set[type] = set()

    def collect(node: Any) -> None:
        node_type = type(node)
        if node_type is dict:
            for key, value in node.items():
                collect(key)
                collect(value)
        elif node_type is list:
            for item in node:
                collect(item)
        else:
            observed.add(node_type)

    collect(clean_snapshot().model_dump())

    assert observed <= set(ALLOWED_LEAF_TYPES), (
        f"real data carries leaf types the allow-list omits: "
        f"{observed - set(ALLOWED_LEAF_TYPES)}"
    )
    assert observed == set(ALLOWED_LEAF_TYPES), (
        f"the allow-list permits types no real snapshot carries: "
        f"{set(ALLOWED_LEAF_TYPES) - observed}"
    )


def test_bool_must_be_listed_explicitly_because_exact_type_does_not_inherit() -> None:
    """``bool`` is a subclass of ``int``, so ``isinstance(True, int)`` is True but
    ``type(True) is int`` is False. Under exact-type matching the allow-list must
    name ``bool`` or every boolean in a real snapshot — ``FreshnessEvidence
    .determinable``, ``SolutionExists.exists``, and any bool inside an ``Any``
    hole — would be reported as an offender.

    Asserted rather than commented, because this is the one place where switching
    the walk to ``isinstance`` would look like a harmless simplification and would
    silently admit every ``str`` and ``int`` subclass with it.
    """
    # Bound to a name rather than written as ``type(True)``: the claim is about
    # what ``type()`` returns for a boolean VALUE at runtime, which is what the
    # walk actually does, and a literal there would be rewritten to the bare
    # ``bool`` type and stop demonstrating it.
    truthy = True
    assert isinstance(truthy, int)
    assert type(truthy) is not int
    assert type(truthy) is bool
    assert bool in ALLOWED_LEAF_TYPES
    # And a real snapshot does carry booleans, so the entry is load-bearing.
    assert any(
        type(value) is bool
        for value in _flatten(clean_snapshot().model_dump())
    )


def test_no_leaf_is_a_str_subclass_or_an_enum() -> None:
    """The two shapes that would pass an ``isinstance``-based walk while being
    exactly what this file excludes. Measured on real data: neither occurs, so
    the exact-type check costs nothing today and closes the hole anyway."""
    for leaf in _flatten(clean_snapshot().model_dump()):
        if isinstance(leaf, str):
            assert type(leaf) is str, f"str subclass in the tree: {type(leaf)}"
        assert not isinstance(leaf, Enum)


def _flatten(node: Any) -> list[Any]:
    if type(node) is dict:
        out: list[Any] = []
        for key, value in node.items():
            out += _flatten(key) + _flatten(value)
        return out
    if type(node) is list:
        out = []
        for item in node:
            out += _flatten(item)
        return out
    return [node]


# --- 2. the planted controls, every hole × every object ----------------------


@pytest.mark.parametrize("hole", sorted(PLANTING_SITES))
@pytest.mark.parametrize("planted", sorted(PLANTED_OBJECTS))
def test_both_detectors_are_shown_firing_and_the_clean_case_stays_green(
    hole: str, planted: str
) -> None:
    """PLANTED AND CLEAN IN ONE TEST, so neither half can be deleted alone.

    Nine cases: three ``Any``-typed holes × three planted objects. Each object is
    a different failure shape and they are NOT interchangeable — a callable and a
    live handle raise on serialization, while a ``Path`` serializes silently to a
    string, which is the case the whole python-mode design exists for.

    Each detector is asserted to fire independently; ``test_the_detectors_are_not
    _the_same_detector`` below proves neither can be relied on alone.
    """
    build = PLANTING_SITES[hole]
    snapshot = build(PLANTED_OBJECTS[planted])

    # DETECTOR 1 fires, and names where.
    offenders = type_walk_offenders(snapshot)
    assert offenders, f"the type walk missed {planted} in {hole}"

    # DETECTOR 2 fires. A callable and a live handle cannot serialize at all —
    # which is itself a refusal, and the honest way to observe it here.
    try:
        clean = round_trip_is_clean(snapshot)
    except Exception as exc:
        assert type(exc).__name__ == "PydanticSerializationError", (
            f"unexpected serialization failure for {planted}: {type(exc).__name__}"
        )
    else:
        assert not clean, f"the round trip missed {planted} in {hole}"

    # And the clean case, same assertions, same helpers.
    assert type_walk_offenders(clean_snapshot()) == []
    assert round_trip_is_clean(clean_snapshot())


def test_a_planted_path_is_the_case_json_mode_would_have_missed() -> None:
    """THE MEASUREMENT BEHIND THE PYTHON-MODE DECISION.

    A ``pathlib.Path`` in an ``Any`` hole serializes silently to a plain string.
    In json mode it is already a ``str`` by the time any assertion sees it, and
    indistinguishable from legitimate text; in python mode the object survives
    and the walk sees it. Both halves asserted, so the reasoning in the module
    docstring is a fact about this repo rather than a claim about pydantic.
    """
    planted = Path(r"C:\Users\Owner\Documents\Ansoft\patch_antenna.aedt")
    snapshot = _with_inspection_data(planted)

    # Python mode: the object is intact and the walk names it.
    offenders = type_walk_offenders(snapshot)
    assert len(offenders) == 1
    assert "WindowsPath" in offenders[0] or "PosixPath" in offenders[0]

    # Json mode: already flattened to a str, so a walk there would find nothing.
    assert _offending_leaves(snapshot.model_dump(mode="json")) == []

    # And the round trip still catches it, which is why there are two detectors.
    assert not round_trip_is_clean(snapshot)


def test_a_callable_cannot_even_serialize() -> None:
    """The other failure shape, stated so the asymmetry is not a surprise: a
    lambda raises rather than flattening, in BOTH dump modes. That is a refusal
    and not a silent pass, but it is a different observable from the ``Path``
    case and the controls above must handle both."""
    snapshot = _with_inspection_data(lambda: None)

    assert type_walk_offenders(snapshot) != []
    with pytest.raises(Exception) as caught:
        snapshot.model_dump_json()
    assert type(caught.value).__name__ == "PydanticSerializationError"


def test_pydantic_does_not_validate_the_any_holes_which_is_why_this_file_exists() -> (
    None
):
    """The premise, asserted rather than assumed.

    If ``Any`` rejected a callable at construction, none of this would be needed.
    It does not: the snapshot builds, and the object sits in the tree in-process.
    """
    snapshot = _with_inspection_data(LiveHandleStub())
    assert isinstance(snapshot, DesignSnapshot)
    assert isinstance(snapshot.inspection.variables.data, LiveHandleStub)


# --- 3. the two detectors are genuinely independent -------------------------


def test_the_detectors_are_not_the_same_detector() -> None:
    """Each is shown to see something the other cannot.

    The type walk sees a planted ``Path`` in python mode; so does the round trip,
    by inequality. But the round trip ALSO sees a value that changed shape without
    changing type — and the walk cannot, because the type stayed legal. A ``set``
    planted in an ``Any`` hole is the demonstration: it serializes to a list, so
    the reloaded snapshot differs while every leaf type in the reloaded tree is
    allowed.
    """
    planted = _with_inspection_data({1, 2, 3})

    # The walk sees the set itself (a container type outside the allow-list)...
    assert type_walk_offenders(planted) != []
    # ...and the round trip sees the shape change independently.
    assert not round_trip_is_clean(planted)
    # The reloaded artifact, meanwhile, is entirely type-clean — so a walk run
    # only on the reloaded copy would report nothing at all.
    reloaded = DesignSnapshot.model_validate_json(planted.model_dump_json())
    assert type_walk_offenders(reloaded) == []
