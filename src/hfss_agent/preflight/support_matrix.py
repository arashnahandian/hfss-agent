"""W-11's image of ``docs/support-matrix.md``: the boundaries, and the rules
that read them (System Design §1.1 W-11, ADR-26 decision 18(d)).

THE DOCUMENT IS THE SPECIFICATION AND THIS MODULE IS ITS IMAGE, never the
other way round. The matrix landed before this file for that reason: writing
the classifier first would have meant inventing the bands and back-filling the
doc to match, inverting which artifact is authoritative. A band changed here
without changing the document is a defect even when every test passes.

IMPORT-LIGHT ON PURPOSE — ``re``, ``typing`` and ``collections.abc``, and
nothing else in the standard library or this package. Nothing here reads the
environment, the filesystem, or installed metadata; those live in ``probes.py``
behind the injection seam, and a test pins that this module names none of them.
That split is what lets every band be tested without a machine that has AEDT on
it, which is the whole reason W-11's suite runs identically on a Windows laptop
with PyAEDT and no AEDT and on a Linux runner with neither.

WHAT IS NOT HERE: the six ``ComponentCheck`` rows, ``overall``, and the
rendered text. Those are the assembler's, and they consume this module rather
than duplicating it.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from typing import Literal

# The published matrix this module implements. A PUBLISHED VALUE: it is what
# every ``PreflightReport.support_matrix_ref`` carries, so renaming or moving
# the document turns every report's reference into a dead link. A test resolves
# this against the repo and fails if nothing is there, so a rename breaks CI
# rather than shipping a broken pointer.
#
# A CITATION, NOT A RESOLVABLE PATH. The wheel packages ``src/hfss_agent`` only
# (pyproject's ``[tool.hatch.build.targets.wheel]``), so ``docs/`` does not ship
# with an installed distribution. On a user's machine this string names the
# document a human can look up in the repo; it is not a file the running code
# can open, and nothing here or downstream may treat it as one.
SUPPORT_MATRIX_REF = "docs/support-matrix.md"

# (year, release) — e.g. AEDT 2026 R1 is ``(2026, 1)``, Python 3.12 is
# ``(3, 12)``. See ``classify_aedt`` for why these are int tuples and not the
# floats PyAEDT itself compares.
AedtVersion = tuple[int, int]
PythonVersion = tuple[int, int]
PyaedtVersion = tuple[int, int]

# The matrix's support-status vocabulary, defined in the document's preamble.
# ``validated`` is deliberately absent: it is defined in the document so the
# word has a fixed meaning, and no row anywhere holds it, because the live pass
# has not run.
SupportStatus = Literal["target", "expected", "beyond-pin", "unsupported"]

# ``ComponentCheck.status`` restricted to the two a REQUIRED component can
# reach. ``unavailable`` is absent by design and this module can never return
# it: every required component is structurally determinable, and the contract
# refuses to construct a report claiming otherwise.
ComponentStatus = Literal["ok", "incompatible"]


# --- the boundaries, read off the published matrix ---------------------------
#
# NOT DERIVED FROM PyAEDT'S ``CURRENT_STABLE_AEDT_VERSION``, AND THAT IS THE
# LOAD-BEARING PROPERTY OF THIS BLOCK. That constant currently holds 2026.1 as
# well, which makes deriving the anchor from it look free. It is not:
#
#   * the two mean different things. The constant means "the newest AEDT this
#     PyAEDT build knew about"; the anchor means "the version this product is
#     built against". They share a number today by coincidence.
#   * the constant is hand-maintained and expected to move — PyAEDT's own module
#     docstring says it "should be updated every time a new stable version is
#     released" — so it is frozen only by our ``pyaedt==1.2.*`` pin. Deriving
#     from it would let a dependency bump silently redefine "target".
#   * it is a ``float``, not a version. PyAEDT compares it as ``float(v[:6])``.
#
# So the anchor is a literal here, and a test asserts the string
# ``CURRENT_STABLE_AEDT_VERSION`` appears nowhere under ``src/``. The pin test
# proves the value; that AST test proves the independence.
AEDT_ANCHOR: AedtVersion = (2026, 1)

# Our floor, standing on PyAEDT's warning. PyAEDT only WARNS below 2022 R2 and
# raises only below 2019, so a 2021.2 install still attaches — this project
# chose to make that number blocking. See the matrix's own section; a reader who
# takes this for PyAEDT's refusal will conclude the check is redundant.
AEDT_FLOOR: AedtVersion = (2022, 2)

# Python: an ecosystem-maturity choice, NOT a PyAEDT limit. PyAEDT 1.2.0's
# metadata is ``Requires-Python: <4,>=3.10`` and it claims support through 3.14;
# a Phase 0 wheels-only resolution found 3.10-3.14 all resolving to prebuilt
# Windows wheels (ADR-13). The ceiling is ours. Kept in step with pyproject's
# ``requires-python = ">=3.10,<3.13"``.
PYTHON_TARGET: PythonVersion = (3, 12)
PYTHON_FLOOR: PythonVersion = (3, 10)
PYTHON_CEILING_EXCLUSIVE: PythonVersion = (3, 13)

# The ``live`` extra's actual pin, ``pyaedt==1.2.*``. Every PyAEDT source line
# this project cites was read under it.
PYAEDT_PIN: PyaedtVersion = (1, 2)

# The one environment-variable prefix whose branch needs a filesystem check
# before the install counts. Named here rather than in ``probes.py`` because the
# parse below has to know the same four prefixes; the SUBDIRECTORY it checks for
# is a filesystem detail and stays with the probe.
AWP_ROOT_PREFIX = "AWP_ROOT"

# The four prefixes PyAEDT's own install scan recognises
# (``list_installed_ansysem``), and nothing else — no registry read, no bundled
# default. The three trailing digits are the version.
_AEDT_ENV_VAR = re.compile(
    r"(?:ANSYSEM_ROOT|ANSYSEM_PY_CLIENT_ROOT|ANSYSEMSV_ROOT|AWP_ROOT)(\d{3})"
)

# A leading ``major.minor``, with anything non-numeric after it ignored:
# ``3.12.10`` -> (3, 12), ``1.2.0`` -> (1, 2), ``1.3.0rc1`` -> (1, 3).
_DOTTED_VERSION = re.compile(r"(\d+)\.(\d+)(?:[^0-9].*)?")


def parse_aedt_env_var_name(name: str) -> AedtVersion | None:
    """The AEDT version an install-root variable NAME encodes, or None.

    THE NAME IS THE WHOLE INPUT, and that is a deliberate property rather than a
    convenience: the version is rebuilt from two integers matched out of
    ``\\d{3}``, so no byte of any environment VALUE reaches the parsed version,
    the reported ``detected`` string, or the rendered text. A probe that returns
    only keys cannot leak a value, and this is the half of that guarantee that
    lives in the classifier.

    Mirrors PyAEDT's own derivation (``AedtVersions.installed_versions``),
    including its pre-2020 adjustment, so our reported version matches the key
    PyAEDT would compute for the same machine:

      * ``ANSYSEM_ROOT261`` -> (2026, 1)
      * ``AWP_ROOT222`` -> (2022, 2)
      * ``ANSYSEM_ROOT193`` -> (2019, 1)   (release 3 and up: release -= 2)
      * ``ANSYSEM_ROOT192`` -> (2018, 2)   (release below 3: year -= 1)

    The legacy branch matters less than it looks — everything it produces is
    below ``AEDT_FLOOR`` and classifies as ``unsupported`` either way — but it is
    mirrored so the version we NAME in a report is the one PyAEDT would name,
    rather than a number no tool agrees with.

    Student (``ANSYSEMSV_ROOT``) and client (``ANSYSEM_PY_CLIENT_ROOT``) roots
    parse to the same version as a full install. The matrix draws no
    student/full distinction, so neither does this.
    """
    match = _AEDT_ENV_VAR.fullmatch(name)
    if match is None:
        return None
    digits = match.group(1)
    year_digits = int(digits[0:2])
    release = int(digits[2])
    if year_digits < 20:
        if release < 3:
            year_digits -= 1
        else:
            release -= 2
    return (2000 + year_digits, release)


def parse_dotted_version(text: str) -> tuple[int, int] | None:
    """The leading ``major.minor`` of a dotted version string, or None.

    Total: every input returns, and an unparseable one returns None rather than
    raising, so a damaged version string cannot break a probe's totality.

    KNOWN NARROWNESS, STATED: a PEP 440 epoch (``1!2.0``) does not parse, and
    reports as unparseable rather than as version 2.0. No distribution this
    project pins uses one; if that changes, this is the line to widen, and a
    silently wrong parse would be worse than the refusal.
    """
    match = _DOTTED_VERSION.fullmatch(text)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)))


def format_aedt_version(version: AedtVersion) -> str:
    """``(2026, 1)`` -> ``"2026.1"`` — the spelling AEDT and PyAEDT both use."""
    year, release = version
    return f"{year}.{release}"


def classify_aedt(version: AedtVersion) -> SupportStatus:
    """One AEDT version's band, per the matrix's AEDT table.

    INT TUPLES, NOT FLOATS, and the difference is not stylistic. PyAEDT compares
    versions as ``float(v[:6])``; on that comparison a hypothetical 2022 R10
    parses to ``2022.1`` and sorts BELOW ``2022.2``, putting a newer release
    under our floor. No AEDT release has reached R10, which is exactly why this
    is worth fixing now rather than after it bites: today the two orderings
    agree, so the change is free and unobservable.

    Four bands, total and ordered, each unconfirmed for its own reason (the
    matrix says which):

      * below the floor            -> ``unsupported``
      * floor up to the anchor     -> ``expected``
      * exactly the anchor         -> ``target``
      * above the anchor           -> ``beyond-pin``
    """
    if version < AEDT_FLOOR:
        return "unsupported"
    if version < AEDT_ANCHOR:
        return "expected"
    if version == AEDT_ANCHOR:
        return "target"
    return "beyond-pin"


def classify_python(version: PythonVersion) -> SupportStatus:
    """One Python version's band, per the matrix's Python table.

    ``beyond-pin`` is reachable at runtime even though ``requires-python`` would
    have refused the install: this describes the interpreter that is RUNNING, and
    if it is running the pin was already bypassed (a direct ``PYTHONPATH``, a
    vendored copy, a forced install). Reporting it is the point.
    """
    if version < PYTHON_FLOOR:
        return "unsupported"
    if version >= PYTHON_CEILING_EXCLUSIVE:
        return "beyond-pin"
    if version == PYTHON_TARGET:
        return "target"
    return "expected"


def classify_pyaedt(version: PyaedtVersion) -> SupportStatus:
    """One PyAEDT version's band, per the matrix's PyAEDT table.

    There is no ``expected`` band here and that is not an omission: the pin is a
    single minor (``==1.2.*``), so there is no range between a floor and the
    target for a version to sit in. Anything below the pin is ``unsupported``,
    anything above is ``beyond-pin``.
    """
    if version < PYAEDT_PIN:
        return "unsupported"
    if version == PYAEDT_PIN:
        return "target"
    return "beyond-pin"


def component_status(support: SupportStatus) -> ComponentStatus:
    """The ``ComponentCheck.status`` a support status maps to.

    THREE OF THE FOUR BANDS MAP TO ``ok``, and ``beyond-pin`` doing so is the
    non-obvious one, so it is stated rather than left to be inferred: a user on
    an AEDT newer than the anchor gets ``overall="ok"`` with the caveat in the
    row's detail. Blocking them would be the mistake ADR-26 decision 5 names —
    PyAEDT's ``__check_version`` raises only when ``current_version`` AND
    ``latest_version`` are both empty, and ``latest_version`` is unfiltered, so a
    future-version-only machine is NOT rejected by PyAEDT and an attach may well
    proceed. Reporting it as incompatible would refuse a machine the dependency
    accepts.

    Only ``unsupported`` blocks, because only there does a floor say the
    combination is one this project will not stand behind.
    """
    return "incompatible" if support == "unsupported" else "ok"


def aggregate_installed_aedt_status(
    versions: Collection[AedtVersion],
) -> ComponentStatus:
    """THE MULTI-INSTALL RULE: the ``aedt`` verdict for a whole installed set.

    A NAMED RULE WITH NO ADR BEHIND IT — decided at Step 2.4b Part 2 and
    recorded in ADR-27, never cited as inherited. ADR-26 decision 18(e) fixes
    the IDENTITY rule (which version may be REPORTED: exactly one install, or an
    attached session); it says nothing about which VERDICT a set of several
    deserves, and that question only appears once something has to classify a
    machine with two installs.

    THE RULE: supported if ANY installed version is, absent is incompatible,
    and only an all-unsupported set blocks.

    THE REASONING, in code because a reader must not have to reconstruct it from
    an ``any(...)``. PyAEDT resolves which install an attach binds to by
    matching the TARGET PROCESS against each installed version in turn — so on a
    machine carrying 2021.2 and 2026.1, attaching to a 2026.1 process is an
    entirely supported session. Blocking that machine would refuse a working
    configuration on the strength of an unrelated old install sitting beside it,
    which is over-reporting: preflight would tell a user their environment
    cannot work while it demonstrably can.

    THE COST, STATED: the mirror case is real. Attaching to the 2021.2 process
    on that same machine gives an unsupported session that this row called
    ``ok``. That is accepted because preflight runs BEFORE any attach and cannot
    know which process will be chosen — and because the honest signal is
    already carried elsewhere: the identity rule leaves ``aedt_version`` as None
    for a multi-install machine, and every installed version is named in the
    row's ``detected``, so a reader sees the 2021.2 sitting there. Naming the
    ambiguity beats guessing which side of it to fail on.

    An EMPTY set is ``incompatible``, not undetermined. Absence is a
    determination: with no install root, PyAEDT's own ``__check_version`` raises
    and attach is IMPOSSIBLE, not merely unverified (ADR-26 decision 5).

    Routed through ``classify_aedt`` + ``component_status`` rather than
    comparing to ``AEDT_FLOOR`` directly, so this rule cannot drift from the
    single-version bands it aggregates; a test asserts the two agree on every
    one-element set.
    """
    if not versions:
        return "incompatible"
    if any(
        component_status(classify_aedt(version)) == "ok" for version in versions
    ):
        return "ok"
    return "incompatible"
