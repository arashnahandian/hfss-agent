"""The attach-time Environment's retention rules (W-5 prerequisite 2).

``_SessionState.environment`` exists so a downstream provenance stamp can name
the AEDT/PyAEDT/Python/wrapper versions it was produced under. Its whole value is
that it is present ONLY while the process it describes is still the attached one,
so these tests pin both halves: same-process transitions preserve it, and a
session-ending one drops it.

The mechanism is the existing one — the licence-free ``FakeAdapter`` driven by
scenario scripting (no sleeps, no live AEDT). A second, distinguishable
``Environment`` comes from mutating the test's OWN ``Scenario`` between attaches:
``Scenario`` is a mutable dataclass and the fake holds that same object, which is
how a static fake is made to answer differently on a later call.
"""

from __future__ import annotations

from session_helpers import (
    DEFAULT_PID,
    attached,
    build_full_chain,
    force_suspect,
    list_timeout_then,
    make_session,
)

from hfss_agent.adapter.fake import OpBehavior, Scenario
from hfss_agent.adapter.results import AdapterDisconnect
from hfss_agent.contract import Environment
from hfss_agent.session.status import _Health

OTHER_PID = 5678

# A second identity block, deliberately different in every field from the fake's
# default, so "the new process's environment" cannot be confused with a retained
# stale one.
RELAUNCHED = Environment(
    aedt_version="2027.1",
    pyaedt_version="1.3.0",
    python_version="3.12.9",
    wrapper_version="0.0.0",
)


def test_attach_retains_the_environment() -> None:
    session, _ = attached()
    environment = session.get_environment()
    assert environment is not None
    # The fake's default identity block, reaching the session unchanged.
    assert environment.aedt_version == "2026.1"
    assert environment.pyaedt_version == "1.2.0"


def test_detached_session_has_no_environment() -> None:
    session, _ = make_session()
    assert session.get_environment() is None


def test_reattach_to_a_different_process_replaces_the_environment() -> None:
    scenario = Scenario()
    session, _ = attached(scenario)
    assert session.get_environment() == scenario.environment

    # The user relaunched AEDT: a different process, running different versions.
    scenario.environment = RELAUNCHED
    session.attach(OTHER_PID)

    assert session.get_environment() == RELAUNCHED
    assert session._state.chain.process_id == OTHER_PID


def test_a_fault_that_loses_the_session_clears_the_environment() -> None:
    session, _ = attached(
        Scenario(behavior={"select": OpBehavior(fault=AdapterDisconnect(detail="x"))})
    )
    assert session.get_environment() is not None

    session.select("project", "patch_antenna")  # -> LOST

    assert session._state.health is _Health.LOST
    # No live process means no honest version to stamp: LOST drops it, exactly
    # like the chain. last_process_id survives (it is a re-attach hint, not a
    # claim about a running process); the environment deliberately does not.
    assert session.get_environment() is None
    assert session._state.last_process_id == DEFAULT_PID


def test_suspect_then_reverified_preserves_the_environment() -> None:
    session, _ = attached(list_timeout_then())
    original = session.get_environment()
    build_full_chain(session)  # plain select successes must also preserve it
    force_suspect(session)
    assert session.get_environment() == original  # SUSPECT is still the same process

    session.list_selection_options("project")  # guarded op -> verify -> ATTACHED

    assert session._state.health is _Health.ATTACHED
    assert session.get_session_status().suspect is False
    # Same process throughout, so the versions read at attach are still true.
    assert session.get_environment() == original


def test_reset_from_a_verify_mismatch_preserves_the_environment() -> None:
    # A selection change, not a session change: verify finds the design stale and
    # resets from it down, staying ATTACHED on the SAME process — so the identity
    # block must survive untouched.
    session, _ = attached(list_timeout_then())
    original = session.get_environment()
    build_full_chain(session, stale_stage="design")
    force_suspect(session)

    session.list_selection_options("project")  # -> verify -> _reset_from("design")

    assert session._state.health is _Health.ATTACHED
    assert session._state.chain.design is None  # the reset really happened
    assert session.get_environment() == original
