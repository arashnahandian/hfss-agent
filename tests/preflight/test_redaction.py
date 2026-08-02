"""W-11's redactor: what may leave the machine, and proof that it is removed.

THE SUITE THAT WATCHES THE REDACTION FAIL. A redaction pass nobody has seen
fail is not tested — it is asserted. So the negative control below neuters each
mechanism in turn and shows the planted identifier appearing, which is the only
evidence that its absence in every other test is caused by this module rather
than by the fixture never having carried it.

Neutered, never inverted (ADR-26 decision 16): inverting a guard perturbs
everything downstream and tells you nothing about what the guard is responsible
for.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping

import pytest
from preflight_helpers import (
    KNOWN_TOOL_NAMES,
    PLANTED_IDENTIFIERS,
    SECRET_ENVIRONMENT,
    hostile_audit_records,
)

from hfss_agent.contract import AuditRecord
from hfss_agent.preflight import redaction
from hfss_agent.preflight.redaction import (
    ALLOWED_ARGUMENT_KEYS,
    REDACTION_RULESET_VERSION,
    SELECTION_KEYS,
    SURVIVING_FIELDS,
    UNREGISTERED_TOOL_NAME,
    redact_audit_record,
    redact_audit_records,
)


def _strings(value: object) -> Iterator[str]:
    """Every string inside a JSON-shaped structure, keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _rendered(records=None) -> str:
    """The redacted fixture as one searchable blob: BOTH forms, deliberately.

    The serialised form is what the bundle is actually written in, so it is the
    shape a reader would search. But searching it ALONE is not sufficient, and
    this was found by the negative control rather than by reasoning: JSON
    escapes a backslash, so the planted Windows path
    ``D:\\clients\\...`` can never appear in ``json.dumps`` output in the form
    the fixture plants it — the assertion "that path is absent" would have
    passed no matter what the redactor did. A test that passes for the wrong
    reason is worse than a missing one, because it reports coverage it does not
    have.

    So the raw strings are searched alongside the serialised form. Any
    identifier is now caught in whichever encoding it survives in.
    """
    source = hostile_audit_records() if records is None else records
    redacted = redact_audit_records(source, KNOWN_TOOL_NAMES)
    return "\n".join([json.dumps(redacted), *_strings(redacted)])


# --- the planted identifiers -------------------------------------------------


@pytest.mark.parametrize("identifier", PLANTED_IDENTIFIERS)
def test_no_planted_identifier_survives(identifier: str) -> None:
    assert identifier not in _rendered()


def test_the_historical_project_is_redacted_though_it_is_not_the_selection() -> None:
    """The record that discriminates key-based redaction from value matching.

    ``kestrel-radar-v7`` is in the LOG, not in the live chain. A matcher built
    from the current selection never sees it — and in the case that matters
    most, a bundle exported pre-attach or after a failure, the chain is empty
    and such a matcher would redact nothing at all.
    """
    rendered = _rendered()
    assert "kestrel-radar-v7" not in rendered
    assert "northwind-defence" not in rendered
    assert r"D:\clients" not in rendered


def test_the_project_path_never_survives() -> None:
    """``selection_state["project"]`` carries the project's ABSOLUTE PATH, which
    names the user and often the client directory. It is dropped by the same
    fixed-key rule as the name, needing no rule of its own."""
    assert ".aedt" not in _rendered()


def test_variation_values_are_geometry_and_do_not_survive() -> None:
    """The finding this fixture exists to pin: ``variation`` is not an identity
    problem, it is a GEOMETRY one. Variable names and dimensions are exactly
    what spec Point 21 excludes, and they sit inside the field everyone reads as
    a name problem. The hash goes too — not a name, but a stable handle that
    correlates two bundles from one design."""
    rendered = _rendered()
    assert "element_pitch_mm" not in rendered
    assert "12.5" not in rendered
    assert "substrate_h_mm" not in rendered
    assert "sha256:kestrelvariation" not in rendered


def test_no_secret_bearing_environment_value_can_reach_a_record() -> None:
    """Belt and braces, and the braces are structural: the AEDT probe returns
    install-root NAMES only, so a licence server or an API token never enters
    the process's view of the environment. Asserted anyway, because "it cannot
    get here" is the kind of claim that stops being true quietly."""
    rendered = _rendered()
    for name, value in SECRET_ENVIRONMENT.items():
        assert value not in rendered
        assert name not in rendered


# --- the presence map --------------------------------------------------------


def test_the_presence_map_keeps_the_shape_and_erases_every_value() -> None:
    first = redact_audit_record(hostile_audit_records()[0], KNOWN_TOOL_NAMES)
    presence = first["selection_present"]
    assert tuple(presence) == SELECTION_KEYS
    assert all(isinstance(value, bool) for value in presence.values())
    assert presence == dict.fromkeys(SELECTION_KEYS, True)


def test_the_presence_map_answers_was_a_design_selected() -> None:
    """The load-bearing fact survives; which design never does."""
    records = hostile_audit_records()
    fully_selected = redact_audit_record(records[0], KNOWN_TOOL_NAMES)
    nothing_selected = redact_audit_record(records[1], KNOWN_TOOL_NAMES)
    partly_selected = redact_audit_record(records[2], KNOWN_TOOL_NAMES)

    assert fully_selected["selection_present"]["design"] is True
    assert nothing_selected["selection_present"]["design"] is False
    assert partly_selected["selection_present"]["design"] is True
    assert partly_selected["selection_present"]["sweep"] is False


def test_an_unexpected_selection_key_is_never_carried_across() -> None:
    """Read through ``SELECTION_KEYS``, not through the record's own dict, so a
    key that should not be there is never looked at."""
    record = hostile_audit_records()[0]
    record.selection_state["customer_reference"] = "northwind-defence"
    redacted = redact_audit_record(record, KNOWN_TOOL_NAMES)
    assert "customer_reference" not in redacted["selection_present"]
    assert "northwind-defence" not in json.dumps(redacted)


# --- the arguments allow-list ------------------------------------------------


def test_every_dispatch_argument_is_dropped_in_version_one() -> None:
    redacted = redact_audit_records(hostile_audit_records(), KNOWN_TOOL_NAMES)
    assert [entry["arguments"] for entry in redacted] == [{}, {}, {}]
    assert [entry["arguments_dropped"] for entry in redacted] == [2, 0, 2]


def test_the_allow_list_is_empty_and_that_is_the_decision() -> None:
    assert ALLOWED_ARGUMENT_KEYS == frozenset()


def test_an_unreviewed_argument_key_is_dropped_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rule that survives a future capability nobody has reviewed.

    A deny-list would ship ``customer_reference``'s value the day someone
    registers a tool declaring it. This shows the opposite default, and shows
    the mechanism is real by allow-listing one key and watching only that key
    survive.
    """
    record = hostile_audit_records()[0]
    record.sanitized_arguments["customer_reference"] = "northwind-defence"
    assert "northwind-defence" not in json.dumps(
        redact_audit_record(record, KNOWN_TOOL_NAMES)
    )

    monkeypatch.setattr(redaction, "ALLOWED_ARGUMENT_KEYS", frozenset({"stage"}))
    permitted = redact_audit_record(record, KNOWN_TOOL_NAMES)
    assert permitted["arguments"] == {"stage": "project"}
    assert "northwind-defence" not in json.dumps(permitted)


def test_argument_key_names_are_dropped_with_their_values() -> None:
    """A key called ``customer_reference`` discloses a concept even with its
    value removed, so unlike ``selection_state`` there is no presence map
    here."""
    rendered = _rendered()
    assert "choice" not in rendered
    assert "stage" not in rendered


# --- the tool_name guard -----------------------------------------------------


def test_a_registered_tool_name_survives_verbatim() -> None:
    redacted = redact_audit_records(hostile_audit_records(), KNOWN_TOOL_NAMES)
    assert redacted[0]["tool_name"] == "select"
    assert redacted[2]["tool_name"] == "select"


def test_a_caller_controlled_tool_name_is_replaced() -> None:
    """``Broker.dispatch`` records the name it was HANDED when the registry has
    no such capability, so an LLM-driven caller can put arbitrary text — here, a
    customer's name wearing a tool's clothes — straight into the log."""
    redacted = redact_audit_records(hostile_audit_records(), KNOWN_TOOL_NAMES)
    assert redacted[1]["tool_name"] == UNREGISTERED_TOOL_NAME
    assert "export_northwind_q3_report" not in json.dumps(redacted)


def test_the_replacement_loses_nothing_diagnostic() -> None:
    """``outcome`` already carries the fact a support engineer needs. WHICH
    unregistered name was attempted is not diagnostic; that it was attempted
    is."""
    redacted = redact_audit_records(hostile_audit_records(), KNOWN_TOOL_NAMES)
    assert redacted[1]["outcome"] == "unknown_capability"
    assert redacted[1]["risk_tier"] is None


def test_an_empty_registry_replaces_every_name() -> None:
    """The guard is driven by the supplied names, not by a hardcoded list, so a
    caller that supplies none redacts everything rather than failing open."""
    redacted = redact_audit_records(hostile_audit_records(), frozenset())
    assert {entry["tool_name"] for entry in redacted} == {UNREGISTERED_TOOL_NAME}


# --- the keep-list ----------------------------------------------------------


def test_the_surviving_fields_are_exactly_the_documented_six() -> None:
    assert SURVIVING_FIELDS == (
        "timestamp",
        "tool_name",
        "risk_tier",
        "outcome",
        "duration",
        "session_degraded",
    )


def test_the_output_keys_are_the_survivors_plus_the_transformed_three() -> None:
    """Transformed fields are RENAMED, so a reader cannot mistake a presence map
    for the selection state it replaced."""
    redacted = redact_audit_record(hostile_audit_records()[0], KNOWN_TOOL_NAMES)
    assert set(redacted) == set(SURVIVING_FIELDS) | {
        "selection_present",
        "arguments",
        "arguments_dropped",
    }


def test_the_dropped_fields_are_absent_by_name() -> None:
    redacted = redact_audit_record(hostile_audit_records()[0], KNOWN_TOOL_NAMES)
    assert "selection_state" not in redacted
    assert "sanitized_arguments" not in redacted
    assert "snapshot_id" not in redacted


def test_snapshot_id_is_dropped_even_when_a_record_carries_one() -> None:
    """Dropped on principle, not because it is currently always None. The broker
    passes ``snapshot_id=None`` for every capability on today's surface, so
    keeping it would be a survivor by vacuity — and admitting a field because it
    is currently always null is how an allow-list rots."""
    record = hostile_audit_records()[0]
    with_snapshot = record.model_copy(update={"snapshot_id": "snap-kestrel-0001"})
    assert "snap-kestrel-0001" not in json.dumps(
        redact_audit_record(with_snapshot, KNOWN_TOOL_NAMES)
    )


def test_surviving_values_are_carried_verbatim() -> None:
    record = hostile_audit_records()[0]
    redacted = redact_audit_record(record, KNOWN_TOOL_NAMES)
    assert redacted["timestamp"] == record.timestamp.isoformat()
    assert redacted["risk_tier"] == "safe"
    assert redacted["outcome"] == "ok"
    assert redacted["duration"] == 0.125
    assert redacted["session_degraded"] is False


def test_the_result_is_json_serialisable() -> None:
    """A plain dict, deliberately not a contract model: there is no schema for a
    redacted record and adding one would be a semver event for a fragment that
    never crosses the engine seam."""
    json.dumps(redact_audit_records(hostile_audit_records(), KNOWN_TOOL_NAMES))


def test_the_ruleset_version_is_pinned() -> None:
    """Bumped on any change to what is kept or dropped, so a bundle from an
    older, more permissive ruleset is never mistaken for a stricter one."""
    assert REDACTION_RULESET_VERSION == 1


# --- the rot test ------------------------------------------------------------


def test_a_field_added_to_the_schema_is_dropped_rather_than_leaked() -> None:
    """WHAT MAKES DROP-BY-DEFAULT A PROPERTY RATHER THAN AN INTENTION.

    The result is built by NAMING the fields that survive, never by copying the
    record and removing fields from it. Under this construction a field added to
    ``AuditRecord`` tomorrow is absent from the output, so an un-updated
    redactor fails as a missing diagnostic. Under copy-and-remove it would be
    present, and the same oversight would be a disclosure.

    A scratch subclass rather than an edit to the real schema: the point is the
    redactor's shape, and mutating a contract model to prove it would be a
    semver event for a test.
    """

    class _FutureAuditRecord(AuditRecord):
        customer_reference: str

    future = _FutureAuditRecord(
        **hostile_audit_records()[0].model_dump(),
        customer_reference="northwind-defence",
    )
    redacted = redact_audit_record(future, KNOWN_TOOL_NAMES)
    assert "customer_reference" not in redacted
    assert "northwind-defence" not in json.dumps(redacted)


# --- the corruption control --------------------------------------------------


def test_a_design_named_ok_is_dropped_and_corrupts_no_outcome() -> None:
    """THE TEST THAT MAKES THE VALUE-MATCHER HAZARD CONCRETE.

    Record 3's design is legitimately named ``ok``. A known-value matcher built
    from the selection would rewrite that substring wherever it appeared —
    including the ``outcome`` field of every record in the log, whose value is
    also ``ok``. It would not merely be incomplete, it would destroy the log's
    meaning while reporting success. Active damage beats incompleteness as a
    reason to refuse a mechanism, and this is the evidence.
    """
    redacted = redact_audit_records(hostile_audit_records(), KNOWN_TOOL_NAMES)
    assert redacted[2]["selection_present"]["design"] is True
    assert "design" not in redacted[2]["arguments"]
    assert [entry["outcome"] for entry in redacted] == [
        "ok",
        "unknown_capability",
        "ok",
    ]


# --- the negative control ----------------------------------------------------
#
# NEUTERED, NOT INVERTED (ADR-26 decision 16). Each mechanism is replaced by an
# identity function in turn, and the identifier it is responsible for is shown
# to appear. Without this, every assertion above is equally satisfied by a
# fixture that never carried the identifier in the first place.


def test_neutering_the_presence_map_leaks_the_project_and_its_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        redaction, "_selection_presence", lambda selection: dict(selection)
    )
    leaked = _rendered()
    assert "kestrel-radar-v7" in leaked
    assert r"D:\clients\northwind-defence" in leaked
    assert "element_pitch_mm" in leaked
    assert "sha256:kestrelvariation" in leaked


def test_the_search_form_would_catch_a_backslash_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pins the fix for a vacuous assertion the negative control exposed.

    ``json.dumps`` escapes a backslash, so the planted Windows path cannot
    appear in serialised output in the form the fixture plants it — searching
    only the serialised blob made "that path is absent" true regardless of what
    the redactor did. ``_rendered`` searches the raw strings as well, and this
    test fails if someone narrows it back.
    """
    monkeypatch.setattr(
        redaction, "_selection_presence", lambda selection: dict(selection)
    )
    planted = r"D:\clients\northwind-defence\kestrel\kestrel-radar-v7.aedt"
    assert planted in _rendered()
    assert planted not in json.dumps(
        redact_audit_records(hostile_audit_records(), KNOWN_TOOL_NAMES)
    )


def test_neutering_the_argument_filter_leaks_the_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(redaction, "_arguments", lambda arguments: dict(arguments))
    leaked = _rendered()
    assert "kestrel-radar-v7" in leaked
    assert "choice" in leaked


def test_neutering_the_tool_name_guard_leaks_the_caller_supplied_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(redaction, "_tool_name", lambda record, known: record.tool_name)
    assert "export_northwind_q3_report" in _rendered()


def test_the_redaction_is_restored_after_each_neutering() -> None:
    """Green again with nothing patched — so the leaks above were caused by the
    neutering rather than by test order or a mutated fixture."""
    rendered = _rendered()
    for identifier in PLANTED_IDENTIFIERS:
        assert identifier not in rendered
