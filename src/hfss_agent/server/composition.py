"""The composition root (W-1, Step 2.8): the one place the object graph is built.

LIFTED FROM A TEST, WHICH IS WHERE IT LIVED UNTIL NOW.
``tests/prohibited_ops/test_tier_surface.py`` has carried a ``_production_registry``
helper since Part 5 of the broker step, with a docstring saying in as many words:
"The full production capability surface, composed the way Step 2.8 will … Until
2.8 provides a single composition root, the factory list here IS the production
surface; when that root exists, this test should build the registry through it
instead so the two can never diverge." This module is that root. Re-pointing the
test at it is deliberately NOT done in the same commit — the two must be seen to
agree while they are still independently written, or the check is circular.

THE COMPOSITION CONTRACT THIS EXISTS TO HONOUR, quoted from ``Broker``: "the
registry's session-routed handlers must be bound to the SAME ``Session``
instance injected here … The broker captures per-call selection state from its
session; a mismatched pair would audit one session's state against another
session's operations." One ``Session`` is built here and threaded into all three
spec factories AND the broker, so the pairing is visible in one screen of code
rather than asserted in prose.

ONE ``data_dir`` FEEDS BOTH FILE COLLABORATORS, which is the pairing
``broker.py`` spells out at its ``data_dir`` parameter: "at composition (Step
2.8) both derive from the SAME data_dir — ``IntentStore(default_intent_path(
data_dir))`` alongside ``Broker(data_dir=data_dir)``". The audit capability is
built from ``default_audit_log_path(data_dir)`` for the same reason — its
docstring requires the path to be "the SAME path the broker's audit writer
appends to".

THIS MODULE PERFORMS NO FILE I/O ITSELF, and must not: the boundary audit checks
every source under ``src/`` outside ``broker``. The directory-creating calls
(``default_intent_path``, ``default_audit_log_path``) live in broker's
``locations``, which owns the one permitted ``makedirs`` site in the repo. Note
that they DO create the data directory when called — so building a composition
touches the disk, which is why it happens in ``main()`` and never at import.

NOTHING IS DISPATCHED HERE. Construction is inert: registration closes over
paths and bound methods without calling any of them, and no adapter round trip
happens until a tool is invoked. That matters for more than startup latency —
every audit-log append in ``src/`` goes through ``Broker.dispatch``, so a
composition that dispatched during construction would append a record outside
whatever lock the server layer later wraps tool invocations in.
"""

from __future__ import annotations

from dataclasses import dataclass

from hfss_agent.adapter import Adapter
from hfss_agent.broker import (
    Broker,
    CapabilityRegistry,
    IntentStore,
    RefuseAllConfirmer,
    audit_capabilities,
    intent_capabilities,
    session_routed_specs,
)
from hfss_agent.broker.files.locations import (
    default_audit_log_path,
    default_data_dir,
    default_intent_path,
)
from hfss_agent.session import Session


@dataclass(frozen=True)
class Composition:
    """The wired object graph, and the handles the tool layer actually needs.

    Frozen, because the graph is built once per process and rebinding any part
    of it would break the same-session pairing the constructor established.

    ``registry`` is exposed rather than kept private for one concrete reason
    beyond introspection: ``preflight.export_diagnostics_bundle`` takes
    ``known_tool_names`` as data, documented as "the names the capability
    registry declares, supplied by the site that BUILT the registry" — which is
    this module. ``session`` is exposed because the tier-surface proof and the
    Part 5 tests assert against it; the tool layer itself should reach the
    session only through ``broker``.
    """

    broker: Broker
    session: Session
    registry: CapabilityRegistry
    data_dir: str

    def known_tool_names(self) -> tuple[str, ...]:
        """The registered capability names, for ``export_diagnostics_bundle``'s
        redaction pass. Derived from the registry rather than hand-listed, so it
        cannot drift from what is actually registered."""
        return tuple(spec.name for spec in self.registry.specs)


def build_composition(adapter: Adapter, data_dir: str | None = None) -> Composition:
    """Wire adapter -> Session -> registry -> Broker and hand back the graph.

    Args:
        adapter: the backend this process will use. REQUIRED AND UNDEFAULTED —
            choosing it is ``adapter_selection``'s job, deliberately not this
            module's. Separating them keeps the fail-closed refusal in one place
            and lets tests compose against a ``FakeAdapter`` without going
            near an environment variable.
        data_dir: where the audit log and intent file live. ``None`` means the
            platform default (``%LOCALAPPDATA%\\hfss-agent`` on Windows,
            ``$XDG_STATE_HOME/hfss-agent`` elsewhere). Kept as an explicit
            parameter rather than always resolving the default, because tests
            must be able to point a whole composition at a tmp_path without
            monkeypatching the environment.

    Returns:
        A ``Composition``. Never raises for a well-formed adapter; the
        directory-creating path resolvers may raise ``OSError`` if the data
        directory cannot be created, which is a genuine startup failure and is
        not caught here.
    """
    resolved_data_dir = default_data_dir() if data_dir is None else data_dir

    session = Session(adapter)
    intent_store = IntentStore(default_intent_path(resolved_data_dir))

    # The three factories, in the order the tier-surface proof lists them. All
    # ten specs are safe tier; the registry validates every declared tier at
    # construction, so an invalid surface cannot exist to dispatch against.
    registry = CapabilityRegistry(
        session_routed_specs(session)
        + intent_capabilities(intent_store, session)
        + audit_capabilities(default_audit_log_path(resolved_data_dir))
    )

    broker = Broker(
        session=session,
        registry=registry,
        # audit_sink deliberately omitted: the broker builds the real
        # append-only writer at default_audit_log_path(data_dir) — the same
        # path audit_capabilities reads above, from the same data_dir.
        confirmer=RefuseAllConfirmer(),
        data_dir=resolved_data_dir,
    )

    return Composition(
        broker=broker,
        session=session,
        registry=registry,
        data_dir=resolved_data_dir,
    )
