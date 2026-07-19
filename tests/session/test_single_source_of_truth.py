"""The session's chain and the adapter's ACTUAL cached selection never diverge.

The session is the single source of truth and drives the adapter so the two agree
after every select and after a verify mismatch (which advances the adapter, then
resyncs). These tests read the FakeAdapter's real ``_selection`` — they do not
assume it.
"""

from __future__ import annotations

from session_helpers import (
    FULL_CHAIN,
    attached,
    build_full_chain,
    force_suspect,
    list_timeout_then,
)

from hfss_agent.session.status import _Health


def test_chain_matches_adapter_after_each_select() -> None:
    session, fake = attached()
    for stage, choice in FULL_CHAIN:
        session.select(stage, choice)
        # read the adapter's REAL cached selection, not an assumption
        assert session._state.chain == fake._selection


def test_chain_matches_adapter_after_verify_mismatch_and_resync() -> None:
    session, fake = attached(list_timeout_then())
    build_full_chain(session, stale_stage="design")  # verify will reset from design
    force_suspect(session)
    session.list_selection_options("project")  # verify -> mismatch at design -> resync

    assert session._state.health is _Health.ATTACHED
    # resync re-scoped the adapter to the retained chain: the two agree again
    assert session._state.chain == fake._selection
    assert session._state.chain.project is not None
    assert session._state.chain.design is None
