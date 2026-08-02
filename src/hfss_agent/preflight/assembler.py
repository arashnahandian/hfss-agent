"""W-11 assembly: the ``PreflightReport`` builder (System Design §1.1, §3, ADR-26).

Journey 1.0's first tool, and the only one that runs BEFORE an attach. It
answers one question — can this machine do the work — against the published
support matrix, and it answers it whether or not a session exists.

REACHES NOTHING. No adapter operation, no registered capability, no ``pyaedt``
import, no dispatch (ADR-26 decision 1). The machine reads arrive as injected
probes and the optional attached-session versions come through the broker's
non-dispatchable accessor, so **this tool writes no audit record** — the audit
log is written by ``Broker.dispatch``, and nothing here dispatches.

Layer 4 (§5): of the ``hfss_agent`` packages it imports ``broker`` and
``contract``, plus its own siblings ``preflight.probes`` and
``preflight.support_matrix``. A package importing its own submodules is not a
boundary break — ``test_preflight_import_audit.py`` allows ``hfss_agent.preflight``
explicitly alongside the other two, and forbids everything else. (W-6's assembler
carries the shorter phrase "imports broker and contract only"; that is accurate
THERE because it has no sibling submodules to reach, and copying it here would
have been false.)

ONE ARM, WHICH IS WHY THE PROBES MUST BE TOTAL. ``preflight_environment``
returns a ``PreflightReport`` or nothing at all — the response has no
``cannot_evaluate`` arm and no refusal arm, so there is no in-band way to say
"the check itself failed". That absence propagates backwards into two design
rules this module depends on: every probe returns a value and none raises
(ADR-26 decision 18(a)), and every required component is structurally
determinable. Where the three Layer-4 siblings each define an assembly
exception, this module defines none: with one arm, total probes, and no
dispatch boundary to narrow, there is no failure left for one to carry, and a
fourth duplicate of that class would exist only to re-raise.

WHAT ``overall`` MEANS, AND WHAT IT DOES NOT. It is computed here from the
required checks and never passed in (ADR-26 decision 18(c)); the contract then
re-derives it and refuses any report whose verdict disagrees with its own
evidence. ``ok`` means nothing structurally blocks an attach. It is not a
claim that an attach will succeed, that a license will check out, or that any
version in the matrix has been validated — the matrix says plainly that none
has.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from hfss_agent.broker import Broker, NoAttachedSessionError
from hfss_agent.contract import Environment
from hfss_agent.contract.tool_io import (
    ComponentCheck,
    PreflightEnvironment,
    PreflightReport,
)
from hfss_agent.preflight.probes import EnvironmentProbes, VersionRead
from hfss_agent.preflight.support_matrix import (
    AEDT_ANCHOR,
    AEDT_FLOOR,
    PYAEDT_PIN,
    PYTHON_CEILING_EXCLUSIVE,
    PYTHON_FLOOR,
    PYTHON_TARGET,
    SUPPORT_MATRIX_REF,
    AedtVersion,
    ComponentStatus,
    aggregate_installed_aedt_status,
    classify_aedt,
    classify_pyaedt,
    classify_python,
    component_status,
    format_aedt_version,
    parse_aedt_env_var_name,
    parse_dotted_version,
)

# The six §1.1 W-11 components, in the order every report emits them. ONE tuple
# governs both the checks and the rendered text, so output order can never
# depend on the order probes happened to answer in — that is what makes
# ``template_text`` byte-deterministic. All six are emitted unconditionally: no
# branch decides whether a row APPEARS, so a probe failure changes a row's
# content and never the report's shape.
#
# Deliberately NOT a contract ``Literal`` (ADR-26 decision 11): this is W-11's
# inventory of what it happens to check, and pinning it in the contract would
# make every future component a semver event on a doubly-pinned artifact. It is
# pinned HERE instead, by a test over the exact tuple.
COMPONENT_ORDER: tuple[str, ...] = (
    "aedt",
    "pyaedt",
    "python",
    "grpc",
    "license",
    "processes",
)

# The three components without which no attach can occur, and the three that are
# reported for information. The split is what keeps the roll-up honest in both
# directions (ADR-26 decision 7): "only incompatible demotes" would call a
# machine with AEDT but no PyAEDT healthy, and "any unavailable demotes" would
# mark every machine on earth incompatible forever, because the license row can
# never be anything else.
#
# The required three are exactly the three that are STRUCTURALLY DETERMINABLE:
# the install scan always returns a set (empty is an answer), importlib.metadata
# either yields a version or says the distribution is absent, and the running
# interpreter cannot fail to report its own version. That is not a coincidence —
# the contract refuses to construct a report whose required check is
# ``unavailable``, so a component may be required only if it can always be
# determined.
_REQUIRED = ("aedt", "pyaedt", "python")

# The three advisory rows are ``unavailable`` PERMANENTLY, each for its own
# structural reason — not pending work a later step finishes. Stated in the
# detail so a reader is never left to wonder whether the check is broken.
_LICENSE_DETAIL = (
    "Not determinable, permanently. This package makes no outbound network "
    "call of any kind, so no license server is contacted and no checkout is "
    "attempted; no local file states whether one would succeed. AEDT reports "
    "licensing at attach time."
)
_GRPC_DETAIL = (
    "Not determinable, permanently, because it is not a property of this "
    "machine. PyAEDT reads the transport per PROCESS at attach, where a port "
    "of -1 means a COM session that still attaches perfectly well. With no "
    "process selected there is nothing to report."
)
_PROCESSES_DETAIL = (
    "Not determinable at this step. Process discovery is deferred to its own "
    "step: the listing schema cannot be filled honestly from any read-only "
    "path without breaking the attach-once model. Deferred with a destination "
    "is not the same as unknown, but it is still undetermined today."
)

_CLOSING_NOTICE = (
    "No entry in the support matrix has been validated against a live AEDT "
    "session — it states what this project targets and what its dependency "
    "declares, never what has been confirmed to work. This report describes "
    "the machine only, and makes no claim that an attach will succeed, that a "
    "license will check out, or that any design will solve."
)

_ADVISORY_NOTICE = (
    "The advisory components above are undetermined by construction, not by "
    "failure, and they never affect the verdict."
)


@dataclass(frozen=True)
class _AedtReading:
    """What the AEDT row and the environment block agree the machine has.

    One helper rather than two, because the identity rule and the verdict rule
    read the same evidence and must not disagree: a report naming version X
    while its check judged a different set would be internally inconsistent in a
    way nothing downstream could detect.
    """

    version: AedtVersion | None
    source: Literal["attached_session", "installed_scan"] | None
    detected: str | None
    status: ComponentStatus
    detail: str


def preflight_environment(
    probes: EnvironmentProbes,
    broker: Broker | None = None,
) -> PreflightReport:
    """Check this machine against the published support matrix (Journey 1.0).

    Args:
        probes: the four machine reads, injected. REQUIRED AND UNDEFAULTED —
            see ``EnvironmentProbes``. With no default there is nothing for a
            forgotten argument to fall through to, so no caller and no test can
            read the host machine by omission.
        broker: the broker holding a session, when there is one. OPTIONAL,
            because preflight's whole purpose is to run before any attach; with
            no broker, or with one whose session is detached, the AEDT version
            is inferred from the installed-version scan instead.

    Returns:
        A ``PreflightReport``, always. There is no other representable outcome.
    """
    environment = _attached_environment(broker)
    aedt = _resolve_aedt(probes, environment)
    pyaedt = probes.pyaedt_version()
    python = probes.python_version()
    wrapper = probes.wrapper_version()

    checks = _checks(aedt, pyaedt, python)
    report_environment = PreflightEnvironment(
        aedt_version=(
            format_aedt_version(aedt.version) if aedt.version is not None else None
        ),
        aedt_version_source=aedt.source,
        pyaedt_version=pyaedt.version,
        python_version=python,
        wrapper_version=wrapper,
    )
    return PreflightReport(
        environment=report_environment,
        checks=checks,
        support_matrix_ref=SUPPORT_MATRIX_REF,
        overall=_overall(checks),
        template_text=_template_text(report_environment, checks, aedt, pyaedt),
    )


def _attached_environment(broker: Broker | None) -> Environment | None:
    """The attached session's version block, or None when there is no session.

    THE SAME EXCEPTION AS W-6 CATCHES, WITH THE OPPOSITE DISPOSITION, and that
    contrast is the reason this function exists rather than being inlined.
    ``validate_native`` catches ``NoAttachedSessionError`` and RAISES: a
    validation run that cannot be stamped with the versions it ran under is a
    record asserting something nobody verified, so the messages are discarded.
    Here the very same exception is the ORDINARY, EXPECTED state — Journey 1.0
    runs before any attach — so it is caught and execution CONTINUES into
    installed-scan mode. A detached session is not an error for this tool; it is
    the case it was written for.

    CATCHING IS ALSO THE ONLY LEGAL WAY TO ASK. ``Session.get_environment()``
    returns None rather than raising, but Layer 4 may not import ``session``;
    and asking through ``dispatch("get_session_status")`` would append an audit
    record for what is a control-plane read. The raising accessor is not
    dispatchable, so this route keeps preflight out of the audit log entirely.
    """
    if broker is None:
        return None
    try:
        return broker.require_environment()
    except NoAttachedSessionError:
        return None


def _resolve_aedt(
    probes: EnvironmentProbes, environment: Environment | None
) -> _AedtReading:
    """Which AEDT version may be reported, and how the ``aedt`` row judges.

    THE IDENTITY RULE (ADR-26 decision 18(e)): a version is reported only when
    an attached session supplies one, or when the installed set has exactly one
    member. A machine with several installs reports NO version — not the newest,
    not the first — because which one applies depends on which process an attach
    binds to, and preflight runs before that choice exists. Every installed
    version is still named in ``detected``, so nothing is hidden; what is
    refused is the guess.

    THE ATTACHED VERSION IS PARSED, NEVER PASSED THROUGH, and this is the
    module's one untrusted-input decision. It arrives from a live AEDT process
    (``Desktop.aedt_version_id``), sanitized at the adapter boundary — which
    strips control characters but DELIBERATELY PRESERVES tab and newline,
    because those are real structure in multi-line solver messages. A newline
    surviving into this newline-joined report would forge a rendered line. So
    the string is run through ``parse_dotted_version`` and, on success, the
    reported version is REBUILT from the two integers — exactly the guarantee
    the env-var path gets for free from its ``\\d{3}`` match. What reaches the
    text is wrapper-constructed either way.

    A session version that will not parse is not used at all, and the scan
    answers instead: an unparseable version cannot be classified, and reporting
    it verbatim while judging it against nothing would be worse than falling
    back to evidence we can read.
    """
    installed = sorted(
        {
            version
            for name in probes.aedt_env_var_names()
            if (version := parse_aedt_env_var_name(name)) is not None
        }
    )
    attached = _attached_aedt_version(environment)

    if attached is not None:
        status = component_status(classify_aedt(attached))
        return _AedtReading(
            version=attached,
            source="attached_session",
            detected=format_aedt_version(attached),
            status=status,
            detail=_aedt_detail_for_one(attached, "the attached session"),
        )

    scan_status = aggregate_installed_aedt_status(installed)
    if not installed:
        return _AedtReading(
            version=None,
            source=None,
            detected=None,
            status=scan_status,
            detail=(
                "No AEDT installation root is present in the environment "
                "(ANSYSEM_ROOT*, ANSYSEM_PY_CLIENT_ROOT*, ANSYSEMSV_ROOT*, "
                "AWP_ROOT* with an AnsysEM subdirectory). That is a "
                "determination, not a gap: with no root, PyAEDT's own version "
                "check raises and an attach is impossible rather than merely "
                "unverified."
            ),
        )
    if len(installed) == 1:
        return _AedtReading(
            version=installed[0],
            source="installed_scan",
            detected=format_aedt_version(installed[0]),
            status=scan_status,
            detail=_aedt_detail_for_one(
                installed[0], "the one installed version found"
            ),
        )
    return _AedtReading(
        version=None,
        source=None,
        detected=", ".join(format_aedt_version(v) for v in installed),
        status=scan_status,
        detail=(
            f"{len(installed)} AEDT versions are installed, so no single "
            "version can be named: which one an attach binds to depends on "
            "which process is attached to, and PyAEDT resolves that by "
            "matching the target process against each installed version in "
            "turn. The set is reported as supported because at least one "
            "installed version is — attaching to that process is a supported "
            "session. Attaching to an unsupported one on the same machine is "
            "not, which is why every version is listed above rather than "
            "summarised."
            if scan_status == "ok"
            else f"{len(installed)} AEDT versions are installed and none meets "
            f"the matrix floor of {format_aedt_version(AEDT_FLOOR)}."
        ),
    )


def _attached_aedt_version(environment: Environment | None) -> AedtVersion | None:
    """The attached session's AEDT version as two integers, if it is readable."""
    if environment is None:
        return None
    return parse_dotted_version(environment.aedt_version)


def _aedt_detail_for_one(version: AedtVersion, source_phrase: str) -> str:
    """The row detail for a single named AEDT version, naming its band."""
    band = classify_aedt(version)
    named = format_aedt_version(version)
    if band == "target":
        return (
            f"AEDT {named}, from {source_phrase}, is the version this project "
            "is built against. Targeted is not validated: no live AEDT session "
            "has confirmed any entry in the support matrix."
        )
    if band == "expected":
        return (
            f"AEDT {named}, from {source_phrase}, is at or above the matrix "
            f"floor of {format_aedt_version(AEDT_FLOOR)} and below the target "
            f"of {format_aedt_version(AEDT_ANCHOR)}. Nothing known forbids it; "
            "this project has never run against it."
        )
    if band == "beyond-pin":
        return (
            f"AEDT {named}, from {source_phrase}, is newer than the target of "
            f"{format_aedt_version(AEDT_ANCHOR)} and newer than the pinned "
            "PyAEDT knows about. Not blocked and not endorsed: PyAEDT does not "
            "reject a machine carrying only a future version, so an attach may "
            "well proceed through code written before that version existed."
        )
    return (
        f"AEDT {named}, from {source_phrase}, is below the matrix floor of "
        f"{format_aedt_version(AEDT_FLOOR)}. That floor is this project's, not "
        "PyAEDT's: PyAEDT only warns below 2022 R2 and would still attach, but "
        "it declares its own capabilities limited there, and this wrapper "
        "cannot stand its claims on a dependency that has said so."
    )


def _checks(
    aedt: _AedtReading, pyaedt: VersionRead, python: str
) -> list[ComponentCheck]:
    """The six rows, built unconditionally and returned in ``COMPONENT_ORDER``.

    Assembled from a dict keyed by component name and then ORDERED BY THE TUPLE
    rather than by insertion, so the ordering guarantee survives someone
    reordering the builders below.
    """
    built = {
        "aedt": _aedt_check(aedt),
        "pyaedt": _pyaedt_check(pyaedt),
        "python": _python_check(python),
        "grpc": _advisory_check(
            "grpc", "gRPC transport available to the target process", _GRPC_DETAIL
        ),
        "license": _advisory_check(
            "license", "a valid AEDT license at attach time", _LICENSE_DETAIL
        ),
        "processes": _advisory_check(
            "processes", "running AEDT processes to attach to", _PROCESSES_DETAIL
        ),
    }
    return [built[component] for component in COMPONENT_ORDER]


def _aedt_check(aedt: _AedtReading) -> ComponentCheck:
    """The AEDT row. Every judgment was already made in ``_resolve_aedt``, so
    the identity rule and the verdict cannot disagree."""
    return ComponentCheck(
        component="aedt",
        detected=aedt.detected,
        required=(
            f"AEDT {format_aedt_version(AEDT_FLOOR)} or later installed; "
            f"{format_aedt_version(AEDT_ANCHOR)} is the target"
        ),
        status=aedt.status,
        severity="required",
        detail=aedt.detail,
    )


def _pyaedt_check(read: VersionRead) -> ComponentCheck:
    """The PyAEDT row, where the three-state read earns its keep.

    ABSENT AND UNREADABLE BOTH BLOCK, and both are determinations rather than
    gaps — but they are DIFFERENT determinations and the detail says which,
    because they send a user to different fixes: install a missing package, or
    reinstall a damaged one. A single nullable version string could not have
    told them apart.

    ``absent`` is the ordinary case in this project's own CI, where both OS legs
    install without the ``live`` extra. A report describing that machine as
    unable to attach is correct, because it is.
    """
    required = f"PyAEDT {PYAEDT_PIN[0]}.{PYAEDT_PIN[1]}.* installed (the live extra)"
    if read.state == "absent":
        return ComponentCheck(
            component="pyaedt",
            detected=None,
            required=required,
            status="incompatible",
            severity="required",
            detail=(
                "No pyaedt distribution is installed. That is a determination, "
                "not a gap: without PyAEDT there is no path to an AEDT session "
                "at all. Install it with the live extra."
            ),
        )
    if read.state == "unreadable" or read.version is None:
        return ComponentCheck(
            component="pyaedt",
            detected=None,
            required=required,
            status="incompatible",
            severity="required",
            detail=(
                "A pyaedt distribution is present but its metadata could not "
                "be read as a version — a damaged or incomplete .dist-info, or "
                "a version string that is not one. This is NOT the same as not "
                "installed: reinstalling the package is the fix, not installing "
                "it."
            ),
        )
    parsed = parse_dotted_version(read.version)
    if parsed is None:
        return ComponentCheck(
            component="pyaedt",
            detected=read.version,
            required=required,
            status="incompatible",
            severity="required",
            detail=(
                f"PyAEDT reports version {read.version!r}, which could not be "
                "read as a major.minor pair, so it cannot be checked against "
                "the pin. Reported verbatim rather than guessed at."
            ),
        )
    band = classify_pyaedt(parsed)
    return ComponentCheck(
        component="pyaedt",
        detected=read.version,
        required=required,
        status=component_status(band),
        severity="required",
        detail=_pin_detail("PyAEDT", read.version, band),
    )


def _python_check(version: str) -> ComponentCheck:
    """The Python row.

    The floor and ceiling are this project's choice and not a PyAEDT limit —
    PyAEDT 1.2.0 declares ``Requires-Python: <4,>=3.10`` and claims support well
    past our ceiling — so the detail says so. A reader who takes the ceiling for
    a dependency constraint will "fix" the pin the first time they see PyAEDT
    advertise a wider range.
    """
    required = (
        f"Python {format_aedt_version(PYTHON_FLOOR)} or later and below "
        f"{format_aedt_version(PYTHON_CEILING_EXCLUSIVE)}; "
        f"{format_aedt_version(PYTHON_TARGET)} recommended"
    )
    parsed = parse_dotted_version(version)
    if parsed is None:
        return ComponentCheck(
            component="python",
            detected=version,
            required=required,
            status="incompatible",
            severity="required",
            detail=(
                f"The running interpreter reports version {version!r}, which "
                "could not be read as a major.minor pair, so it cannot be "
                "checked against the supported band."
            ),
        )
    band = classify_python(parsed)
    return ComponentCheck(
        component="python",
        detected=version,
        required=required,
        status=component_status(band),
        severity="required",
        detail=_pin_detail("Python", version, band)
        + (
            " The band is this project's choice for ecosystem maturity, not a "
            "PyAEDT limit: PyAEDT resolves cleanly well past this ceiling."
        ),
    )


def _pin_detail(name: str, detected: str, band: str) -> str:
    """The shared band sentence for the two pinned-range components."""
    if band == "target":
        return f"{name} {detected} is the pinned, targeted version."
    if band == "expected":
        return (
            f"{name} {detected} is inside the supported band, but is not the "
            "recommended version."
        )
    if band == "beyond-pin":
        return (
            f"{name} {detected} is above the pinned range. Not blocked and not "
            "endorsed: it is outside what this project tests against."
        )
    return f"{name} {detected} is below the supported floor."


def _advisory_check(component: str, required: str, detail: str) -> ComponentCheck:
    """One of the three permanently-undetermined rows.

    ``unavailable`` here means this wrapper structurally CANNOT determine the
    component — never that it failed to. Advisory severity is what stops that
    from demoting every machine forever: the license row can never be anything
    else, so a rule where any undetermined component blocks would mark every
    environment on earth incompatible.
    """
    return ComponentCheck(
        component=component,
        detected=None,
        required=required,
        status="unavailable",
        severity="advisory",
        detail=detail,
    )


def _overall(checks: list[ComponentCheck]) -> Literal["ok", "incompatible"]:
    """The verdict, COMPUTED from the checks and never passed in.

    Deliberately the same rule the contract enforces, and deliberately computed
    here anyway: the contract's validator is a backstop against a producer that
    disagrees with its own evidence, and a backstop that the producer relies on
    to be correct is not a backstop. Advisory rows are ignored entirely — see
    ``_advisory_check``.
    """
    blocking = [
        check
        for check in checks
        if check.severity == "required" and check.status == "incompatible"
    ]
    return "incompatible" if blocking else "ok"


def _template_text(
    environment: PreflightEnvironment,
    checks: list[ComponentCheck],
    aedt: _AedtReading,
    pyaedt: VersionRead,
) -> str:
    """The deterministic core text (§3): complete without any LLM.

    BYTE-DETERMINISTIC AND TIMESTAMP-FREE, following W-5, W-6 and W-7. The same
    machine state rendered twice produces identical bytes, so tests can pin the
    wording and a diff between two runs shows only what actually changed about
    the environment. Determinism holds structurally: the rows arrive in
    ``COMPONENT_ORDER`` and nothing here sorts, dedups, or iterates a dict.

    NEWLINE-JOINED, like W-6's and W-7's: a list of component checks IS a list,
    and flattening it onto one line would misrepresent its shape.

    NO CONTROL-CHARACTER GUARD, and that is a determination rather than an
    oversight. ADR-25 decision 7 requires any module rendering an
    ``UntrustedStr`` into a line-oriented format to carry its own guard. Nothing
    rendered below is one:

      * the AEDT version is rebuilt from two integers — from a ``\\d{3}`` match
        on an environment variable NAME, or from ``parse_dotted_version`` on the
        attached session's string (see ``_resolve_aedt``), so the attached path
        gets the same guarantee as the scanned one;
      * the PyAEDT and wrapper versions passed a conservative shape check at the
        probe, which admits PEP 440's alphabet and no whitespace, newline, or
        control character;
      * the Python version is interpreter-sourced;
      * every other string here is a wrapper-owned literal.

    The two version strings that could be rendered without passing that shape
    check are the two unparseable branches above, and both come from the same
    probe-checked source. There is no path from HFSS-sourced text to this
    function.
    """
    required = [check for check in checks if check.severity == "required"]
    incompatible = [check for check in required if check.status == "incompatible"]
    advisory = [check for check in checks if check.severity == "advisory"]
    verdict = "incompatible" if incompatible else "ok"

    parts = [
        f'Preflight environment check: overall "{verdict}". '
        f"{len(required)} required component(s), {len(required) - len(incompatible)} "
        f"ok and {len(incompatible)} incompatible; {len(advisory)} advisory "
        "component(s), none determinable.",
        f"Versions: AEDT {_environment_aedt(environment, aedt)}; PyAEDT "
        f"{_environment_pyaedt(pyaedt)}; Python "
        f"{environment.python_version}; hfss-agent {environment.wrapper_version}.",
        f"Components, checked against {SUPPORT_MATRIX_REF}:",
    ]
    parts += [
        f"  [{check.severity}] {check.component}: {check.status} — detected "
        f"{check.detected if check.detected is not None else 'nothing'}; "
        f"requires {check.required}. {check.detail}"
        for check in checks
    ]
    parts.append(_ADVISORY_NOTICE)
    parts.append(_CLOSING_NOTICE)
    return "\n".join(parts)


def _environment_pyaedt(read: VersionRead) -> str:
    """The PyAEDT clause of the versions line.

    "not installed" and "not readable" are kept apart HERE TOO, not only in the
    row below, because the versions line is the part a reader skims. Collapsing
    both to one phrase would send someone with a damaged install looking for a
    package that is already there.
    """
    if read.version is not None:
        return read.version
    return "not installed" if read.state == "absent" else "not readable"


def _environment_aedt(
    environment: PreflightEnvironment, aedt: _AedtReading
) -> str:
    """The AEDT clause of the versions line, with its provenance named.

    The source is stated in words because the two claims are different and a
    reader has to be able to tell them apart: a version read from an attached
    session is the version of the process we are talking to, while one inferred
    from an installed-version scan is a guess about which process an attach
    MIGHT bind to.
    """
    if environment.aedt_version is None:
        if aedt.detected is not None:
            return f"no single version ({aedt.detected} installed)"
        return "none installed"
    if environment.aedt_version_source == "attached_session":
        return f"{environment.aedt_version} (read from the attached session)"
    return f"{environment.aedt_version} (inferred from the installed-version scan)"
