"""The fake-adapter disclosure (W-1): what the handshake says, and what it cannot.

THIS TESTS A DISCLOSURE, NOT A GUARD, and the distinction is the point. The
disclosure is delivered once, at initialize, and the host may render it,
summarise it, or ignore it. It changes nothing downstream: the values a
simulated session returns are not marked and are not detectable.
``test_a_fake_backed_response_is_still_indistinguishable`` pins that hole open
on purpose, so nobody later reads the presence of a disclosure as evidence
that simulated data is identifiable -- and
``test_the_tell_check_finds_a_tell_where_one_exists`` is its companion limb,
because an absence assertion with no demonstration that the check can FIND the
thing is an assertion that cannot fail.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from server_helpers import DEFAULT_PID, composed_app, drive_client, payload

from hfss_agent.adapter.fake import FakeAdapter
from hfss_agent.preflight import REAL_PROBES
from hfss_agent.server import FAKE, LIVE, build_composition
from hfss_agent.server.app import build_app
from hfss_agent.server.tool_surface import DEFERRED_TOOLS, binding_for


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
    assert "do not report any value from this server as a measurement" in text


def test_the_fake_instructions_separate_what_is_invented_from_what_is_real(
) -> None:
    """THE PART 11 CORRECTION, PINNED.

    The notice used to say "every value it returns ... is canned test data
    invented by this package". Measured false: preflight_environment closes
    over REAL_PROBES and reports the operator's own interpreter and package
    versions; get_audit_log returns real timestamps; export_diagnostics_bundle
    really writes a file. A user who believed the old sentence would discount
    a true failure about their own machine, so over-warning is not the
    harmless direction here.

    This pins the THREE-PART SHAPE rather than any one phrase: what is
    invented, what is real, and that some responses mix both. A rewrite that
    collapses it back to a single sentence fails here.
    """
    text = _app(FAKE).instructions or ""
    assert "WHAT IS INVENTED" in text
    assert "WHAT IS REAL" in text
    assert "MIX THE TWO" in text
    # The three tools whose real output the old wording denied.
    for tool in ("preflight_environment", "get_audit_log",
                 "export_diagnostics_bundle"):
        assert tool in text, f"{tool} is not named among the real values"
    # The instruction that the old wording made impossible to give.
    assert "do not dismiss a preflight failure" in text


def test_the_fake_instructions_admit_their_own_limits() -> None:
    """THE SENTENCE THAT MUST NOT BE SOFTENED, and the one that was wrong.

    A disclosure that implies the values are marked would be worse than none: a
    reader would look for the marker, not find one, and conclude the data is
    live. So the text still has to state that individual responses carry no
    marker -- that half is load-bearing and is asserted below.

    WHAT CHANGED IN PART 11: the text used to say "This notice is the ONLY
    indication that the data is simulated", and this test pinned that phrase.
    It was false. The server NAME also carries the warning -- it ends in
    " (SIMULATED)", set three lines above the notice in ``build_app`` and
    asserted by ``test_the_fake_suffixes_the_server_name`` in this same file.
    So the claim is no longer made and this test no longer looks for it;
    it now requires the notice to account for BOTH signals, which is what a
    reader needs in order to know what to carry forward.
    """
    text = _app(FAKE).instructions or ""
    assert "TWO THINGS IN THIS HANDSHAKE CARRY THIS WARNING" in text
    assert "(SIMULATED)" in text, (
        "the notice does not mention the server-name marker, so a reader is "
        "not told about the one signal that survives a dropped instructions "
        "blob"
    )
    assert "INDIVIDUAL RESPONSES CARRY NO MARKER" in text


# WHAT THE OVERCLAIM CHECK IS, STATED SO IT IS NOT MISTAKEN FOR MORE. This is
# a FOUR-WORD BLOCKLIST STANDING IN FOR A CLAIM ABOUT MEANING, not a proof of
# it. "Reliable", "trustworthy", "validated" and "authoritative" would all
# pass it while making exactly the warranty the live wording must not make.
# It is kept because these four are the words a draft actually reaches for,
# and a cheap tripwire on the likely wording beats no tripwire at all -- but
# a reviewer reading new instructions text is still the guard, and this is
# not a substitute for that.
_OVERCLAIMS = ("verified", "accurate", "guaranteed", "correct")


def _overclaims_in(text: str) -> list[str]:
    return [word for word in _OVERCLAIMS if word in text.lower()]


def test_the_live_instructions_claim_no_more_than_the_connection() -> None:
    """Live wording must not read as a correctness warranty -- it describes what
    is connected, not that the answers are right."""
    text = _app(LIVE).instructions or ""
    assert "attach-only" in text
    assert "SIMULATED" not in text
    assert _overclaims_in(text) == []


def test_the_overclaim_check_finds_an_overclaim_when_there_is_one() -> None:
    """THE COMPANION LIMB the standing rule requires for any "X appears
    nowhere" assertion: the same check, shown FINDING X where X exists.

    Without this, a detector that had stopped matching -- a case change, a
    typo in the word list, a lowercasing that went missing -- would leave the
    assertion above permanently and silently green.
    """
    assert _overclaims_in("Every value is GUARANTEED accurate.") == [
        "accurate",
        "guaranteed",
    ]
    assert _overclaims_in("Values are read from that session.") == []


# The five capabilities ``_LIVE_INSTRUCTIONS`` tells a client NOT to plan around,
# paired with the ``tool_surface`` row each phrase is denying.
_DENIED_IN_LIVE_INSTRUCTIONS = {
    "HFSS validation": "validate_setup",
    "solution-validity gating": "check_solution_validity",
    "S-parameter metrics": "compute_metrics",
    "solver health": "get_solve_health",
    "result export": "export_results",
}


def test_the_live_instructions_denial_list_matches_the_deferred_rows() -> None:
    """A HAZARD PART 11 CREATED, CLOSED IN THE SAME BREATH.

    ``_LIVE_INSTRUCTIONS`` now ENUMERATES the surface -- what it offers and what
    it does not -- which is a real improvement over advertising metric formulas
    no tool reaches. But an enumeration goes stale: the day Step 3.3 registers
    ``validate_setup``, that paragraph starts telling every client the tool does
    not exist, and nothing else in the suite would notice. Deferral rows have
    self-invalidating tests for exactly this reason; this gives the prose one
    too.

    BOTH DIRECTIONS. A phrase must be in the text AND its tool must still be
    deferred; and the denial list plus ``list_aedt_processes`` -- which the
    attach sentence covers instead, since it is about where a process id comes
    from rather than a capability -- must be EXACTLY the deferred set. A seventh
    deferral, or a sixth registration, fails here.
    """
    text = _app(LIVE).instructions or ""
    for phrase, tool in _DENIED_IN_LIVE_INSTRUCTIONS.items():
        assert phrase in text, f"the live instructions no longer deny {phrase!r}"
        binding = binding_for(tool)
        assert binding is not None and binding.status == "deferred", (
            f"the live instructions tell clients {tool} is unavailable, but its "
            "tool_surface row is no longer deferred. Register it in the text or "
            "the text is now lying to every client."
        )
    covered = set(_DENIED_IN_LIVE_INSTRUCTIONS.values()) | {"list_aedt_processes"}
    assert covered == set(DEFERRED_TOOLS), (
        "the deferred set and what the live instructions account for have "
        f"diverged. Only in the text: {sorted(covered - set(DEFERRED_TOOLS))}. "
        f"Only deferred: {sorted(set(DEFERRED_TOOLS) - covered)}."
    )


def test_the_live_instructions_tell_a_client_where_a_process_id_comes_from(
) -> None:
    """The sixth deferral, handled in prose rather than in the denial list.

    ``list_aedt_processes`` is deferred, so no registered tool enumerates AEDT
    processes -- and ``attach`` requires one. Without this sentence a client is
    handed a required argument with no stated source. Also said in ``attach``'s
    own description, because a host may drop instructions but a tool description
    reaches the model at the moment it chooses to call.
    """
    text = _app(LIVE).instructions or ""
    assert "cannot enumerate them" in text
    assert binding_for("list_aedt_processes").status == "deferred"
    assert "cannot list process ids" in binding_for("attach").summary


def test_the_two_modes_differ_in_both_name_and_instructions() -> None:
    fake, live = _app(FAKE), _app(LIVE)
    assert fake.name != live.name
    assert fake.instructions != live.instructions


# The words that would betray a simulated backend if one of them leaked into a
# value. Deliberately broad -- "test" included -- because the claim being
# checked is broad: that NOTHING marks a response.
_TELLS = ("fake", "simulated", "canned", "mock", "test")


def _tells_in(text: str) -> list[str]:
    lowered = text.lower()
    return [tell for tell in _TELLS if tell in lowered]


# Responses that echo a CALLER-SUPPLIED PATH are excluded below, and the
# exclusion is about the test harness rather than the property: under pytest a
# tmp_path contains "pytest-of-<user>/test_<name>", so ``get_audit_log`` (whose
# records carry the arguments) and ``export_diagnostics_bundle`` (whose result
# carries the path) would report a "test" tell that came from the test's own
# directory name, not from the adapter. Every tool that returns ADAPTER-DERIVED
# data is driven.
_TELL_PROBE_CALLS = (
    ("attach", {"process_id": DEFAULT_PID}),
    ("list_selection_options", {"stage": "project"}),
    ("select", {"stage": "project", "choice": "patch_antenna"}),
    ("select", {"stage": "design", "choice": "HFSSDesign1"}),
    ("select", {"stage": "setup", "choice": "Setup1"}),
    ("select", {"stage": "sweep", "choice": "Sweep1"}),
    ("select", {"stage": "variation", "choice": "sha256:defaultvariation"}),
    ("get_session_status", {}),
    ("inspect_design", {}),
    ("preflight_environment", {}),
    ("get_design_intent", {}),
)


def test_a_fake_backed_response_is_still_indistinguishable(tmp_path: Path) -> None:
    """THE HOLE, PINNED OPEN DELIBERATELY -- and now actually read off
    RESPONSES.

    This test was named for responses and its docstring claimed "nothing in a
    tool response reveals the adapter", while its body called
    ``broker.require_environment()`` and inspected four fields of one object.
    No tool was invoked. It now drives eleven real calls over a client session
    and searches the structured content each one returns.

    It asserts the CURRENT, KNOWN-BAD property: nothing in a tool response
    reveals the adapter. That is not an endorsement -- it is a tripwire. If a
    later change makes responses self-identifying, this fails and whoever made
    that change must come here, read why the disclosure was worded as it was,
    and update the wording to match the new, better reality.

    READ THIS WITH THE DISCLOSURE TEXT, NOT ALONE. Part 11 corrected the fake
    instructions: they no longer claim that "every value it returns ... is
    canned test data", because that was false for ``preflight_environment``,
    ``get_audit_log`` and ``export_diagnostics_bundle``. The notice now
    separates what is invented from what is real, and
    ``test_the_fake_instructions_separate_what_is_invented_from_what_is_real``
    pins that shape while
    ``test_the_disclosures_claim_about_real_values_is_true`` checks the claim
    against the running system. THIS test covers the other half: that no
    response says WHICH of its values came from which side. If that ever
    changes, all three move together.
    """
    app, _ = composed_app(tmp_path, want_app=True)

    async def work(session, _init):
        seen = {}
        for name, arguments in _TELL_PROBE_CALLS:
            result = await session.call_tool(name, arguments)
            assert result.is_error is False, f"{name} errored: {result.content}"
            seen[name] = json.dumps(result.structured_content, default=str)
        return seen

    responses = drive_client(app, work)
    assert len(responses) == len({name for name, _ in _TELL_PROBE_CALLS})
    betrayed = {
        name: _tells_in(body)
        for name, body in responses.items()
        if _tells_in(body)
    }
    assert not betrayed, (
        f"a fake-backed response now identifies itself: {betrayed}. If responses "
        "have become self-identifying, update the disclosure in server/app.py "
        "-- it currently states, in as many words, that they are not."
    )


def test_the_tell_check_finds_a_tell_where_one_exists() -> None:
    """THE COMPANION LIMB. The same check, shown FINDING a tell.

    ``app.name`` is the ready example and the honest one: the server name IS
    marked -- ``"hfss-agent (SIMULATED)"`` -- so the detector applied to it
    must fire. If it does not, the absence assertion above is proving nothing
    and would stay green through any change.

    Worth noticing while you are here: that the NAME is marked while responses
    are not is the whole shape of this disclosure. The name is the one signal
    a client carries forward without being asked to.
    """
    assert _tells_in(_app(FAKE).name) == ["simulated"]
    assert _tells_in(_app(LIVE).name) == []
    # And on a response-shaped payload, so the limb covers the same kind of
    # input the absence check reads.
    marked = json.dumps({"environment": {"aedt_version": "2026.1 (fake)"}})
    assert _tells_in(marked) == ["fake"]


def test_the_disclosures_claim_about_real_values_is_true(tmp_path: Path) -> None:
    """THE DISCLOSURE'S FACTS, CHECKED AGAINST THE RUNNING SYSTEM.

    Every other test in this file pins WORDING. This one asks whether the
    wording is TRUE -- which is the failure mode that produced the Part 11
    correction in the first place: a sentence everyone had read, nobody had
    checked, and four tests were happily pinning.

    The notice makes three checkable factual claims. Each is checked here
    against a real fake-backed session:

      * "preflight_environment reads the Python, PyAEDT and wrapper versions
        actually installed here" -- compared with the real probes;
      * "after you attach it ... says aedt_version_source=\"attached_session\"";
      * "get_audit_log returns ... real timestamps".
    """
    composition = build_composition(FakeAdapter(), data_dir=str(tmp_path))
    app = build_app(composition, adapter_kind=FAKE)

    async def work(session, _init):
        await session.call_tool("attach", {"process_id": DEFAULT_PID})
        environment = await session.call_tool("preflight_environment", {})
        history = await session.call_tool("get_audit_log", {})
        status = await session.call_tool("get_session_status", {})
        for stage, choice in (
            ("project", "patch_antenna"),
            ("design", "HFSSDesign1"),
            ("setup", "Setup1"),
            ("sweep", "Sweep1"),
            ("variation", "sha256:defaultvariation"),
        ):
            await session.call_tool("select", {"stage": stage, "choice": choice})
        inspected = await session.call_tool("inspect_design", {})
        return (
            environment.structured_content,
            history.structured_content,
            status.structured_content,
            inspected.structured_content,
        )

    preflight, audit, status, inspected = drive_client(app, work)
    reported = preflight["environment"]

    # CLAIM 1: the versions are this machine's, not the fake's.
    assert reported["python_version"] == REAL_PROBES.python_version()
    assert reported["wrapper_version"] == REAL_PROBES.wrapper_version()
    # The fake holds its own, different constants for these; that the report
    # matches the PROBES is what shows which source preflight actually used.
    canned = composition.broker.require_environment().model_dump()
    assert canned["python_version"] == "3.12.4"
    assert canned["wrapper_version"] == "0.0.0"

    # CLAIM 2: a true field naming a session that is not real.
    assert reported["aedt_version_source"] == "attached_session"
    assert reported["aedt_version"] == canned["aedt_version"]

    # CLAIM 3: the audit timestamps are real clock readings, not canned ones.
    records = audit["records"]
    assert records, "no audit history to check"
    stamped = datetime.fromisoformat(
        records[-1]["timestamp"].replace("Z", "+00:00")
    )
    age = abs((datetime.now(timezone.utc) - stamped).total_seconds())
    assert age < 300, f"audit timestamp is {age:.0f}s from now; not a real clock"

    # CLAIM 4: "everything in the selection chain EXCEPT the process id you
    # passed to attach". The exception is real and the notice has to carve it
    # out -- an earlier Part 11 draft said the whole chain was invented.
    chain = payload("get_session_status", status)["selection"]
    assert chain["process_id"] == DEFAULT_PID, (
        "the process id is the caller's own value echoed back, which is why the "
        "notice excepts it from what is invented"
    )

    # CLAIM 5: the provenance stamp's versions come from the SIMULATED session,
    # not from the real probes -- so "everything about this process is real"
    # would have been an overclaim, and the notice says so instead.
    provenance = payload("inspect_design", inspected)["provenance"]
    assert provenance["wrapper_version"] == canned["wrapper_version"]
    assert provenance["wrapper_version"] != REAL_PROBES.wrapper_version()


def test_the_attached_environment_carries_no_tell_either() -> None:
    """The original four-field check, KEPT rather than replaced.

    ``Environment`` is the one object whose SHAPE the disclosure names -- it
    says a response's "environment versions are indistinguishable from a live
    session's" -- so pinning its field set is a separate, narrower guarantee
    than the response sweep above: a NEW field appearing here is a change to
    what the disclosure is talking about.
    """
    composition = build_composition(FakeAdapter(), data_dir=tempfile.mkdtemp())
    composition.session.attach(DEFAULT_PID)
    fields = composition.broker.require_environment().model_dump()
    assert set(fields) == {
        "aedt_version",
        "pyaedt_version",
        "python_version",
        "wrapper_version",
    }
    blob = " ".join(str(value) for value in fields.values())
    assert _tells_in(blob) == []
