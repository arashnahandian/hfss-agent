"""W-11's classifier: the bands, the parse, and the multi-install rule.

Every test here runs without AEDT, without PyAEDT, and without reading the
machine — the module under test imports nothing that could. That is the whole
reason the classifier is separated from the probes: a band is a decision about
version numbers, and deciding it should not require owning the software.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hfss_agent.preflight.support_matrix import (
    AEDT_ANCHOR,
    AEDT_FLOOR,
    PYAEDT_PIN,
    PYTHON_CEILING_EXCLUSIVE,
    PYTHON_FLOOR,
    PYTHON_TARGET,
    SUPPORT_MATRIX_REF,
    aggregate_installed_aedt_status,
    classify_aedt,
    classify_pyaedt,
    classify_python,
    component_status,
    format_aedt_version,
    parse_aedt_env_var_name,
    parse_dotted_version,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PREFLIGHT = _REPO_ROOT / "src" / "hfss_agent" / "preflight"
_SRC = _REPO_ROOT / "src" / "hfss_agent"


# --- the published reference -------------------------------------------------


def test_support_matrix_ref_is_the_published_value() -> None:
    """Pinned because it is published: every report carries this string."""
    assert SUPPORT_MATRIX_REF == "docs/support-matrix.md"


def _is_separator(cells: list[str]) -> bool:
    """True for a markdown table's header/body separator row.

    STRUCTURAL, NOT LITERAL. The first version of this parse dropped the
    separator by matching the exact string ``"----------------"``, which meant
    reformatting the table's dashes would make the separator parse as a DATA
    row — and the "exactly one target" assertion would still have passed while
    the helper quietly returned a malformed row. This step has twice found tests
    passing for reasons unrelated to what they asserted, and that is the same
    family, so the rule is now what actually defines a separator: every cell
    consists only of dashes and alignment colons. No dash count, no alignment
    style (``---``, ``:---``, ``---:``, ``:---:``) can defeat it, and a real
    data cell — which always contains at least one other character — can never
    be mistaken for one.
    """
    return bool(cells) and all(
        cell and set(cell) <= {"-", ":"} for cell in cells
    )


def _aedt_table_rows() -> list[list[str]]:
    """The AEDT table's data rows, as stripped cells.

    Scoped to the ``## AEDT`` section rather than the whole file, because all
    three tables carry a ``target`` row and a file-wide search would find the
    Python one just as happily.

    THE HEADER IS DROPPED BY POSITION, NOT BY ITS TEXT. Markdown fixes the
    order — header, separator, then body — so everything at or before the
    structurally-identified separator is not data. That removes the second
    literal the first version carried (matching the header cell ``"Support
    status"``), which would have broken just as quietly if a column were ever
    renamed.

    A row whose width does not match the header's RAISES rather than being
    returned. Silently handing back a malformed row is exactly the failure this
    helper was rewritten to prevent, so it is made loud instead.
    """
    lines = (_REPO_ROOT / SUPPORT_MATRIX_REF).read_text(encoding="utf-8").splitlines()
    start = lines.index("## AEDT")
    end = next(
        index
        for index, line in enumerate(lines[start + 1 :], start + 1)
        if line.startswith("## ")
    )
    rows = [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in lines[start:end]
        if line.startswith("|")
    ]
    separator = next(
        (index for index, row in enumerate(rows) if _is_separator(row)), None
    )
    assert separator is not None, "the AEDT table has no header separator row"
    width = len(rows[0])
    body = rows[separator + 1 :]
    malformed = [row for row in body if len(row) != width]
    assert not malformed, (
        f"the AEDT table has row(s) whose width differs from the {width}-column "
        f"header: {malformed}"
    )
    return body


@pytest.mark.parametrize(
    ("cells", "expected"),
    [
        (["----", "----"], True),
        (["-", "-"], True),
        (["-" * 40, "-" * 3], True),
        ([":---", "---:"], True),
        ([":---:", ":-:"], True),
        (["`2026.1`", "target"], False),
        (["v < 2022.2", "unsupported"], False),
        (["AEDT version", "Support status"], False),
        (["", ""], False),
        ([], False),
    ],
)
def test_the_separator_filter_cannot_be_defeated_by_reformatting(
    cells: list[str], expected: bool
) -> None:
    """The regression guard for the brittleness this helper was rewritten for.

    The first version matched the separator by its exact dash count, so
    reformatting the table would have turned the separator into an apparent
    data row without failing anything. This pins the structural rule instead:
    dashes and alignment colons only, at any length and in any alignment style,
    and never a cell carrying real content.
    """
    assert _is_separator(cells) is expected


def test_the_documents_anchor_row_agrees_with_the_code() -> None:
    """THE DOC-TO-CODE LINK, on the file ADR-26 decision 18(d) calls "the
    specification the classifier reads".

    WHAT THIS MATCH PROVES: the ``## AEDT`` table contains EXACTLY ONE row whose
    support status is ``target``, and the version in that row's first cell is
    the same version ``AEDT_ANCHOR`` holds. Change the doc's anchor row to
    2027.1 without changing the constant and this fails; change the constant
    without the doc and it fails too. That is the drift the Done bar is about.

    WHAT IT DOES NOT PROVE, stated because a looser version of this test is
    exactly the vacuity trap this step already fell into once. It does not check
    the prose: the ``### 2026.1 — the anchor`` heading, the body paragraphs, and
    the component table's "2026.1 is the target" cell are all unverified and
    could disagree. It does not check the other three bands, the Python table,
    or the PyAEDT table. And it deliberately does NOT grep the file for the
    string "2026.1", which would pass on any of the eleven other mentions —
    including one inside a sentence about PyAEDT's constant, which is the number
    the anchor must NOT be derived from.
    """
    targets = [row for row in _aedt_table_rows() if row[1] == "target"]
    assert len(targets) == 1, (
        f"the AEDT table must name exactly one target version; found {targets}"
    )
    documented = targets[0][0].strip("`")
    assert documented == format_aedt_version(AEDT_ANCHOR), (
        f"docs/support-matrix.md names {documented!r} as the AEDT target while "
        f"AEDT_ANCHOR is {format_aedt_version(AEDT_ANCHOR)!r}. The document is "
        "the specification; the constant implements it, and they have drifted."
    )


def test_support_matrix_ref_names_a_document_that_exists() -> None:
    """The anti-dangling guard.

    ``support_matrix_ref`` is a required field, so a rename that left this
    string behind would put a dead pointer in every report ever produced, and
    nothing would notice — the report would still validate. This makes the
    rename fail here instead.

    Repo-time only, and deliberately so: the wheel packages ``src/hfss_agent``
    alone, so ``docs/`` does not ship with an installed distribution. The field
    is a citation for a human, never a path the running code resolves.
    """
    assert (_REPO_ROOT / SUPPORT_MATRIX_REF).is_file()


# --- the boundaries ----------------------------------------------------------


def test_the_boundaries_are_pinned() -> None:
    """The six constants, pinned so a band cannot move by accident.

    Moving one of these is a change to what this product claims to support, and
    it is only honest alongside an edit to ``docs/support-matrix.md``, which is
    the specification these implement. Failing here is the reminder.
    """
    assert AEDT_ANCHOR == (2026, 1)
    assert AEDT_FLOOR == (2022, 2)
    assert PYTHON_TARGET == (3, 12)
    assert PYTHON_FLOOR == (3, 10)
    assert PYTHON_CEILING_EXCLUSIVE == (3, 13)
    assert PYAEDT_PIN == (1, 2)


def test_the_anchor_is_not_derived_from_pyaedts_constant() -> None:
    """No code under ``src/`` references ``CURRENT_STABLE_AEDT_VERSION``.

    THE PIN TEST ABOVE PROVES THE VALUE; THIS PROVES THE INDEPENDENCE, and they
    are different properties. ``CURRENT_STABLE_AEDT_VERSION`` holds 2026.1 in
    the pinned PyAEDT too, so an anchor read from it would pass every value
    assertion in this file while being wrong in a way that only shows up later:
    that constant is hand-maintained and moves with each PyAEDT release, so
    deriving from it would let a dependency bump silently redefine "target".

    AST-BASED, NOT A TEXT SCAN, and the difference matters here specifically:
    ``support_matrix.py`` NAMES the constant in a comment, precisely to record
    that it is not used. A substring search would flag the sentence explaining
    the rule as a violation of it. Only a Name or an Attribute can actually read
    the constant — a bare string could reach it only through ``getattr`` or
    ``eval``, and this repo forbids arbitrary execution outright.
    """
    offenders: list[str] = []
    for source in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "CURRENT_STABLE_AEDT_VERSION":
                offenders.append(f"{source.name}: name reference")
            elif (
                isinstance(node, ast.Attribute)
                and node.attr == "CURRENT_STABLE_AEDT_VERSION"
            ):
                offenders.append(f"{source.name}: attribute reference")
    assert not offenders, f"anchor derived from PyAEDT's constant: {offenders}"


def test_the_classifier_reads_no_host_state() -> None:
    """Only ``probes.py`` may import the machine-reading modules.

    Globbed rather than listed, so ``assembler.py`` inherits this the moment it
    lands rather than needing the test edited. This is the structural half of
    the guarantee that no test reads the host: the probes are injected, and
    nothing outside the probe module can go around the seam to reach the
    environment directly.
    """
    forbidden = {"os", "platform", "importlib", "importlib.metadata", "sys"}
    offenders: list[str] = []
    for source in sorted(_PREFLIGHT.glob("*.py")):
        if source.name == "probes.py":
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders += [
                    f"{source.name}: import {alias.name}"
                    for alias in node.names
                    if alias.name.split(".")[0] in forbidden
                ]
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in forbidden:
                    offenders.append(f"{source.name}: from {node.module} import ...")
    assert not offenders, f"host state read outside probes.py: {offenders}"


# --- parsing an install-root variable name -----------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ANSYSEM_ROOT261", (2026, 1)),
        ("ANSYSEM_ROOT251", (2025, 1)),
        ("ANSYSEM_ROOT242", (2024, 2)),
        ("ANSYSEM_ROOT222", (2022, 2)),
        ("ANSYSEM_ROOT212", (2021, 2)),
        ("AWP_ROOT261", (2026, 1)),
        ("ANSYSEMSV_ROOT261", (2026, 1)),
        ("ANSYSEM_PY_CLIENT_ROOT261", (2026, 1)),
    ],
)
def test_parse_reads_the_version_out_of_the_name(
    name: str, expected: tuple[int, int]
) -> None:
    """All four prefixes PyAEDT recognises, and only the NAME is consulted.

    Student and client roots parse to the same version as a full install: the
    matrix draws no such distinction, so neither does the parse.
    """
    assert parse_aedt_env_var_name(name) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ANSYSEM_ROOT193", (2019, 1)),
        ("ANSYSEM_ROOT194", (2019, 2)),
        ("ANSYSEM_ROOT192", (2018, 2)),
        ("ANSYSEM_ROOT191", (2018, 1)),
    ],
)
def test_parse_mirrors_pyaedts_pre_2020_adjustment(
    name: str, expected: tuple[int, int]
) -> None:
    """The legacy numbering, mirrored from ``AedtVersions.installed_versions``.

    Everything this branch produces is below ``AEDT_FLOOR`` and would classify
    as ``unsupported`` under any parse, so the branch does not change a single
    verdict. It is mirrored anyway so the version this report NAMES is the one
    PyAEDT would name for the same machine — a report citing a version no other
    tool agrees with is worse than one citing an old one.
    """
    assert parse_aedt_env_var_name(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "PATH",
        "ANSYSEM_ROOT",
        "ANSYSEM_ROOT26",
        "ANSYSEM_ROOT2611",
        "ANSYSEM_ROOT26A",
        "ansysem_root261",
        "XANSYSEM_ROOT261",
        "ANSYSEM_ROOT261X",
        "",
    ],
)
def test_parse_refuses_a_name_that_is_not_an_install_root(name: str) -> None:
    """Anchored and case-sensitive, matching PyAEDT's own pattern.

    Returning None rather than raising keeps the scan total: an unrecognised
    variable is skipped, never a crash on a machine with an oddly-named one.
    """
    assert parse_aedt_env_var_name(name) is None


def test_format_aedt_version_uses_the_spelling_aedt_uses() -> None:
    assert format_aedt_version((2026, 1)) == "2026.1"
    assert format_aedt_version((2022, 2)) == "2022.2"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3.12.10", (3, 12)),
        ("3.10.0", (3, 10)),
        ("1.2.0", (1, 2)),
        ("1.2", (1, 2)),
        ("1.3.0rc1", (1, 3)),
        ("1.2.0.post1", (1, 2)),
        ("1.2.0+local.1", (1, 2)),
    ],
)
def test_parse_dotted_version_reads_major_minor(
    text: str, expected: tuple[int, int]
) -> None:
    assert parse_dotted_version(text) == expected


@pytest.mark.parametrize("text", ["", "1", "abc", "1.x", ".1.2", "1!2.0"])
def test_parse_dotted_version_refuses_what_it_cannot_read(text: str) -> None:
    """Total, and narrow on purpose. ``1!2.0`` (a PEP 440 epoch) is refused
    rather than read as 2.0 — no distribution this project pins uses one, and a
    silently wrong parse would be worse than a stated refusal."""
    assert parse_dotted_version(text) is None


# --- the bands ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ((2021, 2), "unsupported"),
        ((2022, 1), "unsupported"),
        ((2022, 2), "expected"),
        ((2024, 2), "expected"),
        ((2026, 1), "target"),
        ((2026, 2), "beyond-pin"),
        ((2027, 1), "beyond-pin"),
    ],
)
def test_classify_aedt_bands(version: tuple[int, int], expected: str) -> None:
    """All four bands including both exact boundaries — the floor is inclusive
    and the anchor is a single point."""
    assert classify_aedt(version) == expected


def test_release_ten_sorts_above_release_two_as_floats_would_not() -> None:
    """The reason the comparison is int tuples and not floats.

    PyAEDT compares versions as ``float(v[:6])``. On that comparison a
    hypothetical 2022 R10 becomes ``2022.1``, which sorts BELOW ``2022.2`` — a
    newer release falling under our floor and being reported as unsupported. No
    AEDT release has reached R10, which is exactly why this is cheap to fix now:
    the two orderings agree on every version that exists, so nothing observable
    changes today.
    """
    assert float("2022.10"[:6]) < float("2022.2")
    assert (2022, 10) > (2022, 2)
    assert classify_aedt((2022, 10)) == "expected"


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ((3, 9), "unsupported"),
        ((2, 7), "unsupported"),
        ((3, 10), "expected"),
        ((3, 11), "expected"),
        ((3, 12), "target"),
        ((3, 13), "beyond-pin"),
        ((3, 14), "beyond-pin"),
    ],
)
def test_classify_python_bands(version: tuple[int, int], expected: str) -> None:
    assert classify_python(version) == expected


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ((1, 1), "unsupported"),
        ((0, 9), "unsupported"),
        ((1, 2), "target"),
        ((1, 3), "beyond-pin"),
        ((2, 0), "beyond-pin"),
    ],
)
def test_classify_pyaedt_bands(version: tuple[int, int], expected: str) -> None:
    """No ``expected`` band exists here, and that is not an omission: the pin is
    a single minor, so there is no range between a floor and the target."""
    assert classify_pyaedt(version) == expected


@pytest.mark.parametrize(
    ("support", "expected"),
    [
        ("target", "ok"),
        ("expected", "ok"),
        ("beyond-pin", "ok"),
        ("unsupported", "incompatible"),
    ],
)
def test_only_unsupported_blocks(support: str, expected: str) -> None:
    """``beyond-pin`` maps to ``ok``, and that is the non-obvious one.

    A user on an AEDT newer than the anchor gets a healthy verdict with the
    caveat in the row's detail. Blocking them would refuse a machine PyAEDT
    itself accepts — its ``__check_version`` raises only when both
    ``current_version`` and ``latest_version`` are empty, and ``latest_version``
    is unfiltered, so a future-version-only machine passes.
    """
    assert component_status(support) == expected  # type: ignore[arg-type]


# --- the multi-install aggregation rule --------------------------------------


def test_an_empty_installed_set_is_incompatible_not_undetermined() -> None:
    """Absence is a DETERMINATION. With no install root PyAEDT's own
    ``__check_version`` raises, so attach is impossible rather than merely
    unverified — which is why the ``aedt`` row is ``incompatible`` and never
    ``unavailable``."""
    assert aggregate_installed_aedt_status(frozenset()) == "incompatible"


@pytest.mark.parametrize(
    ("versions", "expected"),
    [
        ({(2026, 1)}, "ok"),
        ({(2021, 2)}, "incompatible"),
        ({(2021, 2), (2026, 1)}, "ok"),
        ({(2024, 2), (2026, 1)}, "ok"),
        ({(2019, 1), (2021, 2)}, "incompatible"),
        ({(2027, 1)}, "ok"),
    ],
)
def test_the_aggregation_rule(
    versions: set[tuple[int, int]], expected: str
) -> None:
    """THE RULE ITSELF, not just its outcomes: supported if ANY installed
    version is, absent is incompatible, and only an all-unsupported set blocks.

    The third row is the one the rule exists for. A machine carrying 2021.2
    beside 2026.1 is ``ok`` because PyAEDT binds an attach by matching the
    target process against each installed version in turn, so attaching to the
    2026.1 process is a fully supported session. Blocking it would tell a user
    their environment cannot work while it demonstrably can.

    Decided at Step 2.4b Part 2 and recorded in ADR-27. ADR-26 decision 18(e)
    fixes only which version may be REPORTED on such a machine, not which
    verdict the set deserves.
    """
    assert aggregate_installed_aedt_status(versions) == expected


@pytest.mark.parametrize(
    "version",
    [(2019, 1), (2021, 2), (2022, 2), (2024, 2), (2026, 1), (2027, 1)],
)
def test_the_aggregation_rule_agrees_with_the_single_version_bands(
    version: tuple[int, int],
) -> None:
    """A one-element set must give exactly what classifying that version gives.

    Structural rather than coincidental — the rule routes through
    ``classify_aedt`` and ``component_status`` instead of comparing to
    ``AEDT_FLOOR`` itself, so the aggregate cannot drift from the bands it
    aggregates. This is the test that would fail if someone "simplified" it back
    to a direct comparison and then moved a band.
    """
    assert aggregate_installed_aedt_status({version}) == component_status(
        classify_aedt(version)
    )
