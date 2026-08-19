"""The fake-adapter disclosure (W-1): what the handshake says, and what it cannot.

THIS TESTS A DISCLOSURE, NOT A GUARD, and the distinction is the point. The
disclosure is delivered once, at initialize, and the host may render it,
summarise it, or ignore it. It changes nothing downstream: the values a
simulated session returns are not marked and are not detectable. The last test
in this file pins that hole open on purpose, so nobody later reads the presence
of a disclosure as evidence that simulated data is identifiable.
"""

from __future__ import annotations

import tempfile

from hfss_agent.adapter.fake import FakeAdapter
from hfss_agent.server import FAKE, LIVE, build_composition
from hfss_agent.server.app import build_app


def _app(kind: str):
    composition = build_composition(FakeAdapter(), data_dir=tempfile.mkdtemp())
    return build_app(composition, adapter_kind=kind)


def test_the_fake_suffixes_the_server_name() -> None:
    """The name is what a client shows in constrained places -- a picker, a
    status line -- where the instructions text will not fit."""
    assert "SIMULATED" in _app(FAKE).name
    assert "SIMULATED" not in _app(LIVE).name


def test_the_fake_instructions_say_the_data_is_not_measured() -> None:
    text = _app(FAKE).instructions or ""
    assert "SIMULATED DATA" in text
    assert "--adapter fake" in text
    assert "NOT connected to Ansys HFSS" in text
    # The instruction that actually constrains a model's behaviour.
    assert "Do not report any value from this server as a measurement" in text


def test_the_fake_instructions_admit_their_own_limits() -> None:
    """THE SENTENCE THAT MUST NOT BE SOFTENED.

    A disclosure that implies the values are marked would be worse than none: a
    reader would look for the marker, not find one, and conclude the data is
    live. So the text has to state that this notice is the only signal and that
    individual responses carry none.
    """
    text = _app(FAKE).instructions or ""
    assert "ONLY indication" in text
    assert "no marker" in text


def test_the_live_instructions_claim_no_more_than_the_connection() -> None:
    """Live wording must not read as a correctness warranty -- it describes what
    is connected, not that the answers are right."""
    text = _app(LIVE).instructions or ""
    assert "attach-only" in text
    assert "SIMULATED" not in text
    for overclaim in ("verified", "accurate", "guaranteed", "correct"):
        assert overclaim not in text.lower()


def test_the_two_modes_differ_in_both_name_and_instructions() -> None:
    fake, live = _app(FAKE), _app(LIVE)
    assert fake.name != live.name
    assert fake.instructions != live.instructions


def test_a_fake_backed_response_is_still_indistinguishable() -> None:
    """THE HOLE, PINNED OPEN DELIBERATELY.

    This asserts the CURRENT, KNOWN-BAD property: nothing in a tool response
    reveals the adapter. It is not an endorsement -- it is a tripwire. If a
    later change makes responses self-identifying, this test fails and whoever
    made that change must come here, read why the disclosure was worded as it
    was, and update the wording to match the new, better reality.

    Without this, the disclosure text and the actual detectability could drift
    apart silently, which is the exact defect the wording exists to avoid.
    """
    composition = build_composition(FakeAdapter(), data_dir=tempfile.mkdtemp())
    composition.session.attach(4242)
    environment = composition.broker.require_environment()

    fields = environment.model_dump()
    assert set(fields) == {
        "aedt_version",
        "pyaedt_version",
        "python_version",
        "wrapper_version",
    }
    blob = " ".join(str(value) for value in fields.values()).lower()
    for tell in ("fake", "simulated", "canned", "mock", "test"):
        assert tell not in blob, (
            f"{tell!r} now appears in a fake-backed Environment. If responses "
            "have become self-identifying, update the disclosure in "
            "server/app.py -- it currently states that they are not."
        )
