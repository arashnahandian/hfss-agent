"""``Selection`` carries a project NAME, never a path (ADR-28).

§1.1 W-8 says a snapshot is "plain JSON-serializable data only — never live
handles, sessions, paths, or callables." §2 said the selection block carried
"project (name+path)", and the contract implemented §2. The two lines could not
both be honoured, §1.1 is the safety line, and it won: the snapshot now carries
the bare name and the path stays on ``SessionStatus.SelectionChain``, where the
session needs it to detect a project that moved and the audit log keeps it.

WHY A DEFAULT AEDT PATH IS WORTH REMOVING rather than tolerating: projects live
under ``%USERPROFILE%\\Documents\\Ansoft`` by default, so the path routinely
carries the operator's Windows account name into the one artifact that leaves
the wrapper for the engine. Nothing downstream of this field has a use for it.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from hfss_agent.contract import (
    CONTRACT_VERSION,
    DesignSnapshot,
    Environment,
    Inspection,
    InspectionSection,
    NativeValidation,
    Project,
    Selection,
    SolveDataUnavailable,
    Variation,
)
from hfss_agent.contract.tool_io import SelectionChain

# A realistic default-location AEDT project path: the shape that actually leaks
# an account name, not a sanitised stand-in like ``C:\proj\patch.aedt``. The
# existing fixtures use the short form, which is exactly why a negative control
# planting THIS one is worth having.
PLANTED_PATH = r"C:\Users\Owner\Documents\Ansoft\patch_antenna.aedt"

# A path-like string: a Windows drive-and-backslash, a UNC prefix, or a POSIX
# absolute path with at least two segments. Deliberately broad — the point is to
# catch a path that got reintroduced, not to classify one precisely.
_PATH_LIKE = re.compile(r"[A-Za-z]:\\|\\\\|/[^/\s]+/[^/\s]+")

_SECTION_NAMES = (
    "variables",
    "objects",
    "materials",
    "boundaries",
    "excitations_ports",
    "setups",
    "sweeps",
    "available_results",
)


def _path_like_strings(node: Any) -> list[str]:
    """Every string anywhere under ``node`` that looks like a filesystem path.

    WALKS THE DUMPED DICT, NEVER THE JSON TEXT, and that choice is the whole
    reason this helper exists instead of a substring check — see
    ``test_the_control_is_not_defeated_by_backslash_escaping``.
    """
    found: list[str] = []
    if isinstance(node, str):
        if _PATH_LIKE.search(node):
            found.append(node)
    elif isinstance(node, dict):
        for key, value in node.items():
            found += _path_like_strings(key)
            found += _path_like_strings(value)
    elif isinstance(node, (list, tuple)):
        for item in node:
            found += _path_like_strings(item)
    return found


def _snapshot(project: str, raw_output: list[str] | None = None) -> DesignSnapshot:
    section = InspectionSection(data=[], read_status="ok")
    return DesignSnapshot(
        contract_version=CONTRACT_VERSION,
        created_at=datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc),
        snapshot_id="snap-001",
        environment=Environment(
            aedt_version="2026.1",
            pyaedt_version="1.2.0",
            python_version="3.12.10",
            wrapper_version="0.0.0",
        ),
        selection=Selection(
            process_id=12345,
            project=project,
            design="HFSSDesign1",
            solution_type="DrivenModal",
            setup="Setup1",
            sweep="Sweep1",
            variation=Variation(values={}, variation_hash="sha256:x"),
        ),
        inspection=Inspection(**{name: section for name in _SECTION_NAMES}),
        native_validation=NativeValidation(raw_output=raw_output or []),
        solve_state=SolveDataUnavailable(reason="no_solution", limitation="x"),
        solved_data=SolveDataUnavailable(reason="no_solution", limitation="x"),
    )


# --- the type change ----------------------------------------------------------


def test_selection_refuses_a_path_carrying_project() -> None:
    """``Selection.project`` is a name. Handing it the ``Project`` it used to
    take — the exact shape of a regression that reverts this amendment — is
    refused by the schema rather than accepted and quietly serialized."""
    with pytest.raises(ValidationError) as caught:
        Selection(
            process_id=12345,
            project=Project(name="patch_antenna", path=PLANTED_PATH),  # type: ignore[arg-type]
            design="HFSSDesign1",
            solution_type="DrivenModal",
            setup="Setup1",
            sweep="Sweep1",
            variation=Variation(values={}, variation_hash="sha256:x"),
        )
    assert caught.value.errors()[0]["loc"] == ("project",)


def test_the_session_chain_still_carries_the_path() -> None:
    """Asserted from BOTH sides so the two cannot silently converge.

    Dropping the path from ``SelectionChain`` too would look like consistency
    and would break the session: it compares this value to detect a project that
    moved between a read and a re-verification. The split is the decision; each
    half needs its own assertion or only one of them is protected.
    """
    chain = SelectionChain(
        process_id=12345,
        project=Project(name="patch_antenna", path=PLANTED_PATH),
    )
    assert chain.project is not None
    assert chain.project.path == PLANTED_PATH


# --- the artifact-level property ----------------------------------------------


def test_no_path_survives_into_the_serialized_selection_block() -> None:
    """SCOPED TO ``selection``, AND THE WHOLE-TREE VERSION WOULD BE FALSE.

    The obvious assertion — "no path anywhere in the serialized snapshot" — is
    not a property this wrapper can offer, and asserting it would produce a test
    that fails on legitimate data. ``native_validation.raw_output`` carries
    HFSS's own ValidateDesign messages, passed through unmodified except for
    control-character stripping and length-capping (ADR-9). Those messages are
    HFSS's text, not ours, and can name project files, material libraries or log
    locations. ``test_a_validator_message_may_legitimately_contain_a_path``
    below demonstrates exactly that, so the scoping here is a measured fact
    rather than a hedge.

    ``selection`` is what the wrapper itself composes, so it is what the wrapper
    can be held to.
    """
    dumped = _snapshot("patch_antenna").model_dump(mode="json")
    assert _path_like_strings(dumped["selection"]) == []


def test_a_validator_message_may_legitimately_contain_a_path() -> None:
    """The measurement behind the scoping above.

    A native message naming a file is ordinary output, and the snapshot must
    carry it verbatim — reading inside these messages to strip anything is where
    passing output through stops and rewriting it begins, which W-6 does not do.
    So a whole-tree path assertion would fail here on correct behaviour.
    """
    message = rf"Error: material library not found at {PLANTED_PATH}"
    snapshot = _snapshot("patch_antenna", raw_output=[message])
    dumped = snapshot.model_dump(mode="json")

    # The message survives byte-for-byte...
    assert dumped["native_validation"]["raw_output"] == [message]
    # ...so a whole-tree assertion WOULD fire, while the scoped one does not.
    assert _path_like_strings(dumped) != []
    assert _path_like_strings(dumped["selection"]) == []


# --- the negative control, and the trap it sits on -----------------------------


def test_the_control_fires_when_a_path_is_planted() -> None:
    """A test of the TEST, not of the code.

    An assertion that never fails is indistinguishable from an assertion that
    cannot fail, and this project has already shipped one: the diagnostics
    bundle's path control passed under full neutering, because it searched
    serialized JSON text for a raw Windows path that JSON escaping guaranteed
    would never appear there. So the control is planted, shown to fire, and the
    clean case shown green immediately after — in one test, so neither half can
    be deleted without the other.
    """
    # Planted: the path goes in through the project NAME, which is the only way
    # a path can still reach this block now that the type refuses a Project.
    planted = _snapshot(PLANTED_PATH).model_dump(mode="json")
    assert _path_like_strings(planted["selection"]) == [PLANTED_PATH]

    # Removed: the same assertion, same helper, on clean data.
    clean = _snapshot("patch_antenna").model_dump(mode="json")
    assert _path_like_strings(clean["selection"]) == []


def test_the_control_is_not_defeated_by_backslash_escaping() -> None:
    """WHY THE HELPER WALKS THE DUMPED DICT AND NOT THE JSON TEXT.

    This is the documented trap, asserted rather than described. ``json.dumps``
    escapes a backslash, so ``C:\\Users\\...`` is written into serialized JSON as
    ``C:\\\\Users\\\\...`` — and a naive ``planted_path in json_text`` check is
    therefore FALSE even when the path is genuinely present. That assertion would
    pass on planted data, pass on clean data, and pass on a completely broken
    schema.

    Both halves are shown: the naive form does not see the planted path, and the
    form this suite actually uses does.
    """
    planted = _snapshot(PLANTED_PATH)
    json_text = planted.model_dump_json()

    # The trap: the raw literal is absent from the serialized text...
    assert PLANTED_PATH not in json_text
    # ...because it was rewritten with doubled separators.
    assert PLANTED_PATH.replace("\\", "\\\\") in json_text
    # Proof this is escaping and not absence: the value is really in there, and
    # the dict walk this suite uses finds it.
    assert json.loads(json_text)["selection"]["project"] == PLANTED_PATH
    assert _path_like_strings(planted.model_dump(mode="json")["selection"]) == [
        PLANTED_PATH
    ]
