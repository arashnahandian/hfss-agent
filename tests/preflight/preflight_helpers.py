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
from datetime import datetime, timezone

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


# --- the hostile redaction fixture -------------------------------------------
#
# EVERY NAME BELOW IS INVENTED. No path, username, machine name, project or
# organisation from this repository or the machine it is built on appears here,
# because a fixture whose realism came from real data would itself be the
# disclosure it exists to prevent.

# The identifiers that must never survive redaction. Named once so the tests
# assert against the same set the fixture plants, and so the negative control
# can iterate it rather than repeating a literal.
PLANTED_IDENTIFIERS: tuple[str, ...] = (
    "kestrel-radar-v7",
    "northwind-defence",
    r"D:\clients\northwind-defence\kestrel\kestrel-radar-v7.aedt",
    "PhasedArray_Tile",
    "element_pitch_mm",
    "12.5",
    "sha256:kestrelvariation",
    "bluefin-antenna",
    "export_northwind_q3_report",
)

# Secret-bearing environment variables. Present on the fixture machine, and
# absent from anything W-11 can see — the AEDT probe returns install-root NAMES
# only, so these never enter the process's view of the environment at all.
SECRET_ENVIRONMENT: dict[str, str] = {
    "ANSYS_LICENSE_FILE": "1055@licsrv.northwind-defence.example",
    "NORTHWIND_API_TOKEN": "sk-live-8f3a9c2e4b1d",
}

# The tool names a registry actually holds, for the ``tool_name`` guard.
KNOWN_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "attach",
        "list_selection_options",
        "select",
        "get_session_status",
        "inspect_design",
        "validate_native",
        "get_audit_log",
    }
)


def _record(
    tool_name: str,
    outcome: str,
    selection: dict[str, object],
    arguments: dict[str, object],
    *,
    risk_tier: str | None = "safe",
    seconds: int = 0,
) -> AuditRecord:
    return AuditRecord(
        timestamp=datetime(2026, 8, 3, 9, 14, seconds, tzinfo=timezone.utc),
        tool_name=tool_name,
        sanitized_arguments=arguments,
        selection_state=selection,
        risk_tier=risk_tier,
        outcome=outcome,
        duration=0.125,
        session_degraded=False,
    )


def hostile_audit_records() -> list[AuditRecord]:
    """Three records, each carrying a different reason redaction is hard.

      1. THE HISTORICAL PROJECT — fully selected, and NOT the current
         selection. This is the record that discriminates key-based redaction
         from known-value matching: a matcher built from the live chain never
         sees ``kestrel-radar-v7``. Its variation carries dimensions, which is
         geometry rather than identity.
      2. THE CALLER-CONTROLLED TOOL NAME — an ``unknown_capability`` dispatch,
         where the broker records the name it was handed verbatim and that name
         identifies a customer. ``risk_tier`` is None, which the contract
         requires for this outcome.
      3. THE COLLIDING NAME — a design legitimately named ``ok``. It exists to
         show that a known-value matcher would not merely be incomplete but
         would rewrite that substring throughout, corrupting the ``outcome``
         field of every record in the log.
    """
    return [
        _record(
            "select",
            "ok",
            {
                "process_id": 8842,
                "project": {
                    "name": "kestrel-radar-v7",
                    "path": (
                        r"D:\clients\northwind-defence\kestrel"
                        r"\kestrel-radar-v7.aedt"
                    ),
                },
                "design": "PhasedArray_Tile",
                "solution_type": "DrivenModal",
                "setup": "Setup1",
                "sweep": "Sweep1",
                "variation": {
                    "values": {"element_pitch_mm": "12.5", "substrate_h_mm": "0.79"},
                    "variation_hash": "sha256:kestrelvariation",
                },
            },
            {"stage": "project", "choice": "kestrel-radar-v7"},
            seconds=1,
        ),
        _record(
            "export_northwind_q3_report",
            "unknown_capability",
            dict.fromkeys(
                (
                    "process_id",
                    "project",
                    "design",
                    "solution_type",
                    "setup",
                    "sweep",
                    "variation",
                )
            ),
            {},
            risk_tier=None,
            seconds=2,
        ),
        _record(
            "select",
            "ok",
            {
                "process_id": 8842,
                "project": {
                    "name": "bluefin-antenna",
                    "path": r"E:\proj\bluefin\bluefin-antenna.aedt",
                },
                "design": "ok",
                "solution_type": "DrivenTerminal",
                "setup": None,
                "sweep": None,
                "variation": None,
            },
            {"stage": "design", "choice": "ok"},
            seconds=3,
        ),
    ]
