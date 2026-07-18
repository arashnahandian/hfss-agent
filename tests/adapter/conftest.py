"""Shared fixtures for the adapter (W-3) tests."""

import pytest

from hfss_agent.adapter.fake import FakeAdapter


@pytest.fixture
def fake() -> FakeAdapter:
    """A FakeAdapter on the default scenario."""
    return FakeAdapter()
