"""Shared helpers for the W-11 preflight suite (Step 2.4b).

Two kinds of fixture, because W-11 has two inputs. The PROBES are injected as
plain data — no machine is read, ever, on any leg. The BROKER is real, driving
the licence-free ``FakeAdapter``, because the attached path's whole point is
that it crosses a boundary; stubbing it would test the stub.

Uniquely named (not ``conftest``) and imported explicitly, following the
session, broker, inspect and validate_native suites' stated rationale: sibling
``conftest`` modules from different test dirs collide under pytest's rootdir
import mode. The broker builders duplicate ``native_helpers``' shape for the
reason that file records — importing across suite directories would work only
through pytest's collection-order ``sys.path`` insertion, and would make this
suite's importability depend on which directory was collected first.
"""

from __future__ import annotations

from collections.abc import Collection

from hfss_agent.adapter.fake import FakeAdapter, Scenario
from hfss_agent.broker import (
    Broker,
    CapabilityRegistry,
    RefuseAllConfirmer,
    session_routed_specs,
)
from hfss_agent.contract import AuditRecord, Environment
from hfss_agent.preflight import EnvironmentProbes, VersionRead
from hfss_agent.session import Session

DEFAULT_PID = 1234

# The healthy machine every test varies from: PyAEDT at the pin, Python at the
# recommended version, a wrapper version that parses.
HEALTHY_PYAEDT = VersionRead("1.2.0", "found")
HEALTHY_PYTHON = "3.12.10"
HEALTHY_WRAPPER = "0.3.0"


class RecordingSink:
    """In-memory ``AuditSink``: appends to a list, never touches a file."""

    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


def root_names(*versions: str) -> frozenset[str]:
    """``"2026.1"`` -> ``{"ANSYSEM_ROOT261"}`` — install roots by version.

    Tests name the VERSION they mean and this builds the variable name, so a
    reader does not have to decode ``261`` to see which case is under test.
    """
    names = set()
    for version in versions:
        year, release = version.split(".")
        names.add(f"ANSYSEM_ROOT{year[2:]}{release}")
    return frozenset(names)


def fixture_probes(
    *,
    aedt: Collection[str] = (),
    pyaedt: VersionRead = HEALTHY_PYAEDT,
    python: str = HEALTHY_PYTHON,
    wrapper: str = HEALTHY_WRAPPER,
) -> EnvironmentProbes:
    """A complete probe set. Every field is supplied, always — the seam has no
    defaults precisely so a fixture cannot half-substitute and inherit the host
    for the rest."""
    names = frozenset(aedt)
    return EnvironmentProbes(
        aedt_env_var_names=lambda: names,
        pyaedt_version=lambda: pyaedt,
        python_version=lambda: python,
        wrapper_version=lambda: wrapper,
    )


def _broker(session: Session) -> tuple[Broker, RecordingSink]:
    sink = RecordingSink()
    return (
        Broker(
            session=session,
            registry=CapabilityRegistry(session_routed_specs(session)),
            audit_sink=sink,
            confirmer=RefuseAllConfirmer(),
        ),
        sink,
    )


def attached_broker(aedt_version: str = "2026.1") -> tuple[Broker, RecordingSink]:
    """A broker whose session is ATTACHED, reporting ``aedt_version``.

    No selection is made: preflight reads only the environment block, so a
    project/design selection would be scenery. The attach drives the session
    DIRECTLY rather than dispatching, so the returned sink holds only records
    the test's own call produced — which is what makes "preflight wrote nothing"
    a clean assertion rather than an arithmetic one.
    """
    scenario = Scenario(
        environment=Environment(
            aedt_version=aedt_version,
            pyaedt_version="1.2.0",
            python_version="3.12.4",
            wrapper_version="0.0.0",
        )
    )
    session = Session(FakeAdapter(scenario))
    session.attach(DEFAULT_PID)
    return _broker(session)


def detached_broker() -> tuple[Broker, RecordingSink]:
    """A broker whose session was never attached — the pre-attach state Journey
    1.0 actually runs in."""
    return _broker(Session(FakeAdapter()))
