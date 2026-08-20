"""The Done bar's second clause, proved: a client handshakes and calls tools.

THE GAP THIS CLOSES. Every other test in this package reads METADATA off the
app -- ``list_tools()`` names, ``_tool_manager._tools`` keys, ``app.name``,
``app.instructions`` -- and the suite's only ``call_tool`` went to a STAND-IN
server with a stand-in tool (``server_helpers.selection_server``, which exists
to measure the dispatch lock, not the surface). So none of the eleven registered
handlers was ever executed. Their ``broker.dispatch`` kwarg names, their contract
request construction, their return values and the wire shape those return values
serialize to were all unverified: the Done bar's "a local MCP client can complete
a handshake and call at least one tool end-to-end against the fake adapter" was
TRUE IN FACT and PROVED BY NOTHING.

WHAT IS REAL HERE AND WHAT IS NOT. Real: the production ``build_composition``,
the production ``build_app``, the SDK's own server loop, a real ``ClientSession``,
real JSON-RPC round trips, and a real ``FakeAdapter`` behind a real ``Session``
and ``Broker``. Not real: the transport is anyio memory streams rather than two
file descriptors (see ``connected_client``), and the backend is the fake adapter
-- which is what the Done bar asks for.

EVERY ASSERTION IS ON STRUCTURED CONTENT, not on ``is_error`` alone. A tool that
returned the wrong payload, or a handler that passed the wrong kwarg name to
``broker.dispatch``, would come back with ``is_error=False`` and a typed refusal
inside -- which is exactly the failure a bare ``is_error`` check cannot see.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from server_helpers import (
    DEFAULT_PID,
    FLAT_STRUCTURED,
    NESTED_UNDER_RESULT,
    composed_app,
    drive_client,
    payload,
)

from hfss_agent.server.tool_surface import TOOL_SURFACE

# The fake scenario's canned chain (adapter/fake/scenario.py ``_default_options``).
# Named here rather than inlined so the reason a value is expected is legible:
# these are the FAKE ADAPTER's data, and a test asserting on them is asserting
# that the call reached it.
FAKE_PROJECT = "patch_antenna"
FAKE_DESIGN = "HFSSDesign1"
FAKE_SETUP = "Setup1"
FAKE_SWEEP = "Sweep1"


def _select_chain(session):
    """Drive the whole selection chain the way a client would: list, then pick.

    Choices are read back from ``list_selection_options`` rather than hardcoded
    at every stage, so this exercises the two tools as a PAIR -- an options list
    that no longer feeds ``select`` is the kind of break a hardcoded choice
    hides.
    """

    async def stage(name):
        listed = await session.call_tool("list_selection_options", {"stage": name})
        body = payload("list_selection_options", listed.structured_content)
        options = body["options"]
        assert options, f"the fake offers no {name} options"
        choice = options[0]["value"]
        chosen = await session.call_tool("select", {"stage": name, "choice": choice})
        assert chosen.is_error is False
        return choice

    return stage


# --- the handshake ------------------------------------------------------------


def test_a_client_completes_the_handshake(tmp_path: Path) -> None:
    """CLAUSE (b), FIRST HALF. Read as a client receives it, not off the app.

    ``test_disclosure.py`` reads ``app.name`` and ``app.instructions`` as
    attributes. That proves ``build_app`` set them; it does not prove they
    survive the handshake and reach a client, which is a different claim and the
    one the disclosure depends on.
    """
    app, _ = composed_app(tmp_path, want_app=True)

    async def work(session, init):
        return init

    init = drive_client(app, work)
    assert init.server_info.name == "hfss-agent (SIMULATED)"
    assert init.server_info.version, "the server reported no version"
    assert init.instructions, "no instructions reached the client"
    assert "SIMULATED DATA" in init.instructions
    assert init.protocol_version, "no protocol version was negotiated"


def test_a_client_lists_every_tool_with_a_description_and_a_schema(
    tmp_path: Path,
) -> None:
    """What a client actually has to work with: eleven tools, each with prose and
    an input schema. A tool with no description is one a model must guess at."""
    app, expected = composed_app(tmp_path, want_app=True)

    async def work(session, _init):
        return (await session.list_tools()).tools

    tools = drive_client(app, work)
    assert {tool.name for tool in tools} == expected
    assert len(tools) == 11

    undescribed = sorted(t.name for t in tools if not (t.description or "").strip())
    assert not undescribed, f"tools offered with no description: {undescribed}"
    unschematised = sorted(
        t.name for t in tools if (t.input_schema or {}).get("type") != "object"
    )
    assert not unschematised, f"tools offered with no object schema: {unschematised}"


def test_the_contract_literal_reaches_the_clients_input_schema(
    tmp_path: Path,
) -> None:
    """``app.py``'s measured claim at ``set_design_intent``, checked.

    It says annotating with the contract's own ``Literal`` rather than ``str``
    is "what puts {"enum": ["s11", "vswr"]} in front of the caller BEFORE they
    call". That is a claim about the SCHEMA A CLIENT RECEIVES, so it can only be
    checked from the client side.
    """
    app, _ = composed_app(tmp_path, want_app=True)

    async def work(session, _init):
        return {t.name: t.input_schema for t in (await session.list_tools()).tools}

    schemas = drive_client(app, work)
    threshold = schemas["set_design_intent"]["properties"]["threshold_type"]
    assert threshold.get("enum") == ["s11", "vswr"], (
        f"threshold_type advertises {threshold!r}; with a bare ``str``"
        " annotation the enum disappears and a bad value reaches the handler."
    )


# --- the wire-shape asymmetry, asserted rather than assumed -------------------


def test_the_wire_shape_split_is_what_app_py_documents(tmp_path: Path) -> None:
    """EVERY tool driven, and each one's shape compared with its classification.

    ``app.py`` records the asymmetry -- a union return nests under ``result``, a
    single model is flat -- as SDK behaviour it absorbs rather than a choice it
    makes, and warns that nothing in the handler signatures reveals it. This
    turns that warning into a check: the tables in ``server_helpers`` are the
    written-down split, and this drives all eleven and requires reality to match.

    FAILS WHEN: the SDK changes how it serializes one of these, or a handler's
    return annotation changes between a union and a single model. Either is a
    silent break for every consumer reading ``structured_content``.
    """
    app, expected = composed_app(tmp_path, want_app=True)
    bundle = tmp_path / "shape-probe.json"

    calls = {
        "preflight_environment": {},
        "attach": {"process_id": DEFAULT_PID},
        "list_selection_options": {"stage": "project"},
        "select": {"stage": "project", "choice": FAKE_PROJECT},
        "get_session_status": {},
        "inspect_design": {},
        "set_design_intent": {
            "target_frequency_hz": 2.4e9,
            "threshold_type": "s11",
            "threshold_value": -10.0,
        },
        "get_design_intent": {},
        "clear_design_intent": {},
        "get_audit_log": {},
        "export_diagnostics_bundle": {"path": str(bundle)},
    }
    assert set(calls) == expected, (
        "this test must drive every registered tool; unclassified: "
        f"{sorted(expected - set(calls))}, stale: {sorted(set(calls) - expected)}"
    )
    assert NESTED_UNDER_RESULT | FLAT_STRUCTURED == expected, (
        "the wire-shape tables in server_helpers no longer cover the surface"
    )
    assert not NESTED_UNDER_RESULT & FLAT_STRUCTURED

    async def work(session, _init):
        seen = {}
        for name, arguments in calls.items():
            result = await session.call_tool(name, arguments)
            assert result.is_error is False, f"{name} errored: {result.content}"
            seen[name] = result.structured_content
        return seen

    structured = drive_client(app, work)
    for name, content in structured.items():
        # ``payload`` is what asserts the shape; a wrong classification raises
        # there, naming the tool.
        assert isinstance(payload(name, content), dict), name


# --- the deep path: a tool that reaches the adapter --------------------------


def test_inspect_design_reaches_the_fake_adapter_through_the_whole_chain(
    tmp_path: Path,
) -> None:
    """THE FULL DEPTH: client -> handler -> W-5 assembler -> broker -> session ->
    adapter, and back.

    ``inspect_design`` is the deepest registered path and the only one whose
    assembler dispatches twice (the read, then ``get_session_status`` for the
    provenance stamp). Asserting on the CANNED DATA is the point: these values
    exist nowhere but ``adapter/fake/scenario.py``, so seeing them here is proof
    the call reached the adapter rather than being answered somewhere above it.
    """
    app, _ = composed_app(tmp_path, want_app=True)

    async def work(session, _init):
        await session.call_tool("attach", {"process_id": DEFAULT_PID})
        stage = _select_chain(session)
        for name in ("project", "design", "setup", "sweep", "variation"):
            await stage(name)
        return await session.call_tool("inspect_design", {})

    result = drive_client(app, work)
    assert result.is_error is False
    body = payload("inspect_design", result.structured_content)

    assert "outcome" not in body, (
        f"inspect_design refused rather than reading: {body}. The selection "
        "chain did not complete, so the deep path was never exercised."
    )
    sections = body["sections"]
    assert sections["setups"]["read_status"] == "ok"
    assert sections["setups"]["data"] == [FAKE_SETUP]
    assert sections["sweeps"]["data"] == {FAKE_SETUP: [FAKE_SWEEP]}

    provenance = body["provenance"]
    assert provenance["project"] == FAKE_PROJECT
    assert provenance["design"] == FAKE_DESIGN
    assert provenance["contract_version"], "the stamp carries no contract version"


def test_a_section_filter_narrows_what_comes_back(tmp_path: Path) -> None:
    """The one handler argument that is a list of contract ``Literal``s. Proves
    ``sections`` is threaded through rather than ignored -- a handler that
    dropped it would return everything and still look successful."""
    app, _ = composed_app(tmp_path, want_app=True)

    async def work(session, _init):
        await session.call_tool("attach", {"process_id": DEFAULT_PID})
        stage = _select_chain(session)
        for name in ("project", "design", "setup", "sweep", "variation"):
            await stage(name)
        both = await session.call_tool("inspect_design", {})
        one = await session.call_tool("inspect_design", {"sections": ["setups"]})
        return both, one

    both, one = drive_client(app, work)
    all_sections = set(payload("inspect_design", both.structured_content)["sections"])
    filtered = set(payload("inspect_design", one.structured_content)["sections"])
    assert filtered == {"setups"}
    assert filtered < all_sections, "the filter returned everything"


# --- the broker-owned file tool ----------------------------------------------


def test_the_file_tool_writes_then_refuses_to_overwrite_then_obeys_overwrite(
    tmp_path: Path,
) -> None:
    """THE ONE TOOL THAT TOUCHES THE DISK, end to end over the protocol.

    ``export_diagnostics_bundle`` is assembler-backed (W-11): it dispatches
    ``get_audit_log`` and then writes through the broker's guarded export
    primitive. The no-silent-overwrite rule is a charter rule, and this is the
    only place on the tool surface it is reachable, so all three arms are driven
    from a client rather than from below.
    """
    app, _ = composed_app(tmp_path, want_app=True)
    bundle = tmp_path / "diagnostics.json"

    # SIZES ARE SAMPLED BETWEEN CALLS, NOT AFTER ALL THREE. The bundle embeds
    # the audit log, and every tool call appends to it -- so the file legitimately
    # grows between the first write and the forced one. Comparing a size read at
    # the end against the FIRST call's ``bytes_written`` measures that growth and
    # reports it as a byte-count defect; it was written that way first and did
    # exactly that.
    async def work(session, _init):
        await session.call_tool("attach", {"process_id": DEFAULT_PID})
        first = await session.call_tool(
            "export_diagnostics_bundle", {"path": str(bundle)}
        )
        after_write = bundle.stat().st_size
        again = await session.call_tool(
            "export_diagnostics_bundle", {"path": str(bundle)}
        )
        after_refusal = bundle.stat().st_size
        forced = await session.call_tool(
            "export_diagnostics_bundle", {"path": str(bundle), "overwrite": True}
        )
        after_force = bundle.stat().st_size
        return first, after_write, again, after_refusal, forced, after_force

    first, after_write, again, after_refusal, forced, after_force = drive_client(
        app, work
    )

    written = payload("export_diagnostics_bundle", first.structured_content)
    assert written["outcome"] == "written"
    assert bundle.exists(), "the tool reported a write that did not happen"
    assert after_write == written["bytes_written"], (
        "the reported byte count does not match the file on disk"
    )
    json.loads(bundle.read_text(encoding="utf-8"))  # it is a readable bundle

    refused = payload("export_diagnostics_bundle", again.structured_content)
    assert refused["outcome"] == "refused_existing_path"
    assert after_refusal == after_write, "the refused call modified the file anyway"

    replaced = payload("export_diagnostics_bundle", forced.structured_content)
    assert replaced["outcome"] == "written"
    assert after_force == replaced["bytes_written"], (
        "the forced overwrite reported a byte count the file does not have"
    )


def test_the_audit_log_records_the_calls_a_client_made(tmp_path: Path) -> None:
    """The surface writes history, and ``get_audit_log`` reads it back. Both
    halves over the protocol, so the round trip is proved rather than assumed."""
    app, _ = composed_app(tmp_path, want_app=True)

    async def work(session, _init):
        await session.call_tool("attach", {"process_id": DEFAULT_PID})
        await session.call_tool("get_session_status", {})
        return await session.call_tool("get_audit_log", {})

    result = drive_client(app, work)
    records = payload("get_audit_log", result.structured_content)["records"]
    names = [record["tool_name"] for record in records]
    assert "attach" in names and "get_session_status" in names
    assert all(record["risk_tier"] == "safe" for record in records)


# --- rejection happens before the handler ------------------------------------


def test_a_schema_violation_is_refused_without_reaching_the_handler(
    tmp_path: Path,
) -> None:
    """``app.py``'s claim that the contract ``Literal`` fails a bad value BEFORE
    dispatch, checked where it matters: no audit record is written, because no
    capability was dispatched. An error raised after dispatch would leave one."""
    app, _ = composed_app(tmp_path, want_app=True)

    async def work(session, _init):
        bad = await session.call_tool(
            "set_design_intent",
            {
                "target_frequency_hz": 2.4e9,
                "threshold_type": "bogus",
                "threshold_value": -10.0,
            },
        )
        history = await session.call_tool("get_audit_log", {})
        return bad, history

    bad, history = drive_client(app, work)
    assert bad.is_error is True
    assert "threshold_type" in str(bad.content)

    records = payload("get_audit_log", history.structured_content)["records"]
    assert not [r for r in records if r["tool_name"] == "set_design_intent"], (
        "a rejected call reached dispatch: the schema is being enforced after "
        "the handler rather than before it."
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"process_id": "not-a-pid"},
        {"process_id": 42.5},
    ],
    ids=["missing", "unparseable", "non-integral"],
)
def test_attach_refuses_malformed_arguments(
    arguments: dict, tmp_path: Path
) -> None:
    """The schema a client is handed is load-bearing, not decorative.

    ``{"process_id": "4242"}`` is deliberately NOT here: pydantic coerces a
    numeric string to ``int`` in both the SDK's derived argument model and the
    contract's ``AttachRequest``, so it is a well-formed call spelled loosely,
    not a malformed one. The cases below cannot be coerced to the declared type.
    """
    app, _ = composed_app(tmp_path, want_app=True)

    async def work(session, _init):
        return await session.call_tool("attach", arguments)

    assert drive_client(app, work).is_error is True


def test_an_unknown_tool_argument_is_DROPPED_rather_than_refused(
    tmp_path: Path,
) -> None:
    """A GAP BETWEEN app.py's CLAIM AND WHAT A CLIENT EXPERIENCES, pinned here
    rather than left to be rediscovered.

    ``app.py`` says constructing the contract request type makes the contract
    load-bearing, so that "field names, Literal domains and ``extra="forbid"``
    are then enforced by the schema the contract owns". The first two hold and
    are checked above. THE THIRD DOES NOT, for an unknown TOOL argument: the SDK
    derives its own argument model from the handler's signature, that model
    binds only the declared parameters, and an extra key is dropped before any
    contract type is constructed. ``AttachRequest(process_id=4242, unexpected=1)``
    raises; ``call_tool("attach", {...same...})`` succeeds.

    Measured, not assumed. This is benign today -- no wrong value results, and
    ignoring unknown input is ordinary protocol tolerance -- so it is recorded
    rather than fixed. FAILS WHEN: the SDK starts refusing unknown arguments, at
    which point app.py's paragraph becomes true and should say so.
    """
    app, _ = composed_app(tmp_path, want_app=True)

    async def work(session, _init):
        return await session.call_tool(
            "attach", {"process_id": DEFAULT_PID, "unexpected": "ignored"}
        )

    result = drive_client(app, work)
    assert result.is_error is False, (
        "the SDK now refuses unknown tool arguments. That is an improvement -- "
        "update app.py's REQUEST TYPES ARE CONSTRUCTED paragraph, which "
        "currently overstates what extra=\"forbid\" reaches, and delete this test."
    )
    assert payload("attach", result.structured_content)["connection_health"] == (
        "connected"
    )


# --- the descriptions a client is offered ------------------------------------
#
# WHAT A CLIENT SEES, TRANSCRIBED INDEPENDENTLY of ``TOOL_SURFACE`` -- the same
# technique ``test_tool_surface._SECTION_3_TOOLS`` uses for the seventeen §3
# names, and for the same reason: a test that read the table and compared it with
# itself would prove nothing.
#
# WHY THIS IS WORTH THE TRANSCRIPTION COST. Descriptions are the text a language
# model reads to decide WHICH TOOL TO CALL. They are the most consequential
# client-facing prose on the surface and, until Part 10, the least checked: two
# separate mutations were measured passing the whole suite -- rewriting a
# ``TOOL_SURFACE`` summary to "PLANTED: this summary no longer describes the
# tool", and replacing ``_describe``'s table lookup with ``return "a tool."``.
# Nothing anywhere read a description.
_EXPECTED_DESCRIPTIONS = {
    "preflight_environment": "Check this machine against the published support matrix.",
    # Names where the process id comes from, because no registered tool
    # enumerates them -- ``list_aedt_processes`` is deferred.
    "attach": (
        "Attach (attach-only) to a running AEDT process. This server cannot "
        "list process ids; obtain one from the operating system."
    ),
    "list_selection_options": "List the choices for a selection stage.",
    "select": "Select a project/design/setup/sweep/variation.",
    "get_session_status": "Report session health, selection chain, and suspect flag.",
    "inspect_design": "Read the structured design inspection sections.",
    "set_design_intent": "Persist the design intent, replacing any previous intent.",
    "get_design_intent": "Read the persisted design intent and its set-time context.",
    "clear_design_intent": "Clear the persisted design intent (tombstone write).",
    "get_audit_log": "Read the append-only audit log, optionally range-filtered.",
    "export_diagnostics_bundle": "Write a redacted diagnostics bundle for support.",
}


def _client_descriptions(app) -> dict[str, str]:
    async def work(session, _init):
        return {t.name: t.description for t in (await session.list_tools()).tools}

    return drive_client(app, work)


def test_the_description_a_client_sees_is_the_pinned_text(tmp_path: Path) -> None:
    """WHAT WOULD HAVE TO CHANGE FOR THIS TO FAIL, stated because a description
    test that checks only non-emptiness is not worth having:

      * any ``TOOL_SURFACE`` summary is reworded, added or removed -- the
        transcription above no longer matches and the failure names the tool and
        shows both strings;
      * ``_describe`` stops reading the table (returns a constant, hardcodes a
        string at the registration site, or looks up the wrong row);
      * a tool is registered with a description that does not come from
        ``_describe`` at all;
      * the SDK stops carrying ``description`` through to ``list_tools``.

    The first is the one that matters day to day. Rewording a description is a
    change to how a model chooses between tools, so it should be a deliberate
    edit HERE as well as in the table -- not something that lands unnoticed
    because the only check was that the field was a non-empty string.

    Read from ``list_tools()`` over a real client session rather than from the
    ``TOOL_SURFACE`` rows, so this is a claim about what is OFFERED, not about
    what is recorded.
    """
    app, registered = composed_app(tmp_path, want_app=True)
    assert set(_EXPECTED_DESCRIPTIONS) == registered, (
        "the transcription above no longer covers the registered surface: "
        f"missing {sorted(registered - set(_EXPECTED_DESCRIPTIONS))}, "
        f"stale {sorted(set(_EXPECTED_DESCRIPTIONS) - registered)}"
    )
    assert _client_descriptions(app) == _EXPECTED_DESCRIPTIONS


def test_the_client_description_and_the_table_summary_cannot_drift(
    tmp_path: Path,
) -> None:
    """``_describe``'s stated purpose, checked.

    Its docstring says the summary is read from the table "so the description a
    client sees and the summary the accounting table carries cannot drift". That
    was an assertion about a mechanism with nothing observing the mechanism's
    output. This compares the two ACROSS the SDK: the row's ``summary`` on one
    side, what ``list_tools()`` hands a client on the other.

    Kept separate from the pinned-text check above on purpose. That one fails
    when the WORDING changes; this one fails when the two sources DISAGREE -- and
    a reader hitting one failure rather than both learns which of the two
    happened.
    """
    app, _ = composed_app(tmp_path, want_app=True)
    offered = _client_descriptions(app)
    rows = {b.name: b.summary for b in TOOL_SURFACE}
    drifted = {
        name: (rows.get(name), description)
        for name, description in offered.items()
        if rows.get(name) != description
    }
    assert not drifted, (
        f"description a client sees differs from its tool_surface summary: "
        f"{drifted}. _describe must read the table, not restate it."
    )


def test_no_two_tools_share_a_description(tmp_path: Path) -> None:
    """Two tools a model cannot tell apart is a worse failure than a vague one.

    This is what a constant-returning ``_describe`` looks like from the caller's
    side, and it is the property that matters rather than the mechanism: eleven
    tools, eleven distinct descriptions.
    """
    app, _ = composed_app(tmp_path, want_app=True)
    offered = _client_descriptions(app)
    seen: dict[str, list[str]] = {}
    for name, description in offered.items():
        seen.setdefault(description, []).append(name)
    shared = {text: names for text, names in seen.items() if len(names) > 1}
    assert not shared, f"tools sharing one description: {shared}"


def test_no_deferred_tools_summary_reaches_a_client(tmp_path: Path) -> None:
    """The six deferred rows carry summaries too. None may be offered: a client
    shown a description for a tool it cannot call has been told about a
    capability that does not exist."""
    app, _ = composed_app(tmp_path, want_app=True)
    offered = set(_client_descriptions(app))
    deferred = {b.name for b in TOOL_SURFACE if b.status == "deferred"}
    leaked = sorted(offered & deferred)
    assert not leaked, f"deferred tools offered to a client: {leaked}"
