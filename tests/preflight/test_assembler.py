"""W-11's assembler: the six rows, the verdict, the three broker modes.

The suite that proves ``preflight_environment`` says true things about a machine
it is told about, and nothing about the machine it is running on.
"""

from __future__ import annotations

import pytest
from preflight_helpers import (
    attached_broker,
    detached_broker,
    fixture_probes,
    lost_broker,
    root_names,
)
from pydantic import ValidationError

from hfss_agent.broker import NoAttachedSessionError
from hfss_agent.contract.tool_io import ComponentCheck
from hfss_agent.preflight import COMPONENT_ORDER, preflight_environment
from hfss_agent.preflight import assembler as assembler_module
from hfss_agent.preflight.probes import VersionRead


def _report(**kwargs):
    return preflight_environment(fixture_probes(**kwargs))


def _row(report, component: str) -> ComponentCheck:
    return next(check for check in report.checks if check.component == component)


# --- the five verdict rows ---------------------------------------------------
#
# Each verdict is a DECISION MADE AT THIS STEP, recorded in ADR-27, not a
# transcription: ADR-26 decision 18(e) fixes only which version may be REPORTED
# (a single install, or an attached session), and says nothing about the verdict
# a set of several deserves.


def test_single_supported_install_is_reported_and_attributed() -> None:
    report = _report(aedt=root_names("2026.1"))
    assert report.environment.aedt_version == "2026.1"
    assert report.environment.aedt_version_source == "installed_scan"
    assert _row(report, "aedt").detected == "2026.1"
    assert _row(report, "aedt").status == "ok"
    assert report.overall == "ok"


def test_single_install_below_our_floor_is_incompatible() -> None:
    """Our floor, not PyAEDT's — PyAEDT would warn and still attach."""
    report = _report(aedt=root_names("2021.2"))
    assert report.environment.aedt_version == "2021.2"
    assert report.environment.aedt_version_source == "installed_scan"
    assert _row(report, "aedt").status == "incompatible"
    assert report.overall == "incompatible"
    assert "this project's, not" in _row(report, "aedt").detail


def test_multi_install_reports_no_version_but_is_not_blocked() -> None:
    """The row the aggregation rule exists for.

    No version may be NAMED (ADR-26 decision 18(e)) because which one an attach
    binds to depends on the process; the set is still supported, because
    attaching to the 2026.1 process is a supported session. Both facts are
    reported at once: ``aedt_version`` is None and every install is listed.
    """
    report = _report(aedt=root_names("2021.2", "2026.1"))
    assert report.environment.aedt_version is None
    assert report.environment.aedt_version_source is None
    assert _row(report, "aedt").detected == "2021.2, 2026.1"
    assert _row(report, "aedt").status == "ok"
    assert report.overall == "ok"


def test_multi_install_all_supported_still_reports_no_version() -> None:
    """The identity rule is about AMBIGUITY, not about support: two supported
    installs are still two, so neither may be named."""
    report = _report(aedt=root_names("2024.2", "2026.1"))
    assert report.environment.aedt_version is None
    assert _row(report, "aedt").detected == "2024.2, 2026.1"
    assert _row(report, "aedt").status == "ok"
    assert report.overall == "ok"


def test_no_install_is_a_determination_not_a_gap() -> None:
    """Absence is an answer. With no root PyAEDT's own check raises, so an
    attach is impossible rather than merely unverified — which is why this is
    ``incompatible`` and never ``unavailable``."""
    report = _report(aedt=())
    assert report.environment.aedt_version is None
    assert _row(report, "aedt").detected is None
    assert _row(report, "aedt").status == "incompatible"
    assert _row(report, "aedt").severity == "required"
    assert report.overall == "incompatible"


# --- the two extras ----------------------------------------------------------


def test_future_version_only_machine_is_not_reported_as_absent() -> None:
    """ADR-26 decision 5's warning, made a test.

    PyAEDT's ``__check_version`` raises only when ``current_version`` AND
    ``latest_version`` are empty, and ``latest_version`` is unfiltered — so a
    machine carrying only a future version is NOT rejected by PyAEDT and an
    attach may well proceed. Reporting it as absent, or blocking it, would
    refuse a machine the dependency accepts.
    """
    report = _report(aedt=root_names("2027.1"))
    assert report.environment.aedt_version == "2027.1"
    assert _row(report, "aedt").status == "ok"
    assert report.overall == "ok"
    detail = _row(report, "aedt").detail
    assert "Not blocked and not endorsed" in detail
    assert "not installed" not in detail.lower()


def test_attached_session_version_overrides_the_installed_scan() -> None:
    """Attached always wins: it is the version of the process we are talking to,
    while the scan is an inference about which process an attach MIGHT bind
    to."""
    broker, _ = attached_broker(aedt_version="2026.1")
    report = preflight_environment(
        fixture_probes(aedt=root_names("2021.2")), broker
    )
    assert report.environment.aedt_version == "2026.1"
    assert report.environment.aedt_version_source == "attached_session"
    assert _row(report, "aedt").status == "ok"
    assert report.overall == "ok"


# --- the component tuple, across every probe-failure scenario ----------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"aedt": root_names("2026.1")},
        {"aedt": root_names("2021.2")},
        {"aedt": root_names("2021.2", "2026.1")},
        {"pyaedt": VersionRead(None, "absent")},
        {"pyaedt": VersionRead(None, "unreadable")},
        {"pyaedt": VersionRead("0.9.0", "found")},
        {"python": "3.9.18"},
        {"python": "not-a-version"},
        {"wrapper": "0.0.0"},
    ],
    ids=[
        "empty-machine",
        "supported-aedt",
        "old-aedt",
        "multi-install",
        "pyaedt-absent",
        "pyaedt-unreadable",
        "pyaedt-too-old",
        "python-too-old",
        "python-unparseable",
        "wrapper-fallback",
    ],
)
def test_the_six_components_are_emitted_by_identity_and_order(kwargs) -> None:
    """Pinned across FAILURE scenarios, not just the happy path.

    All six rows are emitted unconditionally, so a probe failure changes a row's
    CONTENT and never the report's SHAPE. A consumer reading position 3 gets the
    python row on every machine there is.
    """
    report = _report(**kwargs)
    assert tuple(check.component for check in report.checks) == COMPONENT_ORDER


def test_the_component_tuple_is_the_six_documented_names() -> None:
    assert COMPONENT_ORDER == (
        "aedt",
        "pyaedt",
        "python",
        "grpc",
        "license",
        "processes",
    )


# --- the three broker modes --------------------------------------------------


def test_no_broker_uses_the_installed_scan() -> None:
    """The ordinary Journey 1.0 call: there is no session yet."""
    report = preflight_environment(fixture_probes(aedt=root_names("2026.1")))
    assert report.environment.aedt_version_source == "installed_scan"


def test_a_detached_broker_falls_back_to_the_scan() -> None:
    """THE SAME EXCEPTION W-6 CATCHES, WITH THE OPPOSITE DISPOSITION.

    ``validate_native`` catches ``NoAttachedSessionError`` and raises, because a
    validation it cannot stamp is a record asserting something nobody verified.
    Here it is the expected state and execution continues — a detached session
    is not an error for this tool, it is the case it was written for.
    """
    broker, _ = detached_broker()
    report = preflight_environment(
        fixture_probes(aedt=root_names("2026.1")), broker
    )
    assert report.environment.aedt_version == "2026.1"
    assert report.environment.aedt_version_source == "installed_scan"
    assert report.overall == "ok"


def test_an_attached_broker_reads_the_session() -> None:
    broker, _ = attached_broker(aedt_version="2024.2")
    report = preflight_environment(fixture_probes(), broker)
    assert report.environment.aedt_version == "2024.2"
    assert report.environment.aedt_version_source == "attached_session"
    assert "installed-version scan" not in report.template_text


def test_an_incompatibility_simulated_by_the_fake_adapter_is_flagged() -> None:
    """THE RUNBOOK'S DONE BAR, pinned: "preflight check runs against the fake
    adapter and correctly flags a simulated incompatibility".

    A SEPARATE TEST RATHER THAN AN ASSERTION ADDED TO THE LOST-SESSION ONE, and
    the reason is that they are different claims. There, the incompatibility
    would arrive from the injected probe set while the subject under test is the
    session transition — the verdict would be true but incidental, and a reader
    could not tell which half the test was protecting.

    Here the FAKE ADAPTER ITSELF SUPPLIES THE INCOMPATIBILITY. The scenario's
    ``Environment`` reports AEDT 2021.2, the probes contribute no installed
    version at all, so the only thing that can produce a verdict is the version
    read back across the broker from the fake session. That is what makes this
    the runbook's clause rather than a paraphrase of it: the simulation is the
    adapter's, not the test's.

    Verified by hand during the Part 5 sweep before it was pinned here, which is
    exactly the evidence a Done bar should not have to rest on.
    """
    broker, _ = attached_broker(aedt_version="2021.2")
    report = preflight_environment(fixture_probes(aedt=()), broker)

    assert report.environment.aedt_version == "2021.2"
    assert report.environment.aedt_version_source == "attached_session"
    aedt = _row(report, "aedt")
    assert aedt.status == "incompatible"
    assert aedt.severity == "required"
    assert report.overall == "incompatible"
    assert 'overall "incompatible"' in report.template_text


def test_a_lost_session_does_not_report_attached_session() -> None:
    """THE THIRD DETACHED SHAPE, and the only one that was not obviously safe.

    A never-attached session plainly has no environment. This one HAD one: it
    attached, read AEDT 2026.1 from the process, and then the link dropped. If
    that environment survived the transition, ``require_environment`` would
    return a dead process's versions, and preflight would report
    ``aedt_version_source="attached_session"`` for a session that no longer
    exists — a version attributed to a process that may since have been
    relaunched at a different one.

    ADR-22 decision 10 says the environment clears on LOST and is deliberately
    not carried forward alongside ``last_process_id``. That is a claim in a
    document about code, so this pins the MECHANISM: the session is driven to
    LOST through a real adapter fault, and the assertion is on what preflight
    actually reports afterwards.

    The scan sees a version the session never did, so the two sources are
    distinguishable in the result: reporting 2021.2 from the scan is the pass,
    and 2026.1 from the dead session would be the failure.
    """
    broker, _, session = lost_broker()
    assert session.get_environment() is None
    with pytest.raises(NoAttachedSessionError):
        broker.require_environment()

    report = preflight_environment(
        fixture_probes(aedt=root_names("2021.2")), broker
    )
    assert report.environment.aedt_version_source == "installed_scan"
    assert report.environment.aedt_version == "2021.2"
    assert "read from the attached session" not in report.template_text


def test_preflight_writes_no_audit_record() -> None:
    """Preflight never dispatches, and the audit log is written by dispatch.

    Asserted on the sink the broker actually holds, in BOTH modes: the attached
    broker's session was driven directly rather than through a dispatch, so a
    non-empty sink here could only have come from this call.
    """
    attached, attached_sink = attached_broker()
    detached, detached_sink = detached_broker()
    preflight_environment(fixture_probes(), attached)
    preflight_environment(fixture_probes(), detached)
    assert attached_sink.records == []
    assert detached_sink.records == []


# --- the attached path is parsed, never passed through -----------------------


def test_an_attached_version_carrying_a_newline_cannot_forge_a_line() -> None:
    """The one untrusted input W-11 has, and the guarantee it gets.

    ``Environment.aedt_version`` comes from a live AEDT process. It is sanitized
    at the adapter boundary — which strips control characters but DELIBERATELY
    PRESERVES newline, since multi-line solver messages are real structure — so
    a newline can reach this module, and ``template_text`` is newline-joined.

    The version is therefore parsed and REBUILT from two integers rather than
    passed through, which is the same guarantee the env-var path gets from its
    ``\\d{3}`` match. The payload below is shaped like a Touchstone data line,
    the forged-measurement attack ADR-25 decision 7 found against ``export``.
    """
    broker, _ = attached_broker(aedt_version="2026.1\nS 2 5.0 0.0")
    report = preflight_environment(fixture_probes(), broker)
    assert report.environment.aedt_version == "2026.1"
    assert "S 2 5.0" not in report.template_text
    assert "\nS 2" not in report.template_text


def test_an_unparseable_attached_version_falls_back_to_the_scan() -> None:
    """A session version that cannot be classified is not used at all.

    Reporting it verbatim while judging it against nothing would be worse than
    falling back to evidence that can be read.
    """
    broker, _ = attached_broker(aedt_version="unknown")
    report = preflight_environment(
        fixture_probes(aedt=root_names("2026.1")), broker
    )
    assert report.environment.aedt_version == "2026.1"
    assert report.environment.aedt_version_source == "installed_scan"


# --- the verdict -------------------------------------------------------------


def test_advisory_rows_never_demote_the_verdict() -> None:
    """Without the severity split every machine on earth would be incompatible
    forever, because the license row can never be anything else."""
    report = _report(aedt=root_names("2026.1"))
    advisory = [check for check in report.checks if check.severity == "advisory"]
    assert [check.component for check in advisory] == ["grpc", "license", "processes"]
    assert all(check.status == "unavailable" for check in advisory)
    assert report.overall == "ok"


def test_no_required_row_is_ever_unavailable() -> None:
    """The three required components are exactly the three that are
    structurally determinable — the contract refuses a report claiming
    otherwise, so the producer must never emit one."""
    for kwargs in ({}, {"pyaedt": VersionRead(None, "unreadable")}, {"python": "x"}):
        report = _report(**kwargs)
        required = [c for c in report.checks if c.severity == "required"]
        assert [c.component for c in required] == ["aedt", "pyaedt", "python"]
        assert all(c.status != "unavailable" for c in required)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"aedt": root_names("2026.1")}, "ok"),
        ({"aedt": root_names("2026.1"), "pyaedt": VersionRead(None, "absent")},
         "incompatible"),
        ({"aedt": root_names("2026.1"), "python": "3.9.18"}, "incompatible"),
        ({"aedt": ()}, "incompatible"),
    ],
)
def test_overall_follows_the_required_rows(kwargs, expected: str) -> None:
    report = _report(**kwargs)
    assert report.overall == expected


# --- the pyaedt row's three states -------------------------------------------


def test_absent_and_unreadable_pyaedt_block_with_different_details() -> None:
    """Both are determinations and both block, but they send a user to
    different fixes — install a missing package, or reinstall a damaged one. A
    single nullable string could not have told them apart."""
    absent = _row(_report(pyaedt=VersionRead(None, "absent")), "pyaedt")
    unreadable = _row(_report(pyaedt=VersionRead(None, "unreadable")), "pyaedt")
    assert absent.status == unreadable.status == "incompatible"
    assert absent.detail != unreadable.detail
    assert "No pyaedt distribution is installed" in absent.detail
    assert "NOT the same as not installed" in unreadable.detail


@pytest.mark.parametrize(
    ("version", "expected"),
    [("1.2.0", "ok"), ("1.1.0", "incompatible"), ("1.3.0", "ok")],
)
def test_pyaedt_bands_map_to_status(version: str, expected: str) -> None:
    report = _report(aedt=root_names("2026.1"), pyaedt=VersionRead(version, "found"))
    assert _row(report, "pyaedt").status == expected


# --- the python row ----------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("3.12.10", "ok"),
        ("3.10.0", "ok"),
        ("3.13.0", "ok"),
        ("3.9.18", "incompatible"),
    ],
)
def test_python_bands_map_to_status(version: str, expected: str) -> None:
    report = _report(aedt=root_names("2026.1"), python=version)
    assert _row(report, "python").status == expected


def test_an_unparseable_python_is_incompatible_never_unavailable() -> None:
    report = _report(python="not-a-version")
    row = _row(report, "python")
    assert row.status == "incompatible"
    assert row.detected == "not-a-version"


def test_the_python_row_says_the_ceiling_is_ours() -> None:
    """A reader who takes the ceiling for a dependency constraint will "fix" the
    pin the first time they see PyAEDT advertise a wider range."""
    assert "not a PyAEDT limit" in _row(_report(), "python").detail


# --- template_text -----------------------------------------------------------


def test_template_text_is_byte_identical_across_runs() -> None:
    """Determinism holds structurally: rows arrive in COMPONENT_ORDER and
    nothing sorts, dedups, or iterates a dict on this path."""
    first = _report(aedt=root_names("2021.2", "2026.1")).template_text
    second = _report(aedt=root_names("2021.2", "2026.1")).template_text
    assert first == second


def test_template_text_renders_every_component() -> None:
    text = _report(aedt=root_names("2026.1")).template_text
    for component in COMPONENT_ORDER:
        assert f" {component}: " in text


def test_template_text_cites_the_matrix_and_claims_no_validation() -> None:
    text = _report(aedt=root_names("2026.1")).template_text
    assert "docs/support-matrix.md" in text
    assert "has been validated against a live AEDT session" in text


def test_template_text_distinguishes_the_two_aedt_sources() -> None:
    """The two claims are different and a reader has to be able to tell them
    apart: one is the process we are talking to, the other a guess about which
    process an attach might bind to."""
    scanned = _report(aedt=root_names("2026.1")).template_text
    broker, _ = attached_broker(aedt_version="2026.1")
    attached = preflight_environment(fixture_probes(), broker).template_text
    assert "inferred from the installed-version scan" in scanned
    assert "read from the attached session" in attached


# --- the negative controls: the contract's backstops shown to bite -----------


def test_a_required_check_reporting_unavailable_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE BACKSTOP, SHOWN TO BITE.

    The assembler cannot emit this — every required component is structurally
    determinable, which is why they are required at all. So the producer is
    deliberately broken and driven through the real entry point, because a
    guard that has never been seen to fire is a guard nobody has tested.

    Its consequence if it did not fire: a report rolling up to ``ok`` with a
    load-bearing component unchecked.
    """
    broken = ComponentCheck(
        component="aedt",
        detected=None,
        required="AEDT 2022.2 or later",
        status="unavailable",
        severity="required",
        detail="a producer defect, simulated",
    )
    monkeypatch.setattr(assembler_module, "_aedt_check", lambda _reading: broken)
    with pytest.raises(ValidationError) as caught:
        _report(aedt=root_names("2026.1"))
    assert "structurally determinable" in str(caught.value)


def test_a_check_list_with_no_required_row_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The evidence guard: an advisory-only list satisfies both roll-up
    validators VACUOUSLY and would declare an unexamined machine healthy."""
    monkeypatch.setattr(
        assembler_module,
        "_checks",
        lambda *_args: [
            assembler_module._advisory_check("license", "a licence", "undetermined")
        ],
    )
    with pytest.raises(ValidationError) as caught:
        _report()
    assert "at least one severity='required'" in str(caught.value)


def test_a_verdict_disagreeing_with_its_evidence_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``overall`` is computed here AND re-derived by the contract. A backstop
    the producer relies on to be correct is not a backstop, so both exist."""
    monkeypatch.setattr(assembler_module, "_overall", lambda _checks: "ok")
    with pytest.raises(ValidationError) as caught:
        _report(aedt=())
    assert "contradicts the checks" in str(caught.value)
