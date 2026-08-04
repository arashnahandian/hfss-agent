"""The project's filesystem path never reaches the engine — now executed, not
just decided (ADR-28).

Step 2.5a retyped ``Selection.project`` from a ``Project`` to a bare name and
pinned the SCHEMA half of this: ``tests/schemas/test_selection_carries_no_path.py``
asserts the type refuses a ``Project`` and that no path survives into a
hand-built selection block. What no code did until now is the DROP itself —
taking a live ``SelectionChain``, which carries the path because the session
needs it, and composing a snapshot that does not. ``snapshot.assembler._selection``
is the first and only code that executes that decision, and this file is what
holds it to it.

WHY THE PATH IS WORTH DROPPING rather than tolerating: a default AEDT project
lives under ``%USERPROFILE%\\Documents\\Ansoft``, so the path routinely carries
the operator's Windows account name into the one artifact that leaves this
machine. Nothing downstream of the snapshot has a use for it.

WHY THIS IS ITS OWN FILE. Deleting the assertion should mean deleting a file,
not quietly removing a line from a long assembly suite — the same reasoning that
gives the schema half its own file one directory over.

THE TYPE SYSTEM IS A SECOND DETECTOR, BUT ONLY FOR THE CLUMSY MISTAKE, and the
distinction is the reason this file exists at all. Measured, not assumed:

  * ``Selection(project=<a Project>)`` RAISES ``ValidationError``
    (``type='string_type'``, "Input should be a valid string"), because
    ``Selection.project`` is an ``UntrustedStr``. So the whole-object regression
    — someone re-widening the field, or forgetting ``.name`` entirely — is caught
    by pydantic before any test runs.
  * ``Selection(project=<a path string>)`` VALIDATES SILENTLY, because a path is
    a perfectly good ``str``. So the PLAUSIBLE regression — reaching for
    ``chain.project.path`` instead of ``chain.project.name``, one attribute
    away — is invisible to the type system.

Both are asserted below, so the claim "pydantic has our back here" cannot be made
about the half where it does not.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from pydantic import ValidationError
from snapshot_helpers import (
    PROJECT_NAME,
    PROJECT_PATH,
    chain,
    inputs,
)

from hfss_agent.contract import Project, Selection, Variation
from hfss_agent.snapshot import assemble_snapshot

# A path-like string: a Windows drive-and-backslash, a UNC prefix, or a POSIX
# absolute path with at least two segments. Deliberately broad and deliberately
# the same pattern the schema suite uses — the point is to catch a path that got
# reintroduced, not to classify one precisely.
_PATH_LIKE = re.compile(r"[A-Za-z]:\\|\\\\|/[^/\s]+/[^/\s]+")


def _path_like_strings(node: Any) -> list[str]:
    """Every string anywhere under ``node`` that looks like a filesystem path.

    WALKS THE DUMPED DICT, NEVER THE JSON TEXT. ``json.dumps`` escapes a
    backslash, so a substring check for a Windows path against serialized JSON is
    false even when the path is genuinely present — it would pass on planted
    data, on clean data, and on a fully broken schema. That trap is asserted
    directly in ``test_the_control_is_not_defeated_by_backslash_escaping`` below.
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


# --- the drop itself ----------------------------------------------------------


def test_the_chain_carries_the_path_and_the_snapshot_does_not() -> None:
    """BOTH SIDES IN ONE TEST, so neither half can be deleted alone.

    A test asserting only the absence would pass against a helper that never
    supplied a path; a test asserting only the presence would not be about the
    snapshot at all. The input is shown to carry the path, and the output is
    shown not to.
    """
    supplied = chain()
    assert supplied.project is not None
    assert supplied.project.path == PROJECT_PATH

    snapshot = assemble_snapshot(**inputs(selection=supplied))  # type: ignore[arg-type]

    assert snapshot.selection.project == PROJECT_NAME
    assert snapshot.selection.project != PROJECT_PATH
    assert PROJECT_PATH not in snapshot.selection.project


def test_no_path_survives_anywhere_in_the_serialized_selection_block() -> None:
    """SCOPED TO ``selection``, and the whole-tree version would be FALSE.

    ``native_validation.raw_output`` carries HFSS's own ValidateDesign messages
    unmodified, and those legitimately name project files, material libraries and
    log locations — ``test_a_validator_message_may_legitimately_contain_a_path``
    below demonstrates exactly that. ``selection`` is what the wrapper itself
    composes, so it is what the wrapper can be held to.
    """
    snapshot = assemble_snapshot(**inputs())  # type: ignore[arg-type]
    dumped = snapshot.model_dump(mode="json")
    assert _path_like_strings(dumped["selection"]) == []


def test_the_account_name_does_not_reach_the_selection_block() -> None:
    """The specific harm, named rather than left implicit: the default AEDT path
    carries the operator's Windows account name, and that is what this decision
    is protecting."""
    snapshot = assemble_snapshot(**inputs())  # type: ignore[arg-type]
    rendered = json.dumps(snapshot.model_dump(mode="json")["selection"])
    assert "Owner" not in rendered
    assert "Documents" not in rendered
    assert "Ansoft" not in rendered


# --- the negative control, and the trap it sits on ---------------------------


def test_the_control_fires_when_a_path_is_planted() -> None:
    """A test of the TEST, not of the code.

    An assertion that never fails is indistinguishable from one that cannot, and
    this project has already shipped one: the diagnostics bundle's path control
    passed under full neutering because it searched serialized JSON for a raw
    Windows path that escaping guaranteed would never appear there. So the
    control is planted, shown to fire, and the clean case shown green immediately
    after — in one test, so neither half can be deleted without the other.

    Planted through the project NAME, which is the only route left now that the
    assembler drops the path and the type refuses a ``Project``.
    """
    planted_chain = chain(project=Project(name=PROJECT_PATH, path=PROJECT_PATH))
    planted = assemble_snapshot(**inputs(selection=planted_chain))  # type: ignore[arg-type]
    assert _path_like_strings(planted.model_dump(mode="json")["selection"]) == [
        PROJECT_PATH
    ]

    clean = assemble_snapshot(**inputs())  # type: ignore[arg-type]
    assert _path_like_strings(clean.model_dump(mode="json")["selection"]) == []


def test_the_control_is_not_defeated_by_backslash_escaping() -> None:
    """WHY THE HELPER WALKS THE DUMPED DICT AND NOT THE JSON TEXT.

    The documented trap, asserted rather than described: a naive
    ``PROJECT_PATH in json_text`` check is FALSE even when the path is genuinely
    present, because the separators were doubled on the way out.
    """
    planted_chain = chain(project=Project(name=PROJECT_PATH, path=PROJECT_PATH))
    planted = assemble_snapshot(**inputs(selection=planted_chain))  # type: ignore[arg-type]
    json_text = planted.model_dump_json()

    assert PROJECT_PATH not in json_text
    assert PROJECT_PATH.replace("\\", "\\\\") in json_text
    assert json.loads(json_text)["selection"]["project"] == PROJECT_PATH
    assert _path_like_strings(planted.model_dump(mode="json")["selection"]) == [
        PROJECT_PATH
    ]


def test_a_validator_message_may_legitimately_contain_a_path() -> None:
    """The measurement behind the scoping above.

    A native message naming a file is ordinary output and the snapshot carries it
    verbatim — reading inside these messages to strip anything is where passing
    output through stops and rewriting it begins. So a whole-tree path assertion
    would fail here on correct behaviour.
    """
    from snapshot_helpers import native_block

    message = rf"Error: material library not found at {PROJECT_PATH}"
    snapshot = assemble_snapshot(
        **inputs(native_validation=native_block([message]))  # type: ignore[arg-type]
    )
    dumped = snapshot.model_dump(mode="json")

    assert dumped["native_validation"]["raw_output"] == [message]
    assert _path_like_strings(dumped) != []
    assert _path_like_strings(dumped["selection"]) == []


# --- what the type system does and does not catch ----------------------------


def test_pydantic_refuses_the_whole_project_object() -> None:
    """The clumsy regression: re-widening the field, or dropping ``.name``.

    Caught by the schema before any assertion in this file runs, which makes
    pydantic a real second detector — for this half.
    """
    with pytest.raises(ValidationError) as caught:
        Selection(
            process_id=1,
            project=Project(name=PROJECT_NAME, path=PROJECT_PATH),  # type: ignore[arg-type]
            design="HFSSDesign1",
            solution_type="DrivenModal",
            setup="Setup1",
            sweep="Sweep1",
            variation=Variation(values={}, variation_hash="sha256:x"),
        )
    error = caught.value.errors()[0]
    assert error["loc"] == ("project",)
    assert error["type"] == "string_type"


def test_pydantic_accepts_a_path_string_which_is_why_this_file_exists() -> None:
    """The plausible regression, and the type system's blind spot.

    ``chain.project.path`` is one attribute away from ``chain.project.name`` and
    is a perfectly valid ``str``, so the schema validates it without complaint.
    Nothing but the assertions above stands there — which is the honest reason
    this file is not redundant with the schema suite.
    """
    selection = Selection(
        process_id=1,
        project=PROJECT_PATH,
        design="HFSSDesign1",
        solution_type="DrivenModal",
        setup="Setup1",
        sweep="Sweep1",
        variation=Variation(values={}, variation_hash="sha256:x"),
    )
    assert selection.project == PROJECT_PATH
