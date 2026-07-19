"""W-2 · session — AEDT session lifecycle and selection state.

Attaches (attach-only) to an already-running AEDT process, owns the selection
chain process -> project -> design -> setup -> sweep -> variation as an
order-enforcing state machine, and re-verifies a suspect session before the next
operation. Recovery from a lost session is a deliberate user re-attach — this
module never re-attaches automatically (see ``session.py``: divergence from
ADR-10 / §6.7, to be recorded in ADR-18).

Process discovery (``list_aedt_processes``) is deliberately NOT here — it is
deferred to its own step and ADR (a discovery method that cannot discover would
be a false-shaped placeholder). The public surface starts at ``attach``.
"""

from hfss_agent.session.session import Session

__all__ = ["Session"]
