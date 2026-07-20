"""User-confirmation scaffolding for the medium/high risk tiers (W-4, §6.1).

The MVP tool surface is 100% safe-tier, so nothing shipped can reach this flow
— but ADR-5's rationale is that retrofitting an enforcement point under
already-shipped tools is how tier checks become advisory, so the flow exists
now, is exercised by tests against synthetic capabilities, and fails CLOSED:

  * the Tier 1 default confirmer refuses everything (deny-by-default): with no
    confirmation channel to a user, an unconfirmable action is refused, never
    assumed approved;
  * HIGH tier never reaches the confirmer at all — the broker refuses it
    unconditionally until the ADR-6 pre-change snapshot provider exists (see
    ``broker.py``).

How a confirmation physically reaches a user over MCP is deliberately
unresolved (a Tier 2.3 decision; elicitation is the candidate). Nothing here
depends on resolving it, precisely because the default refuses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from hfss_agent.contract import RiskTier


@dataclass(frozen=True)
class ConfirmationRequest:
    """What a user would be asked to approve: the capability, its tier, the
    registered human-readable action description, and the arguments — already
    through the ADR-9 sanitizer, because a confirmation prompt must never
    render raw untrusted strings."""

    capability: str
    tier: RiskTier
    description: str
    sanitized_arguments: dict[str, object]


class Confirmer(Protocol):
    """The per-action confirmation seam, consulted for medium-tier dispatches
    only (safe never asks; high is refused before asking)."""

    def confirm(self, request: ConfirmationRequest) -> bool:
        """True to approve the action, False to refuse it."""
        ...


class RefuseAllConfirmer:
    """The Tier 1 default: refuse every request (fail closed).

    Deliberately NOT interactive and NOT configurable — until a real
    confirmation channel exists, approval is unobtainable, so even a
    misregistered medium-tier capability cannot run.
    """

    def confirm(self, request: ConfirmationRequest) -> bool:
        return False
