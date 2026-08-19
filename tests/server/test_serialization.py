"""Tool-dispatch serialization (W-1): the measured race, and the lock that closes it.

WHY AN AGGREGATE OVER MANY ROUNDS RATHER THAN ONE ASSERTION. The race is
probabilistic. Measured without the lock, four concurrent callers corrupt the
final selection chain in roughly 40% of rounds -- so a single-round test would
pass two times in five while the defect was fully present. Every test here loops
and asserts on a COUNT, which is what makes a green result mean something.

THESE TESTS HAVE MEASURED TEETH. Removing ``serialized`` from the tool makes
``test_concurrent_callers_cannot_corrupt_the_selection_chain`` fail with roughly
50 mismatches in 120 rounds; the unserialized control below pins that, so the
suite proves the lock is load-bearing rather than assuming it.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

from server_helpers import (
    fast_broker,
    mismatched,
    real_writer_composition,
    selection_server,
)

from hfss_agent.server import TOOL_DISPATCH_LOCK
from hfss_agent.server.app import build_app
from hfss_agent.server.serialization import serialized

# Four concurrent callers over 120 rounds. Four is enough to corrupt the chain
# (measured ~40% of rounds unserialized); 120 keeps the aggregate decisive while
# the whole file stays near a second against an in-memory audit sink.
THREADS = 4
ROUNDS = 120


def _run_rounds(*, serialize: bool) -> int:
    """Drive ``THREADS`` concurrent tool calls per round; count corrupt chains.

    Goes through ``MCPServer.call_tool`` -- the SDK's real tool entry point,
    which dispatches each synchronous handler onto its own worker thread. That
    is the production concurrency, not a simulation of it.
    """
    async def rounds() -> int:
        corrupt = 0
        for _ in range(ROUNDS):
            session, broker = fast_broker()
            server = selection_server(broker, serialize=serialize)
            await asyncio.gather(
                *[
                    server.call_tool("drive_selection", {"tag": str(index)})
                    for index in range(THREADS)
                ]
            )
            if mismatched(session):
                corrupt += 1
        return corrupt

    return asyncio.run(rounds())


def test_concurrent_callers_cannot_corrupt_the_selection_chain() -> None:
    """THE PROPERTY. Every round's final chain is exactly one caller's.

    Each caller selects ``P<i>`` then ``D<i>``. A chain pairing ``P2`` with
    ``D0`` is a state no caller requested and no sequential execution could
    produce -- and, worse, one a subsequent read would stamp with honest-looking
    provenance naming the wrong design.
    """
    corrupt = _run_rounds(serialize=True)
    assert corrupt == 0, (
        f"{corrupt}/{ROUNDS} rounds ended with a selection chain no caller "
        "requested, with the dispatch lock in place. The lock is not covering "
        "the tool entry point."
    )


def test_without_the_lock_the_same_drive_does_corrupt_it() -> None:
    """THE CONTROL, AND IT IS THE POINT OF THE FILE.

    A passing test proves nothing unless its failure is reachable. This runs the
    identical harness with the ONLY difference being that the tool is not
    wrapped, and requires the corruption to actually appear. If this ever
    reports zero, the test above has gone vacuous -- the harness stopped
    exercising concurrency -- and both need investigating, not deleting.
    """
    corrupt = _run_rounds(serialize=False)
    assert corrupt > 0, (
        "the unserialized control produced no corruption in "
        f"{ROUNDS} rounds, so the serialized test above is no longer evidence "
        "of anything. Check that call_tool still dispatches handlers "
        "concurrently before trusting either result."
    )


def test_every_registered_tool_carries_the_serialized_marker() -> None:
    """THE REFLECTION CHECK, mirroring ``session.py``'s ``reconnect_guarded``.

    The concurrency test proves the lock works on a tool that uses it. THIS
    proves every shipped tool uses it -- which is the half that decays, because
    a tool added in a later step is exactly what forgets. There is deliberately
    no exemption list: an exemption list is how this test would start to rot.
    """
    import tempfile

    from hfss_agent.adapter.fake import FakeAdapter
    from hfss_agent.server import FAKE, build_composition

    composition = build_composition(FakeAdapter(), data_dir=tempfile.mkdtemp())
    app = build_app(composition, adapter_kind=FAKE)

    tools = app._tool_manager._tools
    assert tools, "no tools registered -- this check would pass vacuously"
    unserialized = [
        name
        for name, tool in tools.items()
        if not getattr(tool.fn, "__serialized__", False)
    ]
    assert not unserialized, (
        f"tools registered without @serialized: {unserialized}. Every tool must "
        "hold the process-wide dispatch lock; see server/serialization.py for "
        "the measured race and for what the lock does NOT cover."
    )


def test_the_lock_is_reentrant_on_one_thread() -> None:
    """An assembler re-entering through the broker must not hang the server.

    Today nothing below this layer takes a lock, so a plain ``Lock`` would also
    survive. This pins the reentrancy anyway, because a non-reentrant lock at
    two layers was measured to DEADLOCK on the first ``inspect_design`` -- the
    assembler dispatches twice -- and the failure mode is a hung server rather
    than a red test.
    """
    reached = []

    @serialized
    def outer() -> str:
        @serialized
        def inner() -> str:
            reached.append("inner")
            return "inner"

        return inner()

    finished = threading.Thread(target=outer, daemon=True)
    finished.start()
    finished.join(5.0)
    assert not finished.is_alive(), "re-entrant acquisition deadlocked"
    assert reached == ["inner"]


def test_the_marker_survives_signature_introspection() -> None:
    """``functools.wraps`` is load-bearing: the SDK builds each tool's input
    schema from the registered callable's signature. If the wrapper hid the real
    parameters, every tool would advertise ``(*args, **kwargs)`` and no client
    could call one correctly."""
    import inspect

    @serialized
    def sample(echo: str, count: int = 2) -> str:
        return echo * count

    parameters = inspect.signature(sample).parameters
    assert list(parameters) == ["echo", "count"]
    assert parameters["count"].default == 2
    assert sample.__serialized__ is True


def test_the_dispatch_lock_is_of_the_reentrant_type() -> None:
    """NARROWED AND RENAMED, because the old name promised what the assertion
    could not deliver.

    This was called ``test_the_lock_is_a_single_process_wide_object`` and its
    body was this one ``isinstance`` line. It distinguishes ``RLock`` from
    ``Lock`` -- ``type(threading.Lock())`` is ``_thread.lock``, a different
    type, so that much is real -- but it proves NEITHER 'single' NOR
    'process-wide': a freshly constructed per-instance ``RLock`` passes it
    identically. The claim now lives in the test below, which cannot pass
    against a per-instance lock.
    """
    assert isinstance(TOOL_DISPATCH_LOCK, type(threading.RLock()))
    assert not isinstance(threading.Lock(), type(threading.RLock())), (
        "the isinstance check no longer distinguishes Lock from RLock, so it "
        "is not testing the reentrancy this module depends on"
    )


def test_a_serialized_call_holds_the_ONE_module_level_lock() -> None:
    """THE CLAIM THE RENAMED TEST ABOVE COULD NOT MAKE: the lock a decorated
    tool takes is the module-level ``TOOL_DISPATCH_LOCK``, not one of its own.

    Checked from ANOTHER THREAD, which is the only way to ask. ``RLock`` is
    reentrant, so a re-acquire on the calling thread succeeds whether or not it
    is the same object; a second thread's non-blocking acquire fails if and
    only if the running handler really holds this object.

    FAILS WHEN: ``serialized`` builds its own lock, takes one off the app or
    the composition, or stops locking at all. Each of those leaves the process
    with more than one lock and therefore with no serialization at all -- the
    exact failure ``serialization.py`` says a module-level lock exists to
    prevent ("a per-instance lock would silently stop serializing the moment a
    second instance appeared").
    """
    observed: dict[str, bool] = {}

    def probe_from_another_thread() -> None:
        acquired = TOOL_DISPATCH_LOCK.acquire(blocking=False)
        observed["acquired_while_held"] = acquired
        if acquired:
            # Release from the thread that took it, or every later test in
            # this process deadlocks on a lock nobody owns.
            TOOL_DISPATCH_LOCK.release()

    @serialized
    def tool() -> str:
        prober = threading.Thread(target=probe_from_another_thread, daemon=True)
        prober.start()
        prober.join(5.0)
        assert not prober.is_alive(), "the probe thread never finished"
        return "done"

    assert tool() == "done"
    assert observed["acquired_while_held"] is False, (
        "another thread acquired TOOL_DISPATCH_LOCK while a @serialized tool "
        "was running, so the decorator is holding some OTHER lock. There is "
        "more than one lock in this process and nothing is serialized."
    )


def test_the_probe_would_notice_an_unheld_lock() -> None:
    """The companion limb: outside a serialized call the same non-blocking
    acquire SUCCEEDS. Without this, a probe that always reported False -- a
    thread that never ran, an exception swallowed -- would make the test above
    pass for the wrong reason."""
    acquired: list[bool] = []

    def probe() -> None:
        got = TOOL_DISPATCH_LOCK.acquire(blocking=False)
        acquired.append(got)
        if got:
            TOOL_DISPATCH_LOCK.release()

    prober = threading.Thread(target=probe, daemon=True)
    prober.start()
    prober.join(5.0)
    assert acquired == [True], (
        "the lock could not be acquired from another thread even with no tool running"
    )


def test_the_audit_log_loses_no_record_under_concurrent_tool_calls(
    tmp_path: Path,
) -> None:
    """THE AUDIT-INTEGRITY PROPERTY, and it is the reason the lock sits here.

    Measured before the lock: appending from multiple threads in one process
    DROPPED records -- 400 expected, 390 written, with ``torn_tail`` False and
    ``corrupt_lines`` empty, so the log looked complete while being short. The
    writer's own docstring calls that outcome "worse than no log, because it
    looks complete", and its accepted-limitations paragraph scopes its
    single-writer assumption to "two server instances" -- two PROCESSES. The SDK
    puts a second writer inside ONE process, which that paragraph never
    contemplated.

    Every append in ``src/`` happens inside ``Broker.dispatch``, so a lock
    around the whole tool invocation covers all of them. This drives the REAL
    ``AuditLogWriter`` and counts lines, because the defect is in that writer.
    """
    composition = real_writer_composition(str(tmp_path))
    calls_per_thread = 6
    threads = 8
    expected = threads * calls_per_thread

    @serialized
    def touch(tag: str) -> str:
        composition.broker.dispatch("get_session_status", {})
        return tag

    barrier = threading.Barrier(threads)

    def worker(index: int) -> None:
        barrier.wait()
        for _ in range(calls_per_thread):
            touch(str(index))

    workers = [threading.Thread(target=worker, args=(i,)) for i in range(threads)]
    for worker_thread in workers:
        worker_thread.start()
    for worker_thread in workers:
        worker_thread.join()

    log_path = tmp_path / "audit-log.jsonl"
    written = log_path.read_text(encoding="utf-8").splitlines()
    lines = [line for line in written if line.strip()]
    parsed = [json.loads(line) for line in lines]

    assert len(lines) == expected, (
        f"expected {expected} audit records, found {len(lines)}. Records are "
        "being lost under concurrent dispatch even with the server-layer lock, "
        "which would mean a writer-level lock is required after all."
    )
    assert all(record["tool_name"] == "get_session_status" for record in parsed)
