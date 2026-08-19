"""``__main__`` (W-1): the flag, the refusal, and the disclosure it selects.

THIS MODULE HAD NO TESTS AT ALL UNTIL PART 10, and its own docstrings advertised
two that did not exist: ``argv`` is "injectable so a test drives the real parser
and the real refusal path without touching ``sys.argv``", and the exit code is
returned rather than raised "so a test can call ``main`` and assert on the code
instead of catching ``SystemExit``". Both claims are now true.

THE ONE THAT MATTERS MOST IS THE LAST ONE HERE. ``build_app`` calls a live
disclosure over a fake adapter "the one combination that must be impossible to
reach by accident", and the wiring that prevents it -- flag -> resolved kind ->
``adapter_kind`` -> disclosure -- lives entirely in ``main`` and was covered by
nothing.

WHAT IS STUBBED, AND WHY EACH ONE. Everything else is production code.

  * ``REAL_PROBES`` -- so the PyAEDT decision is deterministic. Without this the
    same test asserts different things on a Windows laptop with the ``live``
    extra and on a CI runner without it, which is exactly the failure
    ``EnvironmentProbes`` was made undefaultable to prevent. Only
    ``pyaedt_version`` is replaced; the other three probes stay real.
  * ``build_adapter`` -- so ``--adapter live`` does not need the AEDT extra CI
    deliberately does not install. It returns a ``FakeAdapter`` FOR BOTH KINDS,
    which makes the disclosure test stronger rather than weaker: with the same
    adapter object behind both runs, the flag is the ONLY thing that can change
    the wording.
  * ``default_data_dir`` -- so a test never creates the real
    ``%LOCALAPPDATA%\\hfss-agent``. ``build_composition`` resolves it when no
    ``data_dir`` is passed, and ``main`` passes none.
  * ``MCPServer.run`` on the built app -- so nothing serves. This is the last
    line of ``main``; everything under test happens before it.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from server_helpers import absent, found, unreadable

from hfss_agent.adapter.fake import FakeAdapter
from hfss_agent.preflight import REAL_PROBES
from hfss_agent.server import FAKE, LIVE
from hfss_agent.server import __main__ as entry
from hfss_agent.server import composition as composition_module


@dataclasses.dataclass
class Started:
    """What one ``main()`` run did, for the assertions to read."""

    exit_code: int
    adapter_kind: str | None
    app: object | None
    transports: list[str]


def _start(monkeypatch, argv, *, pyaedt, tmp_path: Path) -> Started:
    """Run the real ``main`` with the four stubs the module docstring lists."""
    record = Started(exit_code=-1, adapter_kind=None, app=None, transports=[])

    monkeypatch.setattr(
        entry, "REAL_PROBES", dataclasses.replace(REAL_PROBES, pyaedt_version=pyaedt)
    )
    monkeypatch.setattr(entry, "build_adapter", lambda kind: FakeAdapter())
    monkeypatch.setattr(
        composition_module, "default_data_dir", lambda: str(tmp_path)
    )

    real_build_app = entry.build_app

    def spy(composition, *, adapter_kind):
        app = real_build_app(composition, adapter_kind=adapter_kind)
        record.adapter_kind = adapter_kind
        record.app = app
        # Replace ONLY the transport call, so main() returns instead of serving.
        monkeypatch.setattr(app, "run", record.transports.append)
        return app

    monkeypatch.setattr(entry, "build_app", spy)
    record.exit_code = entry.main(argv)
    return record


# --- the refusal path ---------------------------------------------------------


def test_an_unrecognised_flag_value_refuses_and_returns_the_refusal_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    """THE ADVERTISED TEST. Drives the real parser and the real refusal path.

    ``REFUSED_EXIT_CODE`` is 2 rather than 1 so a supervisor can tell a
    deliberate refusal from a crash; asserting on the constant rather than the
    literal keeps that decision in one place.
    """
    started = _start(
        monkeypatch, ["--adapter", "fkae"], pyaedt=found, tmp_path=tmp_path
    )
    assert started.exit_code == entry.REFUSED_EXIT_CODE
    assert started.app is None, "a refused startup must not build a server"
    assert started.transports == [], "a refused startup must not serve"

    captured = capsys.readouterr()
    lines = [line for line in captured.err.splitlines() if line.strip()]
    assert len(lines) == 2, f"expected a reason line and a remedy line, got {lines}"
    assert "refusing to start" in lines[0]
    assert "'fkae'" in lines[0], "the refusal does not quote what was given"
    assert "--adapter" in lines[1] and "fake" in lines[1], (
        "the remedy line does not name the fix"
    )
    # Every diagnostic on this path goes to stderr. (``argparse`` writes --help
    # to stdout, which is a separate path this test does not reach and does not
    # claim to cover.)
    assert captured.out == ""


def test_live_without_pyaedt_refuses_rather_than_falling_back(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    """THE CENTRAL REFUSAL, driven through the entry point rather than through
    ``resolve_adapter_kind`` alone. A silent downgrade to the fake here is how a
    user reads canned S-parameters under a stamp naming their own design."""
    started = _start(monkeypatch, [], pyaedt=absent, tmp_path=tmp_path)
    assert started.exit_code == entry.REFUSED_EXIT_CODE
    assert started.app is None
    assert "not installed" in capsys.readouterr().err


def test_the_two_pyaedt_absences_reach_the_operator_differently(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    """"Install it" and "reinstall it" are different fixes, and the distinction
    has to survive all the way to stderr -- not just exist in the exception."""
    _start(monkeypatch, [], pyaedt=absent, tmp_path=tmp_path)
    missing = capsys.readouterr().err
    _start(monkeypatch, [], pyaedt=unreadable, tmp_path=tmp_path)
    damaged = capsys.readouterr().err
    assert missing != damaged
    assert "not installed" in missing
    assert "could not " in damaged


def test_every_line_the_refusal_path_prints_is_ascii(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    """The cp1252 guard, at the point of use.

    ``test_adapter_selection`` checks the exception's two strings. This checks
    what actually reaches the console, prefix included -- a non-ASCII character
    in ``__main__``'s own ``hfss-agent: `` framing would be just as unreadable.
    """
    for argv, probe in ((["--adapter", "fkae"], found), ([], absent), ([], unreadable)):
        _start(monkeypatch, argv, pyaedt=probe, tmp_path=tmp_path)
        text = capsys.readouterr().err
        offenders = sorted({char for char in text if ord(char) > 127})
        assert not offenders, f"non-ASCII on stderr for {argv}: {offenders}"


# --- the successful path, and the combination that must never be wrong --------


def test_the_flag_selects_the_adapter_kind_and_the_server_serves_stdio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A clean start: kind resolved, app built, transport started, code 0.

    The transport argument is asserted because ``__main__`` passes ``"stdio"``
    explicitly rather than relying on the SDK default -- the transport is a
    locked architectural decision and a default is not the place to record one.
    """
    started = _start(
        monkeypatch, ["--adapter", "fake"], pyaedt=absent, tmp_path=tmp_path
    )
    assert started.exit_code == 0
    assert started.adapter_kind == FAKE
    assert started.transports == ["stdio"]


def test_the_flag_is_absent_and_live_is_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Omitting the flag serves LIVE, through the entry point. Absence of
    configuration selects the correct-for-the-user option, not the
    safe-for-the-developer one."""
    started = _start(monkeypatch, [], pyaedt=found, tmp_path=tmp_path)
    assert started.exit_code == 0
    assert started.adapter_kind == LIVE
    assert started.transports == ["stdio"]


def test_the_fake_flag_produces_the_simulated_name_and_the_fake_disclosure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE COMBINATION ``build_app`` CALLS IMPOSSIBLE-BY-ACCIDENT, checked.

    ``build_app`` takes ``adapter_kind`` keyword-only and undefaulted precisely
    so that live wording over a fake adapter cannot be reached by omission. That
    argument is only ever supplied in one place -- ``main`` -- and until now
    nothing checked that ``main`` supplies the right one. Every other disclosure
    test builds the app itself and passes the kind by hand, which cannot catch a
    mis-wiring here.

    Note the adapter object is a ``FakeAdapter`` in BOTH this test and its live
    counterpart below (see the module docstring). That is deliberate: it removes
    the adapter as a variable, so the flag is provably the only cause of the
    difference in wording.
    """
    started = _start(
        monkeypatch, ["--adapter", "fake"], pyaedt=absent, tmp_path=tmp_path
    )
    assert started.adapter_kind == FAKE
    assert "SIMULATED" in started.app.name
    instructions = started.app.instructions or ""
    assert "SIMULATED DATA" in instructions
    assert "--adapter fake" in instructions


def test_the_live_path_produces_neither_the_simulated_name_nor_the_notice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The other half, and the one a mis-wiring would break silently: a live
    start must not carry simulated wording, and a fake start must not lose it."""
    started = _start(
        monkeypatch, ["--adapter", "live"], pyaedt=found, tmp_path=tmp_path
    )
    assert started.adapter_kind == LIVE
    assert "SIMULATED" not in started.app.name
    instructions = started.app.instructions or ""
    assert "SIMULATED" not in instructions
    assert "attach-only" in instructions


@pytest.mark.parametrize("given", [" FAKE ", "Fake", "fake\t"])
def test_a_loosely_spelled_flag_still_reaches_the_fake_disclosure(
    given: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Whitespace and case tolerance is decided in ``resolve_adapter_kind``, but
    it is the DISCLOSURE that must not be lost by it. A spelling that resolved to
    the fake adapter while publishing live wording is the exact failure this
    whole chain exists to prevent."""
    started = _start(
        monkeypatch, ["--adapter", given], pyaedt=absent, tmp_path=tmp_path
    )
    assert started.adapter_kind == FAKE
    assert "SIMULATED" in started.app.name


# --- the parser itself --------------------------------------------------------


def test_the_parser_does_not_use_argparse_choices() -> None:
    """``build_parser``'s stated reason, checked rather than trusted.

    With ``choices=``, argparse rejects a bad value itself -- printing its own
    usage text and exiting before ``resolve_adapter_kind`` is consulted -- which
    would leave two refusal paths with two different wordings, only one of which
    names the fix and is ASCII-checked. This pins that the single refusal path
    survives: a bogus value must reach the parser without argparse intercepting.
    """
    parsed = entry.build_parser().parse_args(["--adapter", "fkae"])
    assert parsed.adapter == "fkae", (
        "argparse rejected the value itself, so the refusal in adapter_selection "
        "is now unreachable and its wording is no longer what an operator sees."
    )


def test_the_parser_reports_an_absent_flag_as_none() -> None:
    """``None`` and an empty string must stay distinguishable: absent means
    LIVE by default, while ``--adapter ""`` is malformed and refuses."""
    assert entry.build_parser().parse_args([]).adapter is None
    assert entry.build_parser().parse_args(["--adapter", ""]).adapter == ""
