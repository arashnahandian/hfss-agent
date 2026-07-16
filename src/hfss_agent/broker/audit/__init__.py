"""broker/audit — append-only JSONL audit writer.

Every tool call: timestamp, tool, sanitized args, selection state, risk tier,
outcome, duration, snapshot_id if one was emitted. Append-only by construction.
"""
