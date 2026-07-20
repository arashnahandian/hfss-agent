"""Broker-domain file error (interim for contract gaps 1-2; plan decision 1).

The pinned contract promises a typed *file* error for broker file failures but
does not yet define one (gap 1), and ``ExportResult`` has no arm for a failed
or invalid write (gap 2 — ``ExportRefused`` is literally
``refused_existing_path``, and ``CannotEvaluate`` is pinned by ADR-16 to
"PyAEDT could not evaluate", which a disk-full or bad-path failure is not).
Until the pending contract amendment lands (a semver event), broker file
failures surface as this exception: the dispatch pipeline audits an escaping
exception as ``typed_error`` and re-raises it, so a failure is loud,
attributed to the file layer, and never misreported as a PyAEDT limitation.
"""

from __future__ import annotations


class BrokerFileError(Exception):
    """A typed file-layer failure: path validation refused, or a write/read
    did not complete. Carries the target ``path``, the specific ``reason``,
    and — when a temp-then-replace write failed after its temp was created —
    the ``orphaned_temp`` path, so a file left behind is never silent
    (ADR-19 correction: for an overwrite-export that orphan sits in the
    USER'S own directory, not the broker's data dir)."""

    def __init__(
        self, path: str, reason: str, *, orphaned_temp: str | None = None
    ) -> None:
        self.path = path
        self.reason = reason
        self.orphaned_temp = orphaned_temp
        message = f"file operation failed for '{path}': {reason}"
        if orphaned_temp is not None:
            message += (
                f" A temporary file was left behind at '{orphaned_temp}' — it"
                " was not removed (no deletion path exists in this codebase);"
                " you may remove it manually."
            )
        super().__init__(message)
