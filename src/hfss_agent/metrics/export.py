"""W-7 export CONTENT: Touchstone v1.0 and CSV as strings (System Design §1.1).

This module generates text. It does not write files, and it must never learn
how: "Also owns Touchstone/CSV export content (the file write itself goes
through the broker)" is §1.1's split, and it is the same capability discipline
that keeps every other path to the disk inside W-4. There is no ``open``, no
``pathlib``, no ``os`` here, and the import audit in
``tests/boundary/test_metrics_import_audit.py`` is what keeps it that way rather
than this paragraph.

LINE ENDINGS ARE ALWAYS "\\n", NEVER "\\r\\n". The broker owns writing, so it
owns any platform conversion; emitting "\\r\\n" here would double-convert on
Windows and make the content untestable across the two CI legs. Every line,
including the last, ends with a single "\\n".

GENERAL N-PORT, DELIBERATELY. Locked Idea Spec Point 5 draws the envelope per
layer: "S-parameter extraction is general (any port count; Touchstone is
inherently multiport); the *interpreted* metric set is the approved list". So
``sparams`` is S11-only because the approved metric set is, and this module is
not -- a one-port-only exporter would be the toy-example failure Point 5 exists
to prevent.

REFUSE RATHER THAN PAD. A Touchstone file states a complete N x N matrix. If the
supplied keys do not form one, this module raises ``ExportContentError`` naming
what is missing; it never zero-fills a gap and never silently omits an entry. A
padded S-matrix is fabricated data, and it would be indistinguishable from
measured data once written.

UNTRUSTED STRINGS ARE NEUTRALISED HERE, AND THIS IS NOT DEFENCE IN DEPTH -- THE
NEWLINE REACHES THIS MODULE INTACT. ``project`` and ``design`` are
``UntrustedStr`` (§6.6 / ADR-9), sanitized at the adapter by
``hfss_agent.adapter.sanitize.sanitize_str``. That function strips control
characters EXCEPT tab and newline: its ``_KEEP_CONTROL = frozenset({"\\t",
"\\n"})`` keeps them deliberately, because "tab and newline are legitimate
structure in multi-line solver messages". Carriage return IS stripped there;
newline is NOT.

So a newline in an HFSS-sourced name arrives here unmodified, and without the
stripping below it would terminate a "!" comment and place an attacker-chosen
line into the data section of a file downstream tooling reads as measurements.
This is the only layer that closes that gap for an export, which is why the
guard lives here and why it is not redundant with the adapter.

The adapter's choice is right for its own job -- mangling multi-line solver
messages to suit one downstream format would be the wrong trade -- so the fix
belongs at the rendering layer, i.e. here. Any other module that renders these
strings into a line-oriented format needs its own equivalent; nothing upstream
provides it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence

from hfss_agent.contract import ComplexSample, ProvenanceRecord, SolvedData

# Touchstone v1.0 puts at most four complex pairs on a line for N >= 3.
_MAX_PAIRS_PER_LINE = 4

# Continuation and subsequent-matrix-row lines are indented by a FIXED amount
# rather than padded to align under the first data column of the frequency line.
# Touchstone parsers ignore leading whitespace entirely, so neither is more
# correct; a fixed indent is chosen because it makes the output byte-identical
# regardless of how wide a frequency value happens to print, which keeps exports
# diffable and keeps this module's tests exact rather than approximate.
_CONTINUATION_INDENT = " " * 8

# The canonical S-parameter key spelling, e.g. "S(2,1)", matched STRICTLY: no
# lower-case "s", no internal or surrounding whitespace, nothing else.
#
# WHY STRICT, WHEN LENIENT PARSING WOULD COST NOTHING TO GET RIGHT. SolvedData's
# docstring fixes "S(1,1)" as the canonical form, but nothing in the code
# enforces it: the real adapter builds its keys directly from
# ``data.expressions`` and normalises none of them, so "keys are canonical" is an
# ASSUMPTION about what PyAEDT emits, not a guarantee we make. It has never been
# checked against a live AEDT session.
#
# A tolerant regex would quietly absorb the moment that assumption turns out to
# be wrong, and the discovery would be lost -- the export would succeed and
# nobody would learn that PyAEDT spells an expression differently than we
# expected. Strict parsing turns the same moment into a named failure at Phase
# 5.2 live validation, which is exactly where an unverified assumption about the
# solver should surface. Refusing costs one loud bug report; absorbing costs the
# knowledge.
_S_PARAM_KEY = re.compile(r"^S\((\d+),(\d+)\)$")

# Characters that must never survive into a "!" comment or a CSV field. C0
# controls plus DEL: the newline is the dangerous one (it would end a comment
# and start a data line), the rest are stripped with it because there is no
# reason for any of them to be in a project name.
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


class ExportContentError(ValueError):
    """Export content could not be generated from the supplied data.

    A ``ValueError`` subclass, so ``except ValueError`` still catches it and the
    refusals here read the same way as ``sparams``'. Named separately so a caller
    assembling an export can distinguish "this S-matrix cannot be exported" from
    an unrelated value error raised further down.
    """


def touchstone_content(
    solved_data: SolvedData, provenance: ProvenanceRecord
) -> str:
    """A complete Touchstone v1.0 file body, as a string.

    The option line is fixed at ``# HZ S RI R <Z0>``, and each choice in it is
    made to avoid losing precision rather than to look conventional:

      * ``HZ`` -- no unit scaling. ``SolvedData.frequencies`` is already
        normalised to Hz by the adapter, so writing Hz means no multiply and no
        rounding between the solver's number and the file's.
      * ``S`` -- scattering parameters, which is what ``SolvedData`` carries.
      * ``RI`` -- real/imaginary. ``ComplexSample`` stores ``real`` + ``imag``
        natively, so RI is a straight copy; MA or DB would require a conversion
        that cannot round-trip exactly.
      * ``R <Z0>`` -- the reference impedance, read from
        ``provenance.reference_impedance``. Never defaulted, and 50 is never
        assumed.

    Z0 IS READ FROM THE PROVENANCE, NOT TAKEN AS A SECOND ARGUMENT. The header
    below must state the reference impedance too, and a separate parameter would
    create two sources for one number that could disagree -- leaving the option
    line and the comment block contradicting each other inside a single file,
    with no way for a reader to tell which was authoritative.

    Numbers are written at Python's default float repr, which round-trips
    exactly. Nothing is truncated or rounded: precision lost in an export is data
    lost, and a value that no longer matches the solver's is no longer a
    measurement.

    Raises:
        ExportContentError: if the S-matrix is incomplete, the keys do not parse,
            a series is misaligned with the frequency array, or the frequencies
            are not strictly increasing.
    """
    port_count, grid = _port_grid(solved_data)
    lines = _provenance_comment_lines(provenance, port_count)
    lines.append(
        f"# HZ S RI R {_number(provenance.reference_impedance)}"
    )
    for index, frequency in enumerate(solved_data.frequencies):
        lines += _touchstone_point_lines(
            solved_data, grid, port_count, index, frequency
        )
    return "".join(f"{line}\n" for line in lines)


def touchstone_port_count(solved_data: SolvedData) -> int:
    """The port count a Touchstone filename must encode, e.g. 2 for ``.s2p``.

    PURE DELEGATION TO ``_port_grid``, WHICH IS THE POINT. Touchstone's extension
    carries the port count, only this module can derive it from the S-parameter
    key names, and the broker owns the write -- so something has to cross that
    gap. This function is that something, and it is deliberately three lines over
    the SAME inference the content generators use rather than a second one.

    Why single-sourcing matters more here than the line count suggests:
    ``_matrix_rows`` writes COLUMN-major order for 2-port and ROW-major for every
    other count (see the comment there). A filename that disagrees with the data
    is therefore not cosmetic -- a 4-port file named ``.s2p`` is read with the
    wrong convention and S21/S12 trade places silently, with nothing in the file
    to reveal it. A second inference path could drift from the first and produce
    exactly that.

    THE MISMATCH POLICY IS NOT DECIDED HERE, AND MUST NOT BE. What to do when the
    caller's requested path disagrees with this number -- refuse, warn, or write
    it anyway -- is the ``export_results`` tool's decision at Step 3.4, which owns
    the request, the path, and the ``ExportRefused`` arms that could carry a
    refusal. This function reports a fact and takes no position on it.

    CALLED BY NOTHING BUT ITS OWN TEST UNTIL STEP 3.4. That is a deliberate
    trade, not an oversight, and it follows the precedent W-6 set with
    ``native_template_text``: the derivation belongs beside the code whose
    ordering convention makes it consequential, and the alternative is that Step
    3.4 either re-implements it or makes ``_port_grid`` public then.

    Raises:
        ExportContentError: for exactly the reasons ``touchstone_content`` does --
            the count cannot be honestly reported for a matrix that could not be
            honestly exported.
    """
    port_count, _ = _port_grid(solved_data)
    return port_count


def csv_content(solved_data: SolvedData, provenance: ProvenanceRecord) -> str:
    """A complete CSV export, as a string: one header row, one row per frequency.

    COLUMN LAYOUT -- data first, provenance trailing, one flat table:

        frequency_hz,
        "S(1,1)_real", "S(1,1)_imag", "S(1,2)_real", ... (row-major, all N x N),
        project, design, setup, sweep, variation, variation_hash,
        solve_timestamp, reference_impedance_ohm, wrapper_version,
        contract_version

    PROVENANCE IS CARRIED AS REPEATED TRAILING COLUMNS, not as a comment
    preamble. CSV has no comment convention -- a leading "#" block is a local
    habit, not a standard, and it makes the file unreadable to the ordinary
    single-table readers (a spreadsheet, ``csv.DictReader``, a dataframe loader)
    that are the entire reason someone asked for CSV instead of Touchstone.
    Repeating the values costs redundancy and buys two things worth more than it:
    the file stays a valid RFC-4180 table needing no special handling, and every
    row stays self-describing, so a row cannot be sliced out of the file and
    separated from the solve it came from.

    THE S-PARAMETER COLUMNS ARE ROW-MAJOR AT EVERY PORT COUNT, including 2-port.
    This deliberately does NOT mirror ``touchstone_content``'s 2-port
    transposition: that transposition is a v1.0 file-format legacy (see
    ``_touchstone_point_lines``), and CSV has no such legacy to honour. Columns
    are self-labelling here, so order carries no meaning a reader must know.

    Headers use the contract's own key spelling, ``S(r,c)_real`` /
    ``S(r,c)_imag``, rather than a flattened ``S11_real``. At N >= 10 the
    flattened form is ambiguous -- "S111" could be S(1,11) or S(11,1) -- and this
    module is general N-port. The parentheses and comma force RFC-4180 quoting,
    which is correct and handled below.

    Raises:
        ExportContentError: for the same reasons ``touchstone_content`` does.
    """
    port_count, grid = _port_grid(solved_data)
    ordered = _row_major_keys(port_count)

    provenance_headers = [
        "project",
        "design",
        "setup",
        "sweep",
        "variation",
        "variation_hash",
        "solve_timestamp",
        "reference_impedance_ohm",
        "wrapper_version",
        "contract_version",
    ]
    provenance_values = [
        _clean(provenance.project),
        _clean(provenance.design),
        _clean(provenance.setup),
        _clean(provenance.sweep),
        _variation_text(provenance),
        _clean(provenance.variation.variation_hash),
        provenance.solve_timestamp.isoformat(),
        _number(provenance.reference_impedance),
        _clean(provenance.wrapper_version),
        _clean(provenance.contract_version),
    ]

    headers = ["frequency_hz"]
    for row, column in ordered:
        headers += [f"S({row},{column})_real", f"S({row},{column})_imag"]
    headers += provenance_headers

    rows = [headers]
    for index, frequency in enumerate(solved_data.frequencies):
        row_values = [_number(frequency)]
        for key in ordered:
            sample = solved_data.s_parameters[grid[key]][index]
            row_values += [_number(sample.real), _number(sample.imag)]
        rows.append(row_values + provenance_values)

    return "".join(
        ",".join(_csv_field(value) for value in row) + "\n" for row in rows
    )


# --- Touchstone line assembly -------------------------------------------------


def _touchstone_point_lines(
    solved_data: SolvedData,
    grid: dict[tuple[int, int], str],
    port_count: int,
    index: int,
    frequency: float,
) -> list[str]:
    """The one or more lines describing a single frequency point."""
    matrix_rows = _matrix_rows(solved_data, grid, port_count, index)

    lines: list[str] = []
    first_chunk = True
    for row in matrix_rows:
        # Each matrix ROW starts a new line; a row longer than four pairs then
        # continues onto further lines of its own.
        for chunk in _chunks(row, _MAX_PAIRS_PER_LINE):
            values = " ".join(
                f"{_number(sample.real)} {_number(sample.imag)}" for sample in chunk
            )
            if first_chunk:
                lines.append(f"{_number(frequency)} {values}")
                first_chunk = False
            else:
                lines.append(f"{_CONTINUATION_INDENT}{values}")
    return lines


def _matrix_rows(
    solved_data: SolvedData,
    grid: dict[tuple[int, int], str],
    port_count: int,
    index: int,
) -> list[list[ComplexSample]]:
    """The S-matrix at one frequency, split into the rows Touchstone expects."""
    if port_count == 2:
        # THE 2-PORT ORDER IS S11 S21 S12 S22 -- TRANSPOSED, AND THIS IS NOT A
        # BUG. Touchstone v1.0 specifies column-major order for 2-port files and
        # row-major for every other port count. The inconsistency is the format's
        # own, dating from the original .s2p convention, and every tool that
        # reads .s2p expects it. "Correcting" this to row-major would silently
        # swap S21 and S12 in every 2-port file this module writes -- which for
        # an asymmetric network means the insertion loss and the reverse
        # isolation trade places, with nothing in the file to reveal it.
        # If you are here to fix it: don't. Check the v1.0 spec first.
        return [
            [
                solved_data.s_parameters[grid[(1, 1)]][index],
                solved_data.s_parameters[grid[(2, 1)]][index],
                solved_data.s_parameters[grid[(1, 2)]][index],
                solved_data.s_parameters[grid[(2, 2)]][index],
            ]
        ]
    # N == 1 collapses to a single row of one pair; N >= 3 is row-major, one
    # matrix row at a time. Both fall out of the same expression.
    return [
        [
            solved_data.s_parameters[grid[(row, column)]][index]
            for column in range(1, port_count + 1)
        ]
        for row in range(1, port_count + 1)
    ]


def _provenance_comment_lines(
    provenance: ProvenanceRecord, port_count: int
) -> list[str]:
    """The "!"-prefixed header block. "!" comments are standard in v1.0.

    Every value passes through ``_clean`` first -- see the module docstring for
    why a newline reaching this block is a data-forgery risk rather than a
    cosmetic one.
    """
    return [
        f"! Touchstone 1.0 ({port_count}-port) generated by hfss-agent",
        f"! project: {_clean(provenance.project)}",
        f"! design: {_clean(provenance.design)}",
        f"! setup: {_clean(provenance.setup)}",
        f"! sweep: {_clean(provenance.sweep)}",
        f"! variation: {_variation_text(provenance)}",
        f"! variation_hash: {_clean(provenance.variation.variation_hash)}",
        f"! solve_timestamp: {provenance.solve_timestamp.isoformat()}",
        f"! reference_impedance_ohm: {_number(provenance.reference_impedance)}",
        f"! wrapper_version: {_clean(provenance.wrapper_version)}",
        f"! contract_version: {_clean(provenance.contract_version)}",
    ]


# --- the S-matrix grid --------------------------------------------------------


def _port_grid(solved_data: SolvedData) -> tuple[int, dict[tuple[int, int], str]]:
    """Infer the port count from the key names and prove the matrix is complete.

    Returns the port count and a ``(row, column) -> original key`` map, so the
    callers above can index the matrix positionally while still reading values
    out of ``s_parameters`` under the exact key it supplied.
    """
    frequencies = solved_data.frequencies
    if not frequencies:
        raise ExportContentError("no frequencies to export")
    for index in range(1, len(frequencies)):
        if frequencies[index] <= frequencies[index - 1]:
            raise ExportContentError(
                "frequencies must be strictly increasing to export; "
                f"index {index} ({frequencies[index]!r}) does not exceed "
                f"index {index - 1} ({frequencies[index - 1]!r})"
            )
    if not solved_data.s_parameters:
        raise ExportContentError("no S-parameters to export")

    grid: dict[tuple[int, int], str] = {}
    non_canonical: list[str] = []
    for key in solved_data.s_parameters:
        match = _S_PARAM_KEY.match(key)
        if match is None:
            non_canonical.append(key)
            continue
        # THE DUPLICATE CHECK SURVIVES STRICT PARSING, and is not dead code.
        # ``\d+`` still accepts leading zeros, so "S(01,1)" and "S(1,1)" are both
        # canonical by the regex yet both resolve to position (1, 1). Two keys
        # can therefore still collide, and which of them to export would be
        # arbitrary.
        position = (int(match.group(1)), int(match.group(2)))
        if position in grid:
            raise ExportContentError(
                f"S-parameter {position[0]},{position[1]} is supplied twice, as "
                f"{grid[position]!r} and {key!r}; which one to export is "
                "ambiguous"
            )
        grid[position] = key
    if non_canonical:
        raise ExportContentError(
            f"S-parameter key(s) {sorted(non_canonical)!r} are not in canonical "
            "S(row,column) form. The canonical spelling is an unverified "
            "assumption about what PyAEDT emits, so this is more likely an "
            "upstream bug worth reporting than a file that needs a looser "
            "parser here"
        )
    if any(row == 0 or column == 0 for row, column in grid):
        raise ExportContentError(
            "S-parameter port indices are 1-based; a 0 index cannot be placed "
            f"in the matrix (got {sorted(grid)!r})"
        )

    port_count = max(max(position) for position in grid)
    missing = [key for key in _row_major_keys(port_count) if key not in grid]
    if missing:
        raise ExportContentError(
            f"the S-matrix is incomplete for {port_count} ports: missing "
            + ", ".join(f"S({row},{column})" for row, column in missing)
            + ". Exporting would mean inventing those entries, so it is refused"
        )

    expected = len(frequencies)
    for position, key in sorted(grid.items()):
        actual = len(solved_data.s_parameters[key])
        if actual != expected:
            raise ExportContentError(
                f"S({position[0]},{position[1]}) has {actual} samples but there "
                f"are {expected} frequencies; the series must align "
                "index-for-index"
            )
    return port_count, grid


def _row_major_keys(port_count: int) -> list[tuple[int, int]]:
    """Every ``(row, column)`` of an N x N matrix, row-major."""
    return [
        (row, column)
        for row in range(1, port_count + 1)
        for column in range(1, port_count + 1)
    ]


# --- formatting ---------------------------------------------------------------


def _number(value: float) -> str:
    """A float at full round-trippable precision -- Python's default repr.

    Not formatted to a fixed number of decimals: a rounded export no longer
    matches the solver's own numbers, and the difference is undetectable once the
    file has left this process.
    """
    return repr(float(value))


def _clean(value: str) -> str:
    """Replace every control character in an untrusted string with a space.

    NOT a duplicate of the adapter's sanitizer, and not defence in depth: the
    adapter deliberately KEEPS tab and newline (see the module docstring), so the
    newline this neutralises genuinely arrives intact from a real read. This is
    the layer that closes it for an export.

    REPLACED WITH A SPACE, NOT DELETED. Deleting would join the text either side
    of the newline into a single word -- "patch\\nantenna" would read as
    "patchantenna", a name that was never in the design. A space preserves the
    token boundary, so the rendered value still reads as what was there.
    """
    return _CONTROL_CHARACTERS.sub(" ", value)


def _variation_text(provenance: ProvenanceRecord) -> str:
    """The variation map as ``name=value; name=value``, in sorted name order.

    Sorted so the same variation always renders identically regardless of dict
    ordering upstream -- an export that differs run to run cannot be compared.
    """
    values = provenance.variation.values
    return "; ".join(
        f"{_clean(name)}={_clean(values[name])}" for name in sorted(values)
    )


def _csv_field(value: str) -> str:
    """One RFC-4180 field: quoted when it must be, with internal quotes doubled.

    Hand-rolled rather than taken from the ``csv`` module, which writes through a
    file-like object; keeping this module free of anything that even resembles a
    write target is worth five lines. Control characters are already gone by the
    time a value reaches here, so the cases left are the quote and the comma.

    THE DOUBLING IS WRITTEN AS split/join, NOT ``str.replace``, AND MUST STAY
    THAT WAY. ``tests/boundary/test_file_io_audit.py`` flags ``.replace(...)`` on
    any receiver, because ``Path.replace`` (which overwrites a file) and
    ``str.replace`` are indistinguishable in an AST. That over-breadth is
    deliberate and documented there, and it is the correct trade for a repo whose
    central claim is that only the broker touches the disk. So this reads a
    little long for what it does; simplifying it to ``value.replace('"', '""')``
    will fail CI, and the audit is not the thing to change.
    """
    if any(character in value for character in ('"', ",", "\n", "\r")):
        escaped = '""'.join(value.split('"'))
        return f'"{escaped}"'
    return value


def _chunks(
    values: Sequence[ComplexSample], size: int
) -> Iterator[Sequence[ComplexSample]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]
