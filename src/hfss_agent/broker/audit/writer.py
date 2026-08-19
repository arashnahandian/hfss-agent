"""The real ``AuditSink`` (W-4, Part 4): append-only JSONL persistence.

WHY THIS FILE CARRIES WEIGHT: the read-only MVP answers "what did you
change?" by construction — nothing — so the audit log carries the ENTIRE
burden of "what did you do?". A log that silently drops or rewrites a record
is worse than no log, because it looks complete; append-only is what makes it
evidence rather than a mutable summary. Accordingly ``"a"`` is the ONLY mode
any file is opened with for writing in ``broker/audit`` — no ``"w"``, no
``"r+"`` — and Part 5's source audit enforces exactly that.

OPEN-PER-APPEND, closed immediately — never a handle held across calls — for
two reasons: Windows holds exclusive-ish locks on open handles, so a held
handle would interfere with ``get_audit_log`` reading the same file
mid-session; and open-per-append is crash-safer — there is no long-lived
buffered tail to lose. The per-call open cost is irrelevant at human
tool-call rates.

DELIBERATELY NOT ROUTED through ``files/writes.py``: those primitives guard
USER-SUPPLIED paths (ADR-8 — overwrite refusal, path validation), while the
audit log lives at a broker-config path that no user input and no
HFSS-sourced string can influence (ADR-9 upheld structurally). Different
threat, different mechanism: an append needs no overwrite guard and must
never be refused for an existing path — an existing log is the normal case.

ACCEPTED LIMITATIONS — stated, with no machinery built for either:
  * concurrency: THIS WRITER IS SAFE ONLY FOR A SINGLE WRITER IN A SINGLE
    THREAD. That is narrower than this paragraph used to claim. It said the
    hazard was "two server instances appending to one log" — two PROCESSES —
    and rested the mitigation on "one server per user". Measured, the case that
    actually loses records is TWO THREADS IN ONE PROCESS, which that mitigation
    does not reach at all: append-mode open is not atomic on Windows (the CRT
    seeks to end, then writes) and the newline guard adds a second open,
    widening the window further.

    The measurement, so the size of it is not left to imagination. 400 records
    appended from 16 threads: WITHOUT a lock, 395 lines written — 5 records lost
    and 2 lines torn — while ``torn_tail`` reported False and ``corrupt_lines``
    was empty, so the log looked complete. WITH the Step 2.8 server-layer lock,
    400 of 400, nothing lost, nothing torn. Silent loss is precisely the outcome
    this module's opening paragraph calls "worse than no log, because it looks
    complete", and neither of the reader's two incompleteness signals can see
    it: nothing was torn and nothing was corrupt — records simply were not there.

    WHAT MAKES IT SAFE TODAY IS A CALLER, NOT THIS FILE. Every append in
    ``src/`` happens inside ``Broker.dispatch``, and Step 2.8's server layer
    serializes every tool invocation behind one process-wide ``RLock``, so
    dispatches never overlap. No cross-platform locking is built here
    (msvcrt/fcntl diverge), so a second writer — another process, or any future
    in-process caller that reaches a ``Broker`` outside that lock — reintroduces
    the loss with nothing in this module to prevent it.
  * rotation: none, ever. Growth is bounded by human-rate usage; read-side
    cost is handled by the range limit; and rotation would sit awkwardly
    against "append-only".
"""

from __future__ import annotations

import os

from hfss_agent.broker.files.errors import BrokerFileError
from hfss_agent.broker.files.locations import ensure_data_dir
from hfss_agent.contract import AuditRecord


class AuditLogWriter:
    """The persistent ``AuditSink``: one JSON object per line, appended per
    call. Part 4 adds only persistence — every dispatch property is already
    proven against the in-memory sink (Part 2 tests), so this class stays a
    thin, mode-locked writer."""

    def __init__(self, path: str) -> None:
        self._path = path
        # The broker may create its OWN data directory only; reuse the
        # locations resolver so the repo keeps a single makedirs call site.
        try:
            ensure_data_dir(os.path.dirname(path))
        except OSError as exc:
            raise BrokerFileError(
                path,
                "the audit log's directory could not be created: "
                f"{type(exc).__name__}: {exc}",
            ) from exc

    @property
    def path(self) -> str:
        return self._path

    def append(self, record: AuditRecord) -> None:
        """Append one record as one JSONL line. ``"a"`` mode ONLY (module
        docstring); ``newline="\\n"`` keeps the log byte-identical across the
        windows/ubuntu CI legs (plan §6d).

        NEWLINE GUARD (ADR-19 fix 1): a crash mid-append leaves a torn final
        line with no trailing newline; without the guard, the next append
        would CONCATENATE onto that stub — destroying a successfully-audited
        record (defect 1 of the two named in ``reader.py``). If the log's
        last byte is not a newline, one is written ahead of the record so the
        stub keeps its own line. Append-only is unaffected: the guard adds a
        READ, never a rewrite.
        """
        prefix = "\n" if self._tail_missing_newline() else ""
        line = prefix + record.model_dump_json() + "\n"
        try:
            with open(self._path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(line)
        except OSError as exc:
            # Wrapped for the file layer's typed-failure policy; the dispatch
            # converts any sink exception into the loud AuditFailure (Part 2).
            raise BrokerFileError(
                self._path,
                f"the audit record could not be appended: "
                f"{type(exc).__name__}: {exc}",
            ) from exc

    def _tail_missing_newline(self) -> bool:
        """Whether the log exists, is non-empty, and does not end in a
        newline — i.e. its tail is a torn stub that needs its own line ending
        before the next record.

        A SEPARATE read-mode open, deliberately NOT ``"a+"``, so "every write
        mode in broker/audit is 'a'" stays literally auditable (Part 5).
        Binary, because a stub's last byte may sit mid-codepoint, which a
        text-mode read could not decode. Zero-length and missing files need
        no guard. The check-then-append TOCTOU window is accepted — module
        docstring, the single-writer assumption.
        """
        try:
            with open(self._path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    return False
                handle.seek(-1, os.SEEK_END)
                return handle.read(1) != b"\n"
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise BrokerFileError(
                self._path,
                "the audit log tail could not be checked before appending: "
                f"{type(exc).__name__}: {exc}",
            ) from exc
