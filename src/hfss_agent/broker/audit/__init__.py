"""broker/audit — append-only JSONL audit writer.

Every tool call: timestamp, tool, sanitized args, selection state, risk tier,
outcome, duration, snapshot_id if one was emitted. Append-only by construction
(``"a"`` is the only write mode in this subpackage); the reader parses the log
back with the two-arm torn-tail policy (see ``reader.py``).
"""

from hfss_agent.broker.audit.reader import AuditReadResult, read_audit_records
from hfss_agent.broker.audit.writer import AuditLogWriter

__all__ = ["AuditLogWriter", "AuditReadResult", "read_audit_records"]
