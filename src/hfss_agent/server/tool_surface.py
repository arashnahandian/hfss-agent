"""The seventeen §3 tool names, each accounted for (W-1, Step 2.8).

WHAT THIS FILE IS FOR. ADR-33 amended ADR-19's claim to: every tool the server
exposes is ACCOUNTED FOR IN THE TIER SYSTEM -- directly if it maps to a
capability, or transitively through a named assembler whose every inner dispatch
is a registered capability. "Accounted for" needs somewhere to be written down,
and this is it: one row per §3 name, each carrying its tier, how it reaches the
capability registry, and -- when it is not registered -- exactly what is missing.

THE THREE-HOP MAPPING (ADR-24 decision 2). A completeness test must be able to
follow tool -> assembler -> capability. Two rows show why one hop is not enough:

  * ``validate_setup`` (the §3 TOOL) is served by
    ``validate_native.assembler.validate_native`` (the ASSEMBLER), which
    dispatches the capability ``validate_native``. Three different things, and
    the tool name matches neither of the other two.
  * ``inspect_design`` is worse: ONE NAME MEANS THREE THINGS. The §3 tool, the
    W-5 assembler function, and the registered capability are all spelled
    ``inspect_design`` -- and the assembler is deliberately NOT the capability
    (``inspect/assembler.py`` says registering it "would put a second,
    differently-shaped ``inspect_design`` in the registry"). It also dispatches
    a SECOND capability, ``get_session_status``, to build its provenance stamp.
    A one-hop mapping keyed on name would silently conflate all three.

So ``inner_capabilities`` is a tuple, not a single name, and it is stated per
row rather than derived: deriving it would mean importing and introspecting an
assembler, and a test that computes the same thing the code computes proves
nothing about whether either is right.

THE DEFERRED ROWS ARE THE POINT OF THE FILE. SIX of the seventeen are deferred;
of those six, FIVE have nothing behind them at all and one (``validate_setup``)
names an assembler that exists and is missing only the composition on top.
Both numbers are stated because they answer different questions, and neither is
a number to trust from prose: ``DEFERRED_TOOLS`` at the foot of this file
derives the set from the rows, and
``test_registered_and_deferred_partition_the_surface`` pins the split at 11 and
6 against an independently written list of the seventeen §3 names. (This
paragraph said "Four" until Part 11, which matched neither count -- in the one
file whose job is making the deferrals reviewable.)

Recording them as "deferred, missing X" rather than omitting them is what lets a
test assert that X is STILL missing -- so the day someone builds X, that test
fails and forces this row to be updated, instead of the tool quietly never being
registered. A list of what IS registered cannot do that; only a list of
everything can.

TIERS ARE REQUIRED ON EVERY ROW, INCLUDING DEFERRED ONES, following
``CapabilitySpec.tier``'s structural trick: a required field with no default on
a frozen dataclass means a row without a tier is a ``TypeError`` at import, not
a discovery at registration time. The whole surface is safe tier (§6.1); a
deferred row still declares one, because the tier is a property of what the tool
DOES, which is known now, not of whether it happens to be built.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from hfss_agent.contract import RiskTier

ToolStatus = Literal["registered", "deferred"]


@dataclass(frozen=True)
class ToolBinding:
    """One §3 tool name and everything needed to account for it.

    Exactly one of two shapes is valid, enforced below rather than documented:

      * REGISTERED -- reaches the registry either directly (``capability``) or
        through an ``assembler`` whose ``inner_capabilities`` are all registered
        names. ``missing_piece`` must be None.
      * DEFERRED -- ``missing_piece`` names the specific absent thing, in words
        precise enough that a test can check for its arrival. Nothing about the
        mapping is guessed: a deferred row may still state its intended
        assembler and inner capabilities when those are known (``validate_setup``
        does), because that mapping is what makes the deferral reviewable.
    """

    name: str
    tier: RiskTier
    status: ToolStatus
    summary: str
    capability: str | None = None
    assembler: str | None = None
    inner_capabilities: tuple[str, ...] = ()
    missing_piece: str | None = None
    # An assembler that dispatches NOTHING. True for exactly one tool today
    # (``preflight_environment``), and it must be declared rather than inferred
    # from an empty tuple: "reaches no capability" and "nobody filled this in"
    # are different facts, and an empty default cannot tell them apart. Stating
    # it also makes the row's tier claim examinable -- a tool that reaches no
    # capability gets no tier check from the registry, so its safe tier rests on
    # this file alone, which a reader should be told rather than left to infer.
    reaches_no_capability: bool = False

    def __post_init__(self) -> None:
        if self.status == "deferred":
            if not self.missing_piece:
                raise ValueError(
                    f"tool {self.name!r} is deferred but names no missing piece. "
                    "A deferral nothing can check for is a deferral nobody will "
                    "notice becoming stale."
                )
            return
        if self.missing_piece:
            raise ValueError(
                f"tool {self.name!r} is registered but still names a missing "
                f"piece ({self.missing_piece!r}). One of the two is wrong."
            )
        if self.capability is None and self.assembler is None:
            raise ValueError(
                f"tool {self.name!r} is registered but reaches the capability "
                "registry by neither a direct capability nor a named assembler. "
                "ADR-33 requires one or the other."
            )
        if self.assembler is not None:
            if self.inner_capabilities and self.reaches_no_capability:
                raise ValueError(
                    f"tool {self.name!r} both names inner capabilities and "
                    "claims to reach none. One of the two is wrong."
                )
            if not self.inner_capabilities and not self.reaches_no_capability:
                raise ValueError(
                    f"tool {self.name!r} is served by assembler "
                    f"{self.assembler!r} but names no inner capabilities. The "
                    "transitive half of ADR-33 is exactly the claim that those "
                    "exist and are registered. If it genuinely dispatches "
                    "nothing, set reaches_no_capability=True and say so."
                )


# --- the seventeen, in System Design §3 order --------------------------------
#
# Every row is safe tier. That is not an assumption inherited from the registry:
# the tier proof iterates the REGISTRY, which holds capabilities, and this table
# holds TOOLS. The two are checked against each other by the Part 7 completeness
# test rather than by one trusting the other.
TOOL_SURFACE: tuple[ToolBinding, ...] = (
    ToolBinding(
        name="preflight_environment",
        tier="safe",
        status="registered",
        summary="Check this machine against the published support matrix.",
        assembler="hfss_agent.preflight.assembler.preflight_environment",
        # THE ONE TOOL THAT DISPATCHES NOTHING, declared rather than left as an
        # empty tuple. Preflight reads the machine through injected probes and,
        # when a session exists, the broker's ``require_environment`` accessor --
        # which is deliberately NOT a capability (broker.py's control-plane rule:
        # it is an immutable lifecycle read that triggers no external work). So
        # this tool's safe tier is asserted by this file and confirmed by no
        # registry entry, which is exactly why the flag is explicit.
        reaches_no_capability=True,
    ),
    ToolBinding(
        name="list_aedt_processes",
        tier="safe",
        status="deferred",
        summary="Enumerate running AEDT processes available to attach to.",
        missing_piece=(
            "no callable anywhere in src/: PyAEDT's active_sessions() yields "
            "{pid: port} only, which cannot fill AedtProcess.aedt_version or "
            "open_projects, so the adapter operation was deliberately not built"
        ),
    ),
    ToolBinding(
        name="attach",
        tier="safe",
        status="registered",
        # NAMES WHERE THE ARGUMENT COMES FROM, because nothing else does:
        # ``list_aedt_processes`` is deferred, so no tool on this surface can
        # enumerate process ids, and a client given only "attach to a process"
        # has no way to obtain one. Said here as well as in the live
        # instructions: a host may drop instructions, but a tool description
        # is what a model reads at the moment it chooses to call this.
        summary=(
            "Attach (attach-only) to a running AEDT process. This server "
            "cannot list process ids; obtain one from the operating system."
        ),
        capability="attach",
    ),
    ToolBinding(
        name="list_selection_options",
        tier="safe",
        status="registered",
        summary="List the choices for a selection stage.",
        capability="list_selection_options",
    ),
    ToolBinding(
        name="select",
        tier="safe",
        status="registered",
        summary="Select a project/design/setup/sweep/variation.",
        capability="select",
    ),
    ToolBinding(
        name="get_session_status",
        tier="safe",
        status="registered",
        summary="Report session health, selection chain, and suspect flag.",
        capability="get_session_status",
    ),
    ToolBinding(
        name="inspect_design",
        tier="safe",
        status="registered",
        summary="Read the structured design inspection sections.",
        # ONE NAME, THREE THINGS -- see the module docstring. The assembler is
        # NOT the capability, and it dispatches two of them.
        assembler="hfss_agent.inspect.assembler.inspect_design",
        inner_capabilities=("inspect_design", "get_session_status"),
    ),
    ToolBinding(
        name="validate_setup",
        tier="safe",
        status="deferred",
        summary="Run HFSS's own validation and pair it with the wrapper's findings.",
        # The mapping is KNOWN even though the tool is not built: W-6 exists and
        # produces the native block. What is missing is the composition on top.
        assembler="hfss_agent.validate_native.assembler.validate_native",
        inner_capabilities=("validate_native", "get_session_status"),
        missing_piece=(
            "nothing in src/ constructs a ValidationReport. Composing its four "
            "fields requires three judgments assigned to Step 3.3: whether "
            "include_supplemental can be honoured with no findings source, "
            "whether engine_status may be hardcoded 'absent' when nothing "
            "detects an engine, and what the whole-response template_text is "
            "(findings/render.py: the native paragraph, the findings paragraph "
            "and the engine notice, composed)"
        ),
    ),
    ToolBinding(
        name="check_solution_validity",
        tier="safe",
        status="deferred",
        summary="Run the four solution-validity gates and report each.",
        missing_piece=(
            "nothing in src/ constructs a SolutionValidityReport. gating."
            "evaluate_gates exists but needs a DesignSnapshot, and no snapshot "
            "acquisition path exists because Session exposes no solve-state "
            "read; gating/gates.py assigns the composition to Step 3.4"
        ),
    ),
    ToolBinding(
        name="compute_metrics",
        tier="safe",
        status="deferred",
        summary="Compute the Tier 1 S-parameter metric set for one variation.",
        missing_piece=(
            "metrics.compute_metrics exists and is complete, but Session "
            "exposes no read for SolvedData, SolveState or the gate findings it "
            "requires, so nothing above Layer 2 can obtain its inputs"
        ),
    ),
    ToolBinding(
        name="get_solve_health",
        tier="safe",
        status="deferred",
        summary="Report convergence history, delta-S progression, solver messages.",
        missing_piece=(
            "no assembler anywhere in src/: nothing constructs a "
            "SolveHealthReport, and Session exposes no solve-state read to "
            "build one from"
        ),
    ),
    ToolBinding(
        name="export_results",
        tier="safe",
        status="deferred",
        summary="Export the solved S-parameter data to Touchstone or CSV.",
        missing_piece=(
            "no export_results entry point in src/: metrics.touchstone_content "
            "and metrics.csv_content generate the payloads and Broker."
            "write_export performs the guarded write, but nothing composes them "
            "into an ExportResult, and Session exposes no SolvedData read"
        ),
    ),
    ToolBinding(
        name="set_design_intent",
        tier="safe",
        status="registered",
        summary="Persist the design intent, replacing any previous intent.",
        capability="set_design_intent",
    ),
    ToolBinding(
        name="get_design_intent",
        tier="safe",
        status="registered",
        summary="Read the persisted design intent and its set-time context.",
        capability="get_design_intent",
    ),
    ToolBinding(
        name="clear_design_intent",
        tier="safe",
        status="registered",
        summary="Clear the persisted design intent (tombstone write).",
        capability="clear_design_intent",
    ),
    ToolBinding(
        name="get_audit_log",
        tier="safe",
        status="registered",
        summary="Read the append-only audit log, optionally range-filtered.",
        capability="get_audit_log",
    ),
    ToolBinding(
        name="export_diagnostics_bundle",
        tier="safe",
        status="registered",
        summary="Write a redacted diagnostics bundle for support.",
        assembler="hfss_agent.preflight.bundle.export_diagnostics_bundle",
        # Dispatches get_audit_log to read the history, then writes through the
        # broker's guarded export primitive (which is not itself a capability).
        inner_capabilities=("get_audit_log",),
    ),
)

REGISTERED_TOOLS: tuple[str, ...] = tuple(
    binding.name for binding in TOOL_SURFACE if binding.status == "registered"
)
DEFERRED_TOOLS: tuple[str, ...] = tuple(
    binding.name for binding in TOOL_SURFACE if binding.status == "deferred"
)


def binding_for(name: str) -> ToolBinding | None:
    """The row for ``name``, or None. Used by the completeness tests."""
    for binding in TOOL_SURFACE:
        if binding.name == name:
            return binding
    return None
