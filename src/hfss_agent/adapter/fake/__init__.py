"""fake adapter — same interface as W-3, canned data, no license required.

All license-free development and both CIs run against this. Can simulate hangs,
crashes, and disconnects on demand so the session-lifecycle paths run in CI.
"""

from hfss_agent.adapter.fake.fake_adapter import FakeAdapter
from hfss_agent.adapter.fake.scenario import OpBehavior, Scenario

__all__ = ["FakeAdapter", "Scenario", "OpBehavior"]
