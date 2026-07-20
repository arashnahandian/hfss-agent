"""The write primitives and the guarded export primitive (ADR-8; plan §6).

Includes the runbook's named done criterion: writing to an existing path
without ``overwrite=true`` is refused AND the target's bytes are unchanged —
asserted on the bytes, not just the returned value.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from broker_helpers import make_broker

from hfss_agent.broker import Broker
from hfss_agent.broker.files import (
    BrokerFileError,
    atomic_replace_write,
    exclusive_create_write,
)
from hfss_agent.contract.tool_io import ExportRefused, ExportWritten


def _broker() -> Broker:
    broker, _sink = make_broker(())
    return broker


# --- the runbook's named done criterion --------------------------------------


def test_existing_path_without_overwrite_refused_and_bytes_unchanged(
    tmp_path: Path,
) -> None:
    target = tmp_path / "out.s2p"
    target.write_bytes(b"ORIGINAL")
    result = _broker().write_export(str(target), "replacement text")

    assert isinstance(result, ExportRefused)
    assert result.outcome == "refused_existing_path"
    assert "No file was modified" in result.template_text
    assert target.read_bytes() == b"ORIGINAL"  # bytes compared, not just typed


# --- write and overwrite behaviour -------------------------------------------


def test_new_path_written_with_exact_bytes(tmp_path: Path) -> None:
    target = tmp_path / "out.s2p"
    result = _broker().write_export(str(target), "line1\nline2\n")
    assert isinstance(result, ExportWritten)
    data = target.read_bytes()
    assert data == b"line1\nline2\n"
    assert result.bytes_written == len(data)


def test_overwrite_true_replaces_the_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "out.csv"
    target.write_bytes(b"OLD")
    result = _broker().write_export(str(target), "NEW", overwrite=True)
    assert isinstance(result, ExportWritten)
    assert target.read_bytes() == b"NEW"


def test_failed_overwrite_leaves_prior_intact_and_names_the_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Force the replace step to fail deterministically on both CI legs: the
    # temp is then fully written but never promoted, so the user's prior file
    # must be untouched and the orphan must be named, in the user's own dir.
    target = tmp_path / "out.s2p"
    target.write_bytes(b"PRIOR")

    def refuse_replace(src: object, dst: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", refuse_replace)
    with pytest.raises(BrokerFileError) as excinfo:
        _broker().write_export(str(target), "NEW", overwrite=True)

    error = excinfo.value
    assert target.read_bytes() == b"PRIOR"  # never torn
    assert error.orphaned_temp is not None
    orphan = Path(error.orphaned_temp)
    assert orphan.exists()  # left in place — nothing is ever deleted
    assert orphan.read_bytes() == b"NEW"
    assert error.orphaned_temp in str(error)  # the error NAMES the orphan
    assert orphan.parent == tmp_path  # in the USER'S directory (ADR-19)


def test_non_oserror_failure_still_names_the_orphan(tmp_path: Path) -> None:
    # A lone surrogate cannot encode to UTF-8, so handle.write raises
    # UnicodeEncodeError — a ValueError, NOT an OSError. Reachable in
    # production because the intent envelope carries untrusted HFSS-sourced
    # chain names (ADR-9). Every failure after the temp exists must still
    # name the orphan and leave the prior target untouched (ADR-19).
    target = tmp_path / "out.s2p"
    target.write_bytes(b"PRIOR")

    with pytest.raises(BrokerFileError) as excinfo:
        atomic_replace_write(str(target), "bad \ud800 payload")

    error = excinfo.value
    assert target.read_bytes() == b"PRIOR"  # never torn
    assert error.orphaned_temp is not None
    assert Path(error.orphaned_temp).exists()  # named AND actually there
    assert error.orphaned_temp in str(error)
    assert "UnicodeEncodeError" in str(error)


def test_binary_payload_written_exactly(tmp_path: Path) -> None:
    target = tmp_path / "bundle.bin"
    result = _broker().write_export(str(target), b"\x00\x01\x02")
    assert isinstance(result, ExportWritten)
    assert target.read_bytes() == b"\x00\x01\x02"
    assert result.bytes_written == 3


def test_bytes_written_counts_utf8_bytes_not_characters(tmp_path: Path) -> None:
    target = tmp_path / "out.csv"
    result = _broker().write_export(str(target), "µ\n")
    assert isinstance(result, ExportWritten)
    assert result.bytes_written == len("µ\n".encode())
    assert result.bytes_written == target.stat().st_size


# --- validation is consulted before any write --------------------------------


def test_write_export_refuses_reserved_name_before_touching_disk(
    tmp_path: Path,
) -> None:
    with pytest.raises(BrokerFileError, match="reserved device name"):
        _broker().write_export(str(tmp_path / "CON.s2p"), "data")


def test_write_export_refuses_missing_parent_and_creates_nothing(
    tmp_path: Path,
) -> None:
    with pytest.raises(BrokerFileError, match="parent directory"):
        _broker().write_export(str(tmp_path / "nope" / "x.s2p"), "data")
    assert not (tmp_path / "nope").exists()


# --- byte determinism (plan §6d) ---------------------------------------------


def test_no_carriage_returns_in_written_text(tmp_path: Path) -> None:
    target = tmp_path / "out.csv"
    _broker().write_export(str(target), "a\nb\nc\n")
    assert b"\r" not in target.read_bytes()


# --- primitives directly ------------------------------------------------------


def test_exclusive_create_raises_fileexists_and_preserves_content(
    tmp_path: Path,
) -> None:
    target = tmp_path / "x.txt"
    assert exclusive_create_write(str(target), "one") == 3
    with pytest.raises(FileExistsError):
        exclusive_create_write(str(target), "two")
    assert target.read_bytes() == b"one"


def test_atomic_replace_write_creates_when_target_missing(tmp_path: Path) -> None:
    target = tmp_path / "x.json"
    atomic_replace_write(str(target), "{}\n")
    assert target.read_bytes() == b"{}\n"
