"""Export-path validation (plan §6c): every refusal class, each with its
specific typed reason. String-level checks use ``tmp_path``-anchored absolute
paths so the same assertion holds on both CI legs."""

from __future__ import annotations

from pathlib import Path

import pytest

from hfss_agent.broker.files import BrokerFileError, validate_export_path


def test_relative_path_refused() -> None:
    with pytest.raises(BrokerFileError, match="not absolute"):
        validate_export_path("relative/out.s2p")


def test_windows_drive_relative_form_refused() -> None:
    # "C:out.s2p" is drive-relative, not absolute — os.path.isabs rejects it
    # on Windows; on POSIX it is a plain relative path. Refused either way.
    with pytest.raises(BrokerFileError, match="not absolute"):
        validate_export_path("C:out.s2p")


@pytest.mark.parametrize(
    "unc", [r"\\server\share\out.s2p", "//server/share/out.s2p"]
)
def test_unc_paths_refused_in_both_slash_spellings(unc: str) -> None:
    with pytest.raises(BrokerFileError, match="UNC"):
        validate_export_path(unc)


@pytest.mark.parametrize(
    "name", ["con.txt", "COM7.s2p", "NUL.", "prn", "lpt9.csv", "AUX.tar.gz"]
)
def test_reserved_device_names_refused_with_and_without_extension(
    tmp_path: Path, name: str
) -> None:
    with pytest.raises(BrokerFileError, match="reserved device name"):
        validate_export_path(str(tmp_path / name))


def test_reserved_names_checked_on_directory_components_too(
    tmp_path: Path,
) -> None:
    with pytest.raises(BrokerFileError, match="reserved device name"):
        validate_export_path(str(tmp_path / "aux" / "out.s2p"))


@pytest.mark.parametrize("name", ["out.s2p.", "out.s2p "])
def test_trailing_dot_or_space_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(BrokerFileError, match="ends with a dot or space"):
        validate_export_path(str(tmp_path) + "/" + name)


def test_trailing_space_on_a_directory_component_refused(tmp_path: Path) -> None:
    bad = str(tmp_path) + "/exports /out.s2p"
    with pytest.raises(BrokerFileError, match="ends with a dot or space"):
        validate_export_path(bad)


def test_missing_parent_refused_named_and_not_created(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "out.s2p"
    with pytest.raises(BrokerFileError, match="parent directory"):
        validate_export_path(str(target))
    # The refusal must not have silently created the tree.
    assert not (tmp_path / "missing").exists()


def test_valid_absolute_path_passes(tmp_path: Path) -> None:
    validate_export_path(str(tmp_path / "ok.s2p"))  # no raise is the assertion


def test_case_insensitive_reserved_check(tmp_path: Path) -> None:
    with pytest.raises(BrokerFileError, match="reserved device name"):
        validate_export_path(str(tmp_path / "CoM3.s2p"))
