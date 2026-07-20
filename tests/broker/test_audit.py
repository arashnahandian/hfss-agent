"""The real audit writer and reader (Part 4): append-only behaviour,
round-trip fidelity, the corrected two-arm malformed-line policy (ADR-19
fixes 1-2: newline guard + non-fatal interior arm), range filtering, the
real-file sink-failure re-verification (plan §13), and the end-to-end
dispatch -> get_audit_log flow."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from broker_helpers import DEFAULT_PID, HandlerSpy, audit_broker, spec_for

from hfss_agent.adapter.fake import FakeAdapter
from hfss_agent.broker import (
    AuditFailure,
    AuditLogWriter,
    Broker,
    CapabilityRegistry,
    RefuseAllConfirmer,
)
from hfss_agent.broker.audit import read_audit_records
from hfss_agent.contract import AuditRecord
from hfss_agent.contract.tool_io import AuditLog, AuditLogRange
from hfss_agent.session import Session


def _record(tool: str = "attach", *, hour: int = 12) -> AuditRecord:
    return AuditRecord(
        timestamp=datetime(2026, 7, 20, hour, 0, 0, tzinfo=timezone.utc),
        tool_name=tool,
        sanitized_arguments={"stage": "project", "nested": {"n": 1}},
        selection_state={"process_id": None},
        risk_tier="safe",
        outcome="ok",
        duration=0.01,
        snapshot_id=None,
    )


def _log(tmp_path: Path) -> str:
    return str(tmp_path / "audit-log.jsonl")


# --- writer: append-only, round-trip, byte determinism ------------------------


def test_append_only_first_line_survives_byte_for_byte(tmp_path: Path) -> None:
    writer = AuditLogWriter(_log(tmp_path))
    writer.append(_record("attach"))
    before = (tmp_path / "audit-log.jsonl").read_bytes()
    writer.append(_record("select"))
    after = (tmp_path / "audit-log.jsonl").read_bytes()
    # Not just "two lines exist": the earlier bytes are entirely untouched.
    assert after.startswith(before)
    assert after.splitlines()[0] == before.splitlines()[0]
    assert len(after.splitlines()) == 2


def test_roundtrip_record_to_jsonl_to_record_field_for_field(
    tmp_path: Path,
) -> None:
    writer = AuditLogWriter(_log(tmp_path))
    record = _record("select")
    writer.append(record)
    result = read_audit_records(_log(tmp_path))
    assert result.torn_tail is False
    # Pydantic equality is field-for-field, including the aware timestamp.
    assert list(result.records) == [record]


def test_log_bytes_have_no_carriage_returns(tmp_path: Path) -> None:
    writer = AuditLogWriter(_log(tmp_path))
    writer.append(_record("attach"))
    writer.append(_record("select"))
    assert b"\r" not in (tmp_path / "audit-log.jsonl").read_bytes()


# --- reader: missing file, torn tail, corruption ------------------------------


def test_missing_log_file_is_an_empty_result_not_an_error(
    tmp_path: Path,
) -> None:
    result = read_audit_records(_log(tmp_path))
    assert result.records == ()
    assert result.torn_tail is False


def test_torn_final_line_survivors_returned_and_flagged(tmp_path: Path) -> None:
    writer = AuditLogWriter(_log(tmp_path))
    writer.append(_record("attach"))
    writer.append(_record("select"))
    # A crash mid-append leaves a partial final line with no trailing newline.
    with open(_log(tmp_path), "a", encoding="utf-8", newline="\n") as handle:
        handle.write('{"timestamp": "2026-07-')
    result = read_audit_records(_log(tmp_path))
    assert [record.tool_name for record in result.records] == ["attach", "select"]
    assert result.torn_tail is True
    assert result.corrupt_lines == ()


def test_malformed_interior_line_returns_survivors_with_notice(
    tmp_path: Path,
) -> None:
    # ADR-19 fix 2: loud but NON-FATAL — the corrupt line is named, never
    # silently skipped, and the surviving records are still returned.
    line = _record("attach").model_dump_json()
    (tmp_path / "audit-log.jsonl").write_text(
        line + "\nGARBAGE-NOT-JSON\n" + line + "\n", encoding="utf-8"
    )
    result = read_audit_records(_log(tmp_path))
    assert [record.tool_name for record in result.records] == ["attach", "attach"]
    assert result.corrupt_lines == (2,)
    assert result.torn_tail is False


def test_crash_then_continue_returns_all_wellformed_records(
    tmp_path: Path,
) -> None:
    # A torn tail followed by TWO more appends: every well-formed record
    # survives, the stub is named as a corrupt interior line, nothing raises.
    writer = AuditLogWriter(_log(tmp_path))
    writer.append(_record("attach", hour=10))
    with open(_log(tmp_path), "a", encoding="utf-8", newline="\n") as handle:
        handle.write('{"partial')
    writer.append(_record("select", hour=11))
    writer.append(_record("get_session_status", hour=12))

    result = read_audit_records(_log(tmp_path))
    assert [record.tool_name for record in result.records] == [
        "attach",
        "select",
        "get_session_status",
    ]
    assert result.corrupt_lines == (2,)  # the stub, kept on its own line
    assert result.torn_tail is False


def test_newline_guard_lands_next_append_on_its_own_line(tmp_path: Path) -> None:
    # ADR-19 fix 1: the record appended right after a torn tail is not merged
    # into the stub and not lost.
    writer = AuditLogWriter(_log(tmp_path))
    writer.append(_record("attach"))
    with open(_log(tmp_path), "a", encoding="utf-8", newline="\n") as handle:
        handle.write('{"partial')
    writer.append(_record("select"))

    raw_lines = (tmp_path / "audit-log.jsonl").read_bytes().splitlines()
    assert len(raw_lines) == 3
    assert raw_lines[1] == b'{"partial'  # the stub kept its own line
    result = read_audit_records(_log(tmp_path))
    assert [record.tool_name for record in result.records] == ["attach", "select"]


def test_guard_adds_no_blank_lines_to_a_wellformed_log(tmp_path: Path) -> None:
    writer = AuditLogWriter(_log(tmp_path))
    for tool in ("attach", "select", "get_session_status"):
        writer.append(_record(tool))
    data = (tmp_path / "audit-log.jsonl").read_bytes()
    assert data.count(b"\n") == 3  # exactly one newline per record
    assert b"\n\n" not in data  # no stray blanks accumulate over appends


# --- range filtering ----------------------------------------------------------


def _three_hour_log(tmp_path: Path) -> str:
    writer = AuditLogWriter(_log(tmp_path))
    for hour, tool in ((10, "attach"), (11, "select"), (12, "get_session_status")):
        writer.append(_record(tool, hour=hour))
    return _log(tmp_path)


def _aware(hour: int) -> datetime:
    return datetime(2026, 7, 20, hour, 0, 0, tzinfo=timezone.utc)


def test_range_start_and_end_bound_inclusively(tmp_path: Path) -> None:
    path = _three_hour_log(tmp_path)

    from_11 = read_audit_records(path, AuditLogRange(start=_aware(11)))
    assert [r.tool_name for r in from_11.records] == ["select", "get_session_status"]

    until_11 = read_audit_records(path, AuditLogRange(end=_aware(11)))
    assert [r.tool_name for r in until_11.records] == ["attach", "select"]

    window = read_audit_records(
        path, AuditLogRange(start=_aware(11), end=_aware(11))
    )
    assert [r.tool_name for r in window.records] == ["select"]


def test_limit_caps_the_most_recent_records(tmp_path: Path) -> None:
    path = _three_hour_log(tmp_path)
    result = read_audit_records(path, AuditLogRange(limit=2))
    assert [r.tool_name for r in result.records] == ["select", "get_session_status"]
    assert read_audit_records(path, AuditLogRange(limit=0)).records == ()


def test_naive_range_datetime_is_read_as_utc(tmp_path: Path) -> None:
    # Contract gap 5: records are written aware-UTC; a naive bound is read as
    # UTC, so it must select exactly what the equivalent aware bound selects.
    path = _three_hour_log(tmp_path)
    naive = datetime(2026, 7, 20, 11, 0, 0)
    aware = datetime(2026, 7, 20, 11, 0, 0, tzinfo=timezone.utc)
    naive_result = read_audit_records(path, AuditLogRange(start=naive))
    aware_result = read_audit_records(path, AuditLogRange(start=aware))
    assert naive_result.records == aware_result.records


# --- the real-file sink-failure re-verification (plan §13) --------------------


def test_sink_failure_against_a_real_unwritable_path(tmp_path: Path) -> None:
    # The audit-log path is occupied by a DIRECTORY, so the real writer's
    # append fails on both OSes — re-verifying Part 2's fail-closed dispatch
    # path against a real file failure, not only a raising double.
    (tmp_path / "audit-log.jsonl").mkdir()
    spy = HandlerSpy(result="payload")
    broker = Broker(
        session=Session(FakeAdapter()),
        registry=CapabilityRegistry((spec_for(spy),)),
        confirmer=RefuseAllConfirmer(),
        data_dir=str(tmp_path),
    )
    result = broker.dispatch("synthetic")

    assert spy.calls == [{}]  # the operation RAN
    assert isinstance(result, AuditFailure)
    assert result.unaudited_outcome == "ok"
    assert "BrokerFileError" in result.detail
    assert "could not be written" in result.notice


# --- end-to-end through dispatch ----------------------------------------------


def test_end_to_end_dispatch_then_get_audit_log_in_order(tmp_path: Path) -> None:
    broker, _log_path, _session = audit_broker(tmp_path)
    broker.dispatch("attach", {"process_id": DEFAULT_PID})
    broker.dispatch("select", {"stage": "project", "choice": "patch_antenna"})

    result = broker.dispatch("get_audit_log")
    assert isinstance(result, AuditLog)
    assert [record.tool_name for record in result.records] == ["attach", "select"]
    assert all(record.risk_tier == "safe" for record in result.records)
    assert "2 record(s)" in result.template_text

    # Self-referential wrinkle: the get_audit_log call above appended its own
    # record AFTER reading, so it appears in the NEXT read, not its own.
    second = broker.dispatch("get_audit_log")
    assert isinstance(second, AuditLog)
    assert [record.tool_name for record in second.records] == [
        "attach",
        "select",
        "get_audit_log",
    ]


def test_get_audit_log_range_through_dispatch(tmp_path: Path) -> None:
    broker, _log_path, _session = audit_broker(tmp_path)
    broker.dispatch("attach", {"process_id": DEFAULT_PID})
    broker.dispatch("get_session_status")

    result = broker.dispatch("get_audit_log", {"range": {"limit": 1}})
    assert isinstance(result, AuditLog)
    assert [record.tool_name for record in result.records] == ["get_session_status"]


def test_get_audit_log_on_fresh_log_is_empty(tmp_path: Path) -> None:
    broker, _log_path, _session = audit_broker(tmp_path)
    result = broker.dispatch("get_audit_log")
    assert isinstance(result, AuditLog)
    assert result.records == []
    assert "0 record(s)" in result.template_text


def test_crash_then_continue_through_dispatch_never_bricks_the_log(
    tmp_path: Path,
) -> None:
    broker, log_path, _session = audit_broker(tmp_path)
    broker.dispatch("attach", {"process_id": DEFAULT_PID})
    with open(log_path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write('{"partial')

    # First read after the crash: the stub is still the FINAL line, so the
    # benign torn-tail wording applies.
    first = broker.dispatch("get_audit_log")
    assert isinstance(first, AuditLog)
    assert [record.tool_name for record in first.records] == ["attach"]
    assert "mid-write" in first.template_text

    # That read's own audit record landed on its OWN line (fix 1), so it is
    # neither merged nor lost; the stub is now INTERIOR, so the alarming
    # wording applies — and the read still returns every well-formed record
    # instead of raising (fix 2).
    second = broker.dispatch("get_audit_log")
    assert isinstance(second, AuditLog)
    assert [record.tool_name for record in second.records] == [
        "attach",
        "get_audit_log",
    ]
    assert "line(s) 2" in second.template_text
    assert "INCOMPLETE" in second.template_text

    # And it keeps working — one crash never permanently bricks the log.
    third = broker.dispatch("get_audit_log")
    assert isinstance(third, AuditLog)
    assert [record.tool_name for record in third.records] == [
        "attach",
        "get_audit_log",
        "get_audit_log",
    ]
