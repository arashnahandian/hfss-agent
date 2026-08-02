"""W-11's diagnostics bundle: the document, its honesty, and the write path.

THE SEARCH FORM IS ITSELF UNDER TEST HERE. Part 3a's negative control found an
assertion that could not fail — ``json.dumps`` escapes a backslash, so a planted
Windows path could never appear in serialised output in the spelling the fixture
plants, and "that path is absent" was true regardless of what the redactor did.
So every leak assertion below searches BOTH the serialised document and its raw
strings, and two tests below pin that the search form can actually see a
backslash path and an escaped character. A control whose search form cannot see
the thing it looks for is not a control.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping

import pytest
from preflight_helpers import (
    PLANTED_IDENTIFIERS,
    SECRET_ENVIRONMENT,
    bundle_broker,
    fixture_probes,
    root_names,
    write_hostile_log,
)

from hfss_agent.broker import BrokerFileError
from hfss_agent.contract.tool_io import ExportFailed, ExportRefused, ExportWritten
from hfss_agent.preflight import bundle as bundle_module
from hfss_agent.preflight.bundle import (
    BUNDLE_FORMAT_VERSION,
    DiagnosticsBundleError,
    build_diagnostics_bundle,
    export_diagnostics_bundle,
)
from hfss_agent.preflight.redaction import REDACTION_RULESET_VERSION


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


def _searchable(payload: str) -> str:
    """The document in BOTH forms — see this module's docstring.

    The serialised text is what a reader greps; the parsed strings are what the
    reader's eye sees rendered. An identifier that survives in either encoding
    is a leak, and searching only one of them is how a control goes blind.
    """
    return "\n".join([payload, *_strings(json.loads(payload))])


def _bundle(tmp_path, **probe_kwargs) -> tuple[str, object, object]:
    log_path = str(tmp_path / "audit-log.jsonl")
    write_hostile_log(log_path)
    broker, sink, names = bundle_broker(log_path)
    probes = fixture_probes(aedt=root_names("2026.1"), **probe_kwargs)
    return build_diagnostics_bundle(probes, names, broker), broker, sink


# --- the document ------------------------------------------------------------


def test_the_bundle_is_readable_indented_json(tmp_path) -> None:
    """Inspectable before sending is the whole shape decision — a user who
    cannot read the file has to trust it instead."""
    payload, _, _ = _bundle(tmp_path)
    assert payload.endswith("\n")
    assert "\n  " in payload
    json.loads(payload)


def test_the_bundle_carries_both_version_fields(tmp_path) -> None:
    """Two versions because they change for unrelated reasons: the format is a
    parsing concern, the ruleset is a sensitivity one."""
    payload, _, _ = _bundle(tmp_path)
    document = json.loads(payload)
    assert document["bundle_format_version"] == BUNDLE_FORMAT_VERSION
    assert document["redaction_ruleset_version"] == REDACTION_RULESET_VERSION


def test_the_bundle_carries_the_preflight_report_and_the_history(tmp_path) -> None:
    payload, _, _ = _bundle(tmp_path)
    document = json.loads(payload)
    assert document["preflight"]["overall"] == "ok"
    assert document["preflight"]["support_matrix_ref"] == "docs/support-matrix.md"
    assert document["audit"]["record_count"] == 3
    assert len(document["audit"]["records"]) == 3
    assert document["audit"]["torn_tail"] is False
    assert document["audit"]["corrupt_lines"] == []


def test_the_bundle_carries_no_wall_clock_stamp(tmp_path) -> None:
    """Timestamp-free like W-5, W-6 and W-7, so two bundles of identical machine
    state are byte-identical and can be diffed."""
    payload, _, _ = _bundle(tmp_path)
    assert "generated_at" not in json.loads(payload)


# --- the four honesty sections ----------------------------------------------


@pytest.mark.parametrize(
    "section",
    [
        "what_was_removed",
        "what_was_kept",
        "what_this_does_not_guarantee",
        "what_was_never_collected",
    ],
)
def test_every_honesty_section_is_present_and_non_empty(
    tmp_path, section: str
) -> None:
    document = json.loads(_bundle(tmp_path)[0])
    assert document[section]
    assert all(isinstance(line, str) for line in document[section])


def test_the_residual_names_every_way_the_bundle_still_identifies(
    tmp_path,
) -> None:
    """THE LOAD-BEARING SECTION. It sits where the person deciding whether to
    send will read it, and it must name all five residuals together — any one
    of them omitted turns the section into reassurance."""
    text = " ".join(json.loads(_bundle(tmp_path)[0])["what_this_does_not_guarantee"])
    assert "working hours" in text and "time zone" in text
    assert "workflow fingerprint" in text
    assert "correlatable" in text
    assert "all true" in text and "multi-second durations" in text
    assert "is not 'this file is anonymous'" in text
    assert "READ THIS BEFORE SENDING" in text


def test_never_collected_names_the_two_absences_that_look_like_omissions(
    tmp_path,
) -> None:
    """Both would otherwise read as things the redactor removed, which would
    overstate what redaction achieved."""
    text = " ".join(json.loads(_bundle(tmp_path)[0])["what_was_never_collected"])
    assert "Stack traces" in text and "records none" in text
    assert "appended after the read returns" in text
    assert "NAMES only" in text


def test_what_was_kept_explains_each_survivor(tmp_path) -> None:
    text = " ".join(json.loads(_bundle(tmp_path)[0])["what_was_kept"])
    for survivor in (
        "timestamp",
        "tool_name",
        "risk_tier",
        "outcome",
        "duration",
        "session_degraded",
        "selection_present",
        "arguments_dropped",
    ):
        assert survivor in text


# --- the negative control, at the bundle level -------------------------------


@pytest.mark.parametrize("identifier", PLANTED_IDENTIFIERS)
def test_no_planted_identifier_reaches_the_bundle(tmp_path, identifier: str) -> None:
    assert identifier not in _searchable(_bundle(tmp_path)[0])


def test_no_secret_environment_value_reaches_the_bundle(tmp_path) -> None:
    searchable = _searchable(_bundle(tmp_path)[0])
    for name, value in SECRET_ENVIRONMENT.items():
        assert name not in searchable
        assert value not in searchable


def test_the_search_form_can_see_a_backslash_path(tmp_path) -> None:
    """The lesson from 3a, applied at this level and pinned.

    ``json.dumps`` escapes ``\\`` to ``\\\\``, so the planted path cannot appear
    in the serialised text in its planted spelling. If ``_searchable`` were
    narrowed to the serialised form alone, every path assertion above would
    pass no matter what the bundle contained.
    """
    payload, _, _ = _bundle(tmp_path)
    planted = r"D:\clients\northwind-defence\kestrel\kestrel-radar-v7.aedt"
    injected = json.dumps({"leak": planted})
    assert planted not in injected
    assert planted in _searchable(injected)


def test_the_search_form_can_see_an_escaped_character(tmp_path) -> None:
    """A newline is ``\\n`` in serialised form and a real newline in the parsed
    strings; both encodings are searched."""
    injected = json.dumps({"leak": "kestrel\nradar"})
    assert "kestrel\nradar" not in injected
    assert "kestrel\nradar" in _searchable(injected)


def test_neutering_the_redaction_leaks_into_the_bundle(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control proper: with the redactor neutered, the identifiers appear IN
    THE BUNDLE. Without this, every assertion above is equally satisfied by a
    log that never carried them.

    Neutered, not inverted (ADR-26 decision 16).
    """
    monkeypatch.setattr(
        bundle_module, "redact_audit_records", lambda records, names: [
            json.loads(record.model_dump_json()) for record in records
        ]
    )
    searchable = _searchable(_bundle(tmp_path)[0])
    for identifier in PLANTED_IDENTIFIERS:
        assert identifier in searchable, identifier


# --- determinism -------------------------------------------------------------


def test_two_builds_are_byte_identical(tmp_path) -> None:
    """ONE log, built twice — and the distinction matters.

    Writing the fixture log twice would append to it, because the audit log is
    append-only by construction, and the second bundle would honestly report six
    records rather than three. That is the log behaving correctly, not the
    bundle behaving non-deterministically, and the first draft of this test
    conflated them. Determinism here means: identical input, identical bytes.
    """
    log_path = str(tmp_path / "audit-log.jsonl")
    write_hostile_log(log_path)
    broker, _, names = bundle_broker(log_path)
    probes = fixture_probes(aedt=root_names("2026.1"))

    first = build_diagnostics_bundle(probes, names, broker)
    second = build_diagnostics_bundle(probes, names, broker)
    assert first == second
    assert hashlib.sha256(first.encode()).hexdigest() == (
        hashlib.sha256(second.encode()).hexdigest()
    )


# --- the write path ----------------------------------------------------------


def test_a_written_bundle_returns_the_brokers_own_result(tmp_path) -> None:
    """Passed through VERBATIM, so the no-silent-overwrite guarantee stays the
    broker's single claim rather than being restated here."""
    log_path = str(tmp_path / "audit-log.jsonl")
    write_hostile_log(log_path)
    broker, _, names = bundle_broker(log_path)
    target = str(tmp_path / "bundle.json")

    result = export_diagnostics_bundle(
        target, fixture_probes(aedt=root_names("2026.1")), names, broker
    )
    assert isinstance(result, ExportWritten)
    assert result.path == target
    assert result.bytes_written > 0
    with open(target, encoding="utf-8") as handle:
        json.loads(handle.read())


def test_an_existing_path_is_refused_without_overwrite(tmp_path) -> None:
    log_path = str(tmp_path / "audit-log.jsonl")
    write_hostile_log(log_path)
    broker, _, names = bundle_broker(log_path)
    target = str(tmp_path / "bundle.json")
    probes = fixture_probes(aedt=root_names("2026.1"))

    export_diagnostics_bundle(target, probes, names, broker)
    again = export_diagnostics_bundle(target, probes, names, broker)
    assert isinstance(again, ExportRefused)
    assert again.outcome == "refused_existing_path"


def test_overwrite_replaces_the_file(tmp_path) -> None:
    log_path = str(tmp_path / "audit-log.jsonl")
    write_hostile_log(log_path)
    broker, _, names = bundle_broker(log_path)
    target = str(tmp_path / "bundle.json")
    probes = fixture_probes(aedt=root_names("2026.1"))

    export_diagnostics_bundle(target, probes, names, broker)
    again = export_diagnostics_bundle(target, probes, names, broker, overwrite=True)
    assert isinstance(again, ExportWritten)


def test_a_broker_file_error_becomes_export_failed_carrying_the_orphan(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented mislabel, and the field it exists to protect.

    ``BrokerFileError`` carries no discriminator between "refused before the
    disk was touched" and "broke mid-write", so the two cannot be told apart
    here. ``ExportFailed`` is the safer wrong answer: reporting ``ExportRefused``
    when a temp file WAS left behind would silently defeat the one field that
    stops a stray file being invisible.
    """
    log_path = str(tmp_path / "audit-log.jsonl")
    write_hostile_log(log_path)
    broker, _, names = bundle_broker(log_path)

    def raising_write(path, payload, *, overwrite=False):
        raise BrokerFileError(
            path, "the device is full", orphaned_temp=path + ".tmp1234"
        )

    monkeypatch.setattr(broker, "write_export", raising_write)
    result = export_diagnostics_bundle(
        str(tmp_path / "bundle.json"),
        fixture_probes(aedt=root_names("2026.1")),
        names,
        broker,
    )
    assert isinstance(result, ExportFailed)
    assert result.outcome == "write_failed"
    assert result.reason == "the device is full"
    assert result.orphaned_temp.endswith(".tmp1234")
    assert "A temporary file remains at" in result.template_text


def test_a_path_refusal_also_maps_to_export_failed_with_no_orphan(
    tmp_path,
) -> None:
    """The imprecise half of the mislabel, asserted so it is visible rather than
    discovered: a relative path is refused before anything is touched, and is
    still reported as a failure because the exception cannot say so."""
    log_path = str(tmp_path / "audit-log.jsonl")
    write_hostile_log(log_path)
    broker, _, names = bundle_broker(log_path)

    result = export_diagnostics_bundle(
        "relative/bundle.json",
        fixture_probes(aedt=root_names("2026.1")),
        names,
        broker,
    )
    assert isinstance(result, ExportFailed)
    assert result.orphaned_temp is None
    assert "not absolute" in result.reason


# --- the dispatch boundary ---------------------------------------------------


def test_a_dispatch_that_returns_no_log_refuses_to_build(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bundle with a silently empty history would read as "this machine has
    done nothing", which is a different and false claim."""
    log_path = str(tmp_path / "audit-log.jsonl")
    write_hostile_log(log_path)
    broker, _, names = bundle_broker(log_path)
    monkeypatch.setattr(broker, "dispatch", lambda *args, **kwargs: object())

    with pytest.raises(DiagnosticsBundleError) as caught:
        build_diagnostics_bundle(
            fixture_probes(aedt=root_names("2026.1")), names, broker
        )
    assert "call history could not be read" in str(caught.value)


# --- the audit side effect ---------------------------------------------------


def test_building_the_bundle_appends_exactly_the_audit_read(tmp_path) -> None:
    """Reading the log necessarily writes one — there is no non-dispatchable
    accessor and the broker's control-plane rule forbids adding one, because an
    accessor may do no disk work.

    Preflight itself still dispatches nothing, so the single record is the
    ``get_audit_log`` read and nothing else.
    """
    log_path = str(tmp_path / "audit-log.jsonl")
    write_hostile_log(log_path)
    broker, sink, names = bundle_broker(log_path)

    build_diagnostics_bundle(fixture_probes(aedt=root_names("2026.1")), names, broker)
    assert [record.tool_name for record in sink.records] == ["get_audit_log"]


def test_the_bundle_does_not_contain_the_record_of_its_own_read(
    tmp_path,
) -> None:
    """The record is appended AFTER the handler returns, so it is never in the
    log the read returned. Stated in the bundle's own text and asserted here."""
    payload, _, sink = _bundle(tmp_path)
    document = json.loads(payload)
    assert document["audit"]["record_count"] == 3
    assert "get_audit_log" not in [
        record["tool_name"] for record in document["audit"]["records"]
    ]
    assert len(sink.records) == 1
