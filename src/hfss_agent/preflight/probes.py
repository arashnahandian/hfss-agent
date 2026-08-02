"""W-11's four in-process probes, and the seam that keeps them out of tests.

THE ONLY MODULE IN ``preflight`` THAT TOUCHES THE MACHINE. Everything here reads
``os.environ``, ``platform``, ``importlib.metadata`` or (once, narrowly) the
filesystem; nothing else in the package names any of them, and a test pins that.
No ``pyaedt`` import occurs anywhere on this path — ADR-26 decision 1 settles
that preflight does not reach the AEDT API at all, which is why W-11 adds no
adapter operation and registers no capability.

TOTAL BY CONSTRUCTION (ADR-26 decision 18(a)). Every probe returns a value and
none raises. That is a requirement rather than a style, because
``preflight_environment``'s response has NO ``cannot_evaluate`` arm and no
refusal arm: a probe that raised would surface as a traceback on the first tool
of Journey 1.0, on the machine least likely to be healthy — the one preflight
exists to describe. ``python_version`` is the one deliberate exception to the
blanket ``try``; see its docstring.

THE DUPLICATION WITH ``adapter/real`` IS FORCED, NOT LAZY. The real adapter has
its own wrapper-version read, and no shared helper is possible: ``preflight``
may import ``broker`` and ``contract`` only, ``hfss_agent.adapter`` is on every
sibling's forbidden list, and a version probe is not a contract schema (ADR-26
alternative (h)). A maintainer who tries to unify them will fail and be tempted
to weaken an audit to make it work. Do not.

Recorded because this file is the reason it was found: the shipped adapter's
equivalent catches only ``PackageNotFoundError`` and so lets a ``None`` through
into a ``-> str`` function. That defect is real, is logged, and is not fixed
here — 2.4b opens no adapter file — but the probes below must not reproduce it,
which is why every metadata read checks ``is None`` as well as catching.
"""

from __future__ import annotations

import importlib.metadata
import os
import platform
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from hfss_agent.preflight.support_matrix import (
    AWP_ROOT_PREFIX,
    parse_aedt_env_var_name,
)

# The subdirectory an ``AWP_ROOT*`` root must contain before PyAEDT counts it as
# an AEDT install. A filesystem detail, so it lives with the probe rather than
# with the bands.
_ANSYSEM_SUBDIRECTORY = "AnsysEM"

# The distributions the two metadata probes read. ``hfss-agent`` is this
# package's own name as published, hyphenated (pyproject's ``[project].name``).
_PYAEDT_DISTRIBUTION = "pyaedt"
_WRAPPER_DISTRIBUTION = "hfss-agent"

# The established fallback when this package's own metadata is absent or
# unreadable, matching what the contract's ``PreflightEnvironment`` docstring
# names. A real value would be better and there is none to be had: the code is
# demonstrably running, so refusing to report a wrapper version would be less
# honest than a marked placeholder.
WRAPPER_VERSION_FALLBACK = "0.0.0"

# The conservative shape a distribution version must have to be REPORTED.
#
# WHY A SHAPE CHECK EXISTS AT ALL, since nothing else in W-11 needs one. The
# rest of this module's output cannot carry foreign bytes: an AEDT version is
# rebuilt from two integers matched out of a ``\d{3}`` key name, and
# ``platform.python_version()`` is interpreter-sourced. ``importlib.metadata``
# is the exception — it returns whatever a ``.dist-info/METADATA`` ``Version:``
# field holds, which is arbitrary text this package did not write, and which is
# PRECISELY the damaged-metadata case preflight exists to describe.
#
# WHY HERE AND NOT AT THE RENDERER. W-11 renders no ``UntrustedStr``: the
# contract types all four ``Environment`` version fields as plain ``str``, and
# W-5 and W-6 both frame untrusted text rather than rewriting it (only
# ``export`` rewrites, because a Touchstone file is machine-parsed and a newline
# there forges a measurement). Guarding at the renderer would invent a third
# pattern for a problem that is really an input one. This sits at the layer that
# already owns the ``is None`` check, and it makes the reported ``detail``
# MORE precise rather than less: a version that fails this check is reported as
# ``unreadable``, which is exactly what it is.
#
# The character set is PEP 440's alphabet (digits, letters, ``. _ + ! -``) and
# nothing else — no whitespace, no newline, no shell metacharacter, no control
# character — capped at 64, which is far above any real version and far below
# anything that could crowd a rendered line.
_VERSION_SHAPE = re.compile(r"[0-9A-Za-z._+!-]{1,64}")

VersionReadState = Literal["found", "absent", "unreadable"]


@dataclass(frozen=True)
class VersionRead:
    """One distribution version read, and WHICH KIND of answer it is.

    A NULLABLE STRING CANNOT CARRY THIS, which is why the type exists. ADR-26
    decision 18(b) requires "metadata present but unreadable" to stay
    distinguishable from "not installed" in what the report says, and both are
    ``None``:

      * ``found`` — a version was read and has a plausible shape.
      * ``absent`` — no such distribution is installed. A DETERMINATION, not a
        gap: it is the answer, and for a required component it means
        ``incompatible``.
      * ``unreadable`` — something is installed but its metadata could not be
        turned into a version. Also a determination, and a DIFFERENT one, with a
        different fix: reinstall a damaged package rather than install a missing
        one. Telling a user "PyAEDT is not installed" when it is installed and
        broken sends them somewhere that will not help.

    NO VALIDATOR ENFORCES ``version is not None`` IFF ``state == "found"``,
    deliberately, even though the repo's idiom elsewhere is to enforce exactly
    that kind of pair. A raising ``__post_init__`` would be reachable from
    inside a probe, and a probe that can raise is not total — the one property
    this module may not trade away. The invariant is held by the four literal
    construction sites below and pinned by a test over what the real probes
    actually return.
    """

    version: str | None
    state: VersionReadState


@dataclass(frozen=True)
class EnvironmentProbes:
    """The injection seam: the four reads, as data.

    EVERY FIELD IS REQUIRED, WITH NO DEFAULT, so a half-substituted set is
    unconstructible — a test cannot override two probes and silently inherit the
    host machine for the other two.

    Taken EXPLICITLY by the assembler rather than defaulting to
    ``REAL_PROBES``, following W-6's reasoning for taking its ``Broker``
    explicitly instead of reaching for an ambient one. The consequence is the
    point: with no default there is nothing for a forgotten argument to fall
    through to, so no test can read the host machine by omission. This matters
    concretely, because the machines disagree — a Windows development laptop may
    have PyAEDT and no AEDT, while a Linux CI runner has neither, and a suite
    that read either would assert different things in the two places.
    """

    aedt_env_var_names: Callable[[], frozenset[str]]
    pyaedt_version: Callable[[], VersionRead]
    python_version: Callable[[], str]
    wrapper_version: Callable[[], str]


def _has_ansysem_subdirectory(variable_name: str) -> bool:
    """Whether an ``AWP_ROOT*`` root actually contains an AEDT install.

    PERMITTED FILESYSTEM ACCESS, AND W-11 IS THE FIRST NON-BROKER MODULE TO USE
    IT — so the justification lives here, where a reader who greps ``os.path``
    outside the broker will land.

    THE BOUNDARY: metadata only. This asks whether a directory exists. It opens
    no file, reads no content, writes nothing, creates no handle, and mutates no
    namespace. The file-I/O audit draws its line at exactly that — content reads
    and namespace mutation — and self-tests ``os.path.isdir`` as legal
    (``tests/boundary/test_file_io_audit.py``); ``path`` is likewise in the
    narrow allowlist of ``os`` attributes this package may reach. CLAUDE.md's
    "only broker performs file I/O" governs the file surface those guards
    protect: opening, writing, deleting, renaming. An existence check acquires
    none of that and inherits none of the broker's guards because it needs none.
    Anything beyond this line — reading the directory's contents, listing it,
    opening a file inside it — belongs in the broker and must not be added here.

    WHY IT IS NEEDED AT ALL: PyAEDT's own install scan counts an ``AWP_ROOT``
    variable only when ``<root>/AnsysEM`` exists. Skipping the check would
    over-report an install PyAEDT will refuse, which is the worse error — it
    tells a user their environment is ready for an attach that cannot happen.

    ONE KNOWN DIVERGENCE FROM PyAEDT, taken deliberately: PyAEDT uses
    ``Path(...).exists()``, which is also true for a FILE named ``AnsysEM``,
    while ``isdir`` is not. On a machine with a file where a directory belongs we
    report no install and PyAEDT reports one. Under-reporting is the safer
    error, and ``isdir`` is what the check actually means, but it IS a
    disagreement with the dependency rather than a match — recorded in ADR-27
    and as a live-pass question, because only a real machine can say whether
    that shape occurs.
    """
    root = os.environ.get(variable_name)
    if not root:
        return False
    try:
        return os.path.isdir(os.path.join(root, _ANSYSEM_SUBDIRECTORY))
    except OSError:
        # A malformed root — an embedded null, a path past the OS limit — is not
        # an install. Dropping this one variable rather than the whole scan:
        # one broken entry must not hide the good ones beside it.
        return False


def real_aedt_env_var_names() -> frozenset[str]:
    """The AEDT install-root variable NAMES present on this machine.

    KEYS ONLY, AND TYPED AS A ``frozenset[str]`` TO KEEP IT THAT WAY. The names
    are sufficient — the version is encoded in the trailing three digits and
    ``parse_aedt_env_var_name`` rebuilds it from two integers — so no
    environment VALUE ever needs to leave this function, and none does. A probe
    that cannot return a value cannot leak one into a report, a rendered line, or
    a diagnostics bundle. The one value this function reads at all is an
    ``AWP_ROOT`` root, consumed inside ``_has_ansysem_subdirectory`` and reduced
    to a bool before it returns.

    Recognition is delegated to ``parse_aedt_env_var_name`` rather than
    duplicated: a name counts as an install root exactly when the classifier can
    read a version out of it, so the scan and the bands cannot drift apart.

    TOTAL: an empty ``frozenset`` is the answer for a machine with no AEDT, and
    it is a DETERMINATION rather than a failure — that is what makes the ``aedt``
    check ``incompatible`` instead of ``unavailable``.
    """
    try:
        names = set()
        for name in os.environ:
            if parse_aedt_env_var_name(name) is None:
                continue
            if name.startswith(AWP_ROOT_PREFIX) and not _has_ansysem_subdirectory(
                name
            ):
                continue
            names.add(name)
        return frozenset(names)
    except Exception:
        # The backstop, not the mechanism: per-variable failures are already
        # handled above. A hostile or broken ``os.environ`` mapping still must
        # not raise out of a probe, so the whole scan degrades to "no install
        # roots found" — the same answer a clean machine without AEDT gives, and
        # the report says what it means either way.
        return frozenset()


def _read_distribution_version(distribution: str) -> VersionRead:
    """One installed distribution's version, as a three-state answer.

    THE CATCH IS ``except Exception`` AND THERE IS ALSO AN ``is None`` CHECK,
    and neither substitutes for the other (ADR-26 decision 18(b)).
    ``importlib.metadata.version()`` RETURNS ``None`` — it does not raise — when
    a ``.dist-info`` exists with no ``Version:`` field, or no ``METADATA`` file
    at all. That ``None`` slips past any ``except``, however broad, and is
    exactly the damaged environment this tool exists to describe. Catching alone
    would miss it; checking alone would miss a metadata backend that throws.
    """
    try:
        raw = importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return VersionRead(None, "absent")
    except Exception:
        # Anything else — an unreadable metadata directory, a broken finder on
        # sys.meta_path, a permissions error — is "present but not readable",
        # never "not installed". The two send a user to different fixes.
        return VersionRead(None, "unreadable")
    if raw is None:
        return VersionRead(None, "unreadable")
    if _VERSION_SHAPE.fullmatch(raw) is None:
        return VersionRead(None, "unreadable")
    return VersionRead(raw, "found")


def real_pyaedt_version() -> VersionRead:
    """PyAEDT's installed version, or which kind of absence this is.

    ``absent`` is the ORDINARY case in this project's own CI, not an edge one:
    both OS legs run ``uv sync`` WITHOUT the ``live`` extra, so ``pyaedt`` is
    genuinely not installed there. That is a determination, and for a required
    component it means ``incompatible`` — the report describing the CI machine as
    unable to attach is correct, because it is.
    """
    return _read_distribution_version(_PYAEDT_DISTRIBUTION)


def real_python_version() -> str:
    """The running interpreter's version, e.g. ``"3.12.10"``.

    DELIBERATELY NOT WRAPPED IN A ``try``, and this is an interpretation of
    ADR-26 decision 18(a) rather than an exception to it — "none raises" reads
    universal, so the reasoning is written down.

    ``platform.python_version()`` formats ``sys.version_info``, which the
    interpreter always has because it is the interpreter. There is no failure
    mode to catch. A ``try`` here would need a fallback value, and any value it
    could return would be a FABRICATED VERSION reported as a measured one — the
    single thing this product must never do. That is strictly worse than the
    crash it would be preventing, because a crash is visible and a wrong version
    string is not.

    The contract agrees and says so: ``PreflightEnvironment.python_version`` is
    required with no absent state, "always determinable".
    """
    return platform.python_version()


def real_wrapper_version() -> str:
    """This package's own version, falling back to ``"0.0.0"``.

    Always a string, because the contract's ``wrapper_version`` has no absent
    state and needs none — this code is running, so a wrapper exists. The
    three-state read is still used underneath, so a damaged ``.dist-info`` takes
    the same path as a missing one rather than crashing; unlike the two
    component probes, nothing downstream consumes the distinction, because the
    wrapper is not one of the six checked components.
    """
    read = _read_distribution_version(_WRAPPER_DISTRIBUTION)
    if read.version is None:
        return WRAPPER_VERSION_FALLBACK
    return read.version


# The real machine reads, bundled. Named and exported so the Step 3.x tool has
# one obvious thing to pass, and so a test importing it is doing something
# visible rather than inheriting it by default.
REAL_PROBES = EnvironmentProbes(
    aedt_env_var_names=real_aedt_env_var_names,
    pyaedt_version=real_pyaedt_version,
    python_version=real_python_version,
    wrapper_version=real_wrapper_version,
)
