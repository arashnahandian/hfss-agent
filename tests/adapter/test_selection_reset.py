"""Selecting a stage clears everything below it (W-3 stale-scope fix).

``downstream_reset`` is the single source of truth both adapters use, so a
re-select never leaves a stale downstream entry. Exercised here as pure logic and
through the FakeAdapter's public ``select()``; the RealAdapter half (downstream
reset plus the ``_scope`` incoherent-binding guard) lives with the RealAdapter
double in ``test_real_adapter.py``.
"""

from __future__ import annotations

from hfss_agent.adapter.fake import FakeAdapter
from hfss_agent.adapter.selection import downstream_reset


def test_downstream_reset_clears_only_stages_below() -> None:
    assert downstream_reset("project") == {
        "design": None,
        "solution_type": None,
        "setup": None,
        "sweep": None,
        "variation": None,
    }
    assert downstream_reset("design") == {
        "setup": None,
        "sweep": None,
        "variation": None,
    }
    assert downstream_reset("setup") == {"sweep": None, "variation": None}
    assert downstream_reset("sweep") == {"variation": None}
    assert downstream_reset("variation") == {}


def _full_chain(fake: FakeAdapter) -> None:
    fake.attach(1)
    fake.select("project", "patch_antenna")
    fake.select("design", "HFSSDesign1")
    fake.select("setup", "Setup1")
    fake.select("sweep", "Sweep1")
    fake.select("variation", "sha256:defaultvariation")


def test_reselecting_project_clears_the_whole_downstream_chain() -> None:
    fake = FakeAdapter()
    _full_chain(fake)
    chain = fake.select("project", "patch_antenna")  # re-select the top stage
    assert chain.project is not None
    assert chain.design is None
    assert chain.solution_type is None
    assert chain.setup is None
    assert chain.sweep is None
    assert chain.variation is None


def test_reselecting_setup_clears_only_sweep_and_variation() -> None:
    fake = FakeAdapter()
    _full_chain(fake)
    chain = fake.select("setup", "Setup1")  # re-select a mid stage
    # Upstream (project/design/solution_type) preserved; only below setup cleared.
    assert chain.design == "HFSSDesign1"
    assert chain.solution_type is not None
    assert chain.setup == "Setup1"
    assert chain.sweep is None
    assert chain.variation is None
