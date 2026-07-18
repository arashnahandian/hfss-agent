"""Crash / disconnect / cannot_evaluate are distinct, per-operation outcomes (W-3).

Proves ADR-10's core requirement: a crash and a lost/dropped session are
different types with different recovery meaning and never collapse into one
generic error. Also proves faults are injectable independently per operation and
that cannot_evaluate is NOT a session fault and maps onto the contract type.
"""

import subprocess
import sys

from hfss_agent.adapter.fake import FakeAdapter, OpBehavior, Scenario
from hfss_agent.adapter.results import (
    AdapterCannotEvaluate,
    AdapterCrash,
    AdapterDisconnect,
    SessionFault,
)
from hfss_agent.contract.tool_io import CannotEvaluate


def _fake_injecting(op: str, outcome) -> FakeAdapter:
    return FakeAdapter(Scenario(behavior={op: OpBehavior(fault=outcome)}))


def test_crash_and_disconnect_are_distinct_types_and_status() -> None:
    crash_fake = _fake_injecting("read_solve_state", AdapterCrash(detail="AEDT died"))
    disconnect_fake = _fake_injecting(
        "read_solve_state", AdapterDisconnect(detail="link dropped")
    )
    crash = crash_fake.read_solve_state()
    disconnect = disconnect_fake.read_solve_state()

    assert isinstance(crash, AdapterCrash)
    assert isinstance(disconnect, AdapterDisconnect)
    # They do not collapse into one another (ADR-10).
    assert type(crash) is not type(disconnect)
    assert crash.status == "crashed" and disconnect.status == "disconnected"
    # Both are session faults -> both drive suspect + reconnect-and-verify.
    assert isinstance(crash, SessionFault) and isinstance(disconnect, SessionFault)


def test_cannot_evaluate_is_not_a_session_fault_and_maps_to_the_contract() -> None:
    fake = FakeAdapter(
        Scenario(
            behavior={
                "read_solved_data": OpBehavior(
                    fault=AdapterCannotEvaluate(
                        reason="get_solution_data returned None",
                        limitation="No solved data for the selected sweep.",
                    )
                )
            }
        )
    )
    result = fake.read_solved_data()
    assert isinstance(result, AdapterCannotEvaluate)
    # Session stays healthy: this is not a transport fault.
    assert not isinstance(result, SessionFault)
    # The tool layer maps it onto the contract CannotEvaluate (adding template_text);
    # the adapter outcome carries exactly what that arm needs.
    contract_arm = CannotEvaluate(
        reason=result.reason,
        limitation=result.limitation,
        template_text="[cannot_evaluate] no solved data",
    )
    assert contract_arm.outcome == "cannot_evaluate"


def test_faults_are_injectable_independently_per_operation() -> None:
    # attach succeeds while read_solve_state disconnects — proving the override
    # map is per-operation, not adapter-wide.
    fake = _fake_injecting("read_solve_state", AdapterDisconnect(detail="dropped"))
    from hfss_agent.contract import Environment

    assert isinstance(fake.attach(4321), Environment)
    assert isinstance(fake.read_solve_state(), AdapterDisconnect)


def test_fake_adapter_imports_no_pyaedt() -> None:
    # The fake must stay licence-free forever: importing it (and its package) must
    # not pull in pyaedt. Fresh interpreter so no other import can mask a leak.
    code = (
        "import sys\n"
        "import hfss_agent.adapter\n"
        "import hfss_agent.adapter.fake  # noqa: F401\n"
        "leaked = sorted(m for m in sys.modules "
        "if m == 'pyaedt' or m.startswith('pyaedt.'))\n"
        "assert not leaked, leaked\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
