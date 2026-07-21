"""Design-intent persistence and the three intent capabilities, driven
through the Part 2 dispatch pipeline (plan §6; decisions 3-4): set/get/clear
round-trips, the tombstone clear, the set-time selection chain, and loud
typed errors for corruption."""

from __future__ import annotations

from pathlib import Path

import pytest
from broker_helpers import DEFAULT_PID, intent_broker
from pydantic import ValidationError

from hfss_agent.broker.files import BrokerFileError, IntentStore
from hfss_agent.contract.tool_io import DesignIntentState

_SET_ARGS: dict[str, object] = {
    "target_frequency_hz": 2.4e9,
    "threshold_type": "s11",
    "threshold_value": -10.0,
}


def test_set_get_clear_roundtrip_through_dispatch(tmp_path: Path) -> None:
    broker, sink, _store, _session = intent_broker(tmp_path)

    set_state = broker.dispatch("set_design_intent", dict(_SET_ARGS))
    assert isinstance(set_state, DesignIntentState)
    assert set_state.intent is not None
    assert set_state.intent.target_frequency_hz == 2.4e9

    got = broker.dispatch("get_design_intent")
    assert isinstance(got, DesignIntentState)
    assert got.intent == set_state.intent

    cleared = broker.dispatch("clear_design_intent")
    assert isinstance(cleared, DesignIntentState)
    assert cleared.intent is None

    after = broker.dispatch("get_design_intent")
    assert isinstance(after, DesignIntentState)
    assert after.intent is None

    # Every call went through the Part 2 pipeline and was audited.
    assert [record.tool_name for record in sink.records] == [
        "set_design_intent",
        "get_design_intent",
        "clear_design_intent",
        "get_design_intent",
    ]
    assert all(
        record.outcome == "ok" and record.risk_tier == "safe"
        for record in sink.records
    )


def test_get_before_any_set_is_none_not_an_error(tmp_path: Path) -> None:
    broker, _sink, _store, _session = intent_broker(tmp_path)
    state = broker.dispatch("get_design_intent")
    assert isinstance(state, DesignIntentState)
    assert state.intent is None
    assert state.template_text == "No design intent is set."


def test_clear_is_a_tombstone_nothing_deleted(tmp_path: Path) -> None:
    broker, _sink, store, _session = intent_broker(tmp_path)
    broker.dispatch("set_design_intent", dict(_SET_ARGS))
    assert (tmp_path / "intent.json").exists()

    broker.dispatch("clear_design_intent")
    # The file still exists: the cleared state was written in place.
    assert (tmp_path / "intent.json").exists()
    envelope = store.read()
    assert envelope is not None
    assert envelope.intent is None


def test_envelope_carries_set_time_chain_and_get_renders_it(
    tmp_path: Path,
) -> None:
    broker, _sink, store, _session = intent_broker(tmp_path)
    broker.dispatch("attach", {"process_id": DEFAULT_PID})
    broker.dispatch("select", {"stage": "project", "choice": "patch_antenna"})
    broker.dispatch("set_design_intent", dict(_SET_ARGS))
    # The selection moves ON after the set — the envelope must not follow it.
    broker.dispatch("select", {"stage": "design", "choice": "HFSSDesign1"})

    envelope = store.read()
    assert envelope is not None
    assert envelope.selection_at_write.project is not None
    assert envelope.selection_at_write.project.name == "patch_antenna"
    assert envelope.selection_at_write.design is None  # set-time, not current

    got = broker.dispatch("get_design_intent")
    assert isinstance(got, DesignIntentState)
    assert 'project="patch_antenna"' in got.template_text
    assert "SET while the selection was" in got.template_text
    assert "current selection differs" in got.template_text


def test_set_with_detached_session_records_the_empty_chain(
    tmp_path: Path,
) -> None:
    broker, _sink, store, _session = intent_broker(tmp_path)
    state = broker.dispatch("set_design_intent", dict(_SET_ARGS))

    envelope = store.read()
    assert envelope is not None
    dumped = envelope.selection_at_write.model_dump()
    assert all(value is None for value in dumped.values())
    assert isinstance(state, DesignIntentState)
    assert "no selection (no session attached)" in state.template_text


def test_set_and_get_templates_render_the_frequency_with_its_unit(
    tmp_path: Path,
) -> None:
    # Gap 6 (amended): the schema now pins the unit in the field name, so the
    # template renders name + unit rather than disclaiming an assumption.
    broker, _sink, _store, _session = intent_broker(tmp_path)
    set_state = broker.dispatch("set_design_intent", dict(_SET_ARGS))
    got = broker.dispatch("get_design_intent")
    for state in (set_state, got):
        assert isinstance(state, DesignIntentState)
        assert "target_frequency_hz=2400000000.0 Hz" in state.template_text
        assert "does not pin a unit" not in state.template_text


def test_corrupt_intent_file_is_loud_typed_error_and_audited(
    tmp_path: Path,
) -> None:
    broker, sink, _store, _session = intent_broker(tmp_path)
    (tmp_path / "intent.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(BrokerFileError, match="intent file"):
        broker.dispatch("get_design_intent")
    # Surfaced AND audited typed_error via the dispatch exception path.
    assert sink.records[-1].tool_name == "get_design_intent"
    assert sink.records[-1].outcome == "typed_error"


def test_unrecognized_envelope_marker_is_a_typed_error(tmp_path: Path) -> None:
    (tmp_path / "intent.json").write_text(
        '{"format": "other/9", "intent": null, "selection_at_write": {}}',
        encoding="utf-8",
    )
    store = IntentStore(str(tmp_path / "intent.json"))
    with pytest.raises(BrokerFileError, match="envelope"):
        store.read()


def test_invalid_set_arguments_fail_loudly_and_audit_typed_error(
    tmp_path: Path,
) -> None:
    broker, sink, _store, _session = intent_broker(tmp_path)
    bad = {
        "target_frequency_hz": 1e9,
        "threshold_type": "bogus",
        "threshold_value": -1.0,
    }
    with pytest.raises(ValidationError):
        broker.dispatch("set_design_intent", bad)
    assert sink.records[-1].outcome == "typed_error"
    # Nothing was persisted by the failed set.
    assert not (tmp_path / "intent.json").exists()


def test_intent_file_bytes_have_no_carriage_returns(tmp_path: Path) -> None:
    broker, _sink, _store, _session = intent_broker(tmp_path)
    broker.dispatch("set_design_intent", dict(_SET_ARGS))
    assert b"\r" not in (tmp_path / "intent.json").read_bytes()
