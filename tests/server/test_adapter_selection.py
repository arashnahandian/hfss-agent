"""Adapter selection (W-1): live by default, fake only on request, never a fallback.

The property under test is not "the flag works" but "there is no input that
silently yields the fake adapter, and no input that silently yields live when
live is unavailable". Every branch below is either a named adapter or a refusal.
"""

from __future__ import annotations

import importlib.util

import pytest
from server_helpers import absent, found, unreadable

from hfss_agent.adapter.fake import FakeAdapter
from hfss_agent.server import (
    FAKE,
    LEGAL_ADAPTER_VALUES,
    LIVE,
    AdapterSelectionError,
    build_adapter,
    resolve_adapter_kind,
    select_adapter,
)

# Constructing the LIVE adapter imports the AEDT API, which public CI
# deliberately does not install. The DECISIONS are tested unconditionally via
# resolve_adapter_kind -- that is the whole reason the decision was split from
# the construction; only the object-building step is gated.
_LIVE_BACKEND = importlib.util.find_spec("ansys") is not None
requires_pyaedt = pytest.mark.skipif(
    not _LIVE_BACKEND, reason="pyaedt (the `live` extra) is not installed"
)


def test_the_flag_is_absent_and_live_is_available() -> None:
    """Omitting the flag selects LIVE, not the developer-friendly option.

    Asserted on the DECISION rather than the constructed object, so this runs in
    public CI -- which installs no AEDT backend. A version of this test that
    built the adapter would be skipped on both CI legs, leaving the single most
    important default unproven exactly where it needs proving.
    """
    assert resolve_adapter_kind(None, found) == LIVE


def test_the_flag_is_absent_and_live_is_not_available() -> None:
    """THE CENTRAL REFUSAL. No PyAEDT and no flag must not degrade to the fake.

    A silent downgrade here is how a user ends up reading canned S-parameters
    under a provenance stamp that names their own design.
    """
    with pytest.raises(AdapterSelectionError) as caught:
        select_adapter(None, absent)
    assert "not installed" in caught.value.reason
    # THE REMEDY MUST NAME THE REQUIREMENT AND A COMMAND THAT WORKS. It used
    # to name ``uv sync --extra live``, which the README never mentioned --
    # so a refused operator was sent to a command the setup instructions did
    # not teach. Part 11 aligned the two; this pins the alignment, and will
    # fail if either side moves without the other.
    assert "'live' extra" in caught.value.remedy
    assert 'uv pip install -e ".[live]"' in caught.value.remedy


def test_absent_and_unreadable_are_different_refusals() -> None:
    """Preflight keeps the two apart; this must not collapse them.

    "Install it" and "reinstall it" send a user to different places, and the
    second one is the case that wastes an afternoon if it is mislabelled.
    """
    with pytest.raises(AdapterSelectionError) as not_installed:
        select_adapter(LIVE, absent)
    with pytest.raises(AdapterSelectionError) as broken:
        select_adapter(LIVE, unreadable)
    assert not_installed.value.reason != broken.value.reason
    assert "could not " in broken.value.reason


def test_fake_is_served_only_when_named() -> None:
    """The fake requires saying so -- and does NOT require PyAEDT.

    Uses the full ``select_adapter`` (decision plus construction), because the
    fake path builds without the live backend and so is CI-safe end to end.
    """
    assert isinstance(select_adapter(FAKE, absent), FakeAdapter)


def test_live_is_served_when_named_and_available() -> None:
    assert resolve_adapter_kind(LIVE, found) == LIVE


@requires_pyaedt
def test_the_live_kind_actually_constructs_a_real_adapter() -> None:
    """The one assertion that genuinely needs the extra installed: that LIVE
    builds a ``RealAdapter`` rather than something else."""
    assert type(build_adapter(LIVE)).__name__ == "RealAdapter"


def test_the_fake_kind_constructs_without_the_live_backend() -> None:
    """Building the fake must never touch the AEDT API -- otherwise a machine
    without PyAEDT could not run the fake either."""
    assert isinstance(build_adapter(FAKE), FakeAdapter)


def test_build_adapter_refuses_a_kind_it_did_not_resolve() -> None:
    """``build_adapter`` makes no decisions. An unknown kind is a programming
    error, not an operator one, and must not quietly become a default."""
    with pytest.raises(ValueError, match="constructible"):
        build_adapter("auto")


@pytest.mark.parametrize("given", [" FAKE ", "Fake", "fake\t", "  fake"])
def test_surrounding_whitespace_and_case_are_tolerated(given: str) -> None:
    """A stray space in a client's JSON config is a mis-set value, not a
    different intention."""
    assert isinstance(select_adapter(given, absent), FakeAdapter)


@pytest.mark.parametrize(
    "given", ["fkae", "", "   ", "auto", "real", "mock", "live fake", "0", "none"]
)
def test_an_unrecognised_value_refuses_rather_than_falling_back(given: str) -> None:
    """NOT "unknown, therefore default". An unrecognised value means the
    operator intended something this server could not honour; guessing which is
    how a fake session reaches a user who believes it.

    The empty and whitespace-only cases are the subtle ones: a flag passed with
    an empty value is MALFORMED, not absent, and must not inherit the default.
    """
    with pytest.raises(AdapterSelectionError) as caught:
        select_adapter(given, found)
    assert repr(given) in caught.value.reason
    for value in LEGAL_ADAPTER_VALUES:
        assert value in caught.value.remedy


def test_no_environment_variable_is_consulted(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE ENV-VAR PATH IS GONE, NOT DEPRECATED.

    The mechanism was deliberately replaced rather than supplemented: two
    mechanisms need a precedence rule, and a precedence rule is one more thing
    that can surprise someone. This pins the removal -- setting the old variable
    to 'fake' must have no effect whatsoever, because nothing reads it.
    """
    monkeypatch.setenv("HFSS_AGENT_ADAPTER", FAKE)
    with pytest.raises(AdapterSelectionError):
        resolve_adapter_kind(None, absent)
    assert resolve_adapter_kind(None, found) == LIVE


def test_the_probe_is_not_consulted_when_the_fake_is_requested() -> None:
    """Asking for the fake must not depend on the live backend being readable --
    otherwise a machine without PyAEDT could not run the fake either."""

    def exploding_probe():
        raise AssertionError("the PyAEDT probe must not run on the fake path")

    assert isinstance(select_adapter(FAKE, exploding_probe), FakeAdapter)


def test_every_operator_facing_message_is_ascii_only() -> None:
    """THE cp1252 GUARD, AND WHY IT IS A TEST RATHER THAN A ONE-OFF CHECK.

    These strings are an operator's only diagnostic and they go to stderr. The
    primary development platform's console encoding is cp1252, which cannot
    represent an em dash: a message containing one renders as
    "refusing to start ? PyAEDT ?" at exactly the moment someone needs to read
    it. That was measured, not supposed -- an earlier draft of these messages
    did precisely that.

    Enforced over EVERY refusal branch rather than a sample, because the failure
    is per-string: one un-checked message reintroduces it.
    """
    refusals = []
    for probe in (absent, unreadable):
        with pytest.raises(AdapterSelectionError) as caught:
            select_adapter(LIVE, probe)
        refusals.append(caught.value)
    with pytest.raises(AdapterSelectionError) as caught:
        select_adapter("nonsense", found)
    refusals.append(caught.value)

    offenders: dict[str, list[str]] = {}
    for refusal in refusals:
        for label, text in (("reason", refusal.reason), ("remedy", refusal.remedy)):
            bad = sorted({char for char in text if ord(char) > 127})
            if bad:
                offenders[f"{label}: {text[:40]}"] = bad
    assert not offenders, (
        f"non-ASCII characters in operator-facing text: {offenders}. These are "
        "printed to a cp1252 console; use plain ASCII punctuation."
    )
