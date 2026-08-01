"""Preflight & session tool I/O (§3): preflight_environment, list_aedt_processes,
attach, list_selection_options, select, get_session_status.

preflight_environment and list_aedt_processes do not reach PyAEDT through the
adapter the way the session tools do, so — per the cannot_evaluate narrowing
logged for this step — their responses have no CannotEvaluate arm:
incompatibilities and an empty process list are ordinary data in the report,
not a cannot_evaluate. attach / select / get_session_status share one
SessionStatus schema.

THE ABSENT CannotEvaluate ARM IS WHY ``PreflightEnvironment`` EXISTS. Because
preflight_environment has no cannot_evaluate arm and no refusal arm, its ONLY
representable outcome is a ``PreflightReport`` — so every state the tool can
legitimately be in has to be expressible inside that one type. Journey 1.0 runs
BEFORE any attach, and the §2 ``Environment`` requires four version strings that
only an attached session supplies, so a report built pre-attach could not be
constructed at all without either fabricating a version or inventing an arm the
contract does not have. ``PreflightEnvironment`` is the parallel type that makes
the honest pre-attach state representable; see its docstring for why two of its
four fields are optional and two are not.
"""

from typing import Annotated, Literal

from pydantic import Discriminator, Tag, model_validator

from hfss_agent.contract.common import StrictModel, UntrustedStr, Variation
from hfss_agent.contract.design_snapshot import Project
from hfss_agent.contract.tool_io.common import (
    CannotEvaluate,
    SelectionRefused,
    SelectionStage,
    result_kind,
)

# --- preflight_environment ---------------------------------------------------


class PreflightEnvironment(StrictModel):
    """The version-identity block as preflight can honestly report it (W-11).

    A PARALLEL to ``DesignSnapshot.Environment``, never a loosening of it —
    exactly as ``SelectionChain`` below parallels ``DesignSnapshot.Selection``
    rather than making its stages optional (ADR-16 decision 3, and its
    explicitly rejected alternative (d)). ``Environment`` describes an ATTACHED
    session: all four versions were read from a live process, so all four are
    required, and the adapter, session, broker and both Layer-4 assemblers all
    depend on that. Preflight's whole purpose is to run BEFORE that, so it
    cannot supply what only attaching supplies.

    Two fields are optional and two are not. The split is reality's, not a
    convenience:

      * ``aedt_version`` is None when no AEDT installation root is present, and
        when SEVERAL are — a machine with two installs cannot say which one an
        attach would bind to, because PyAEDT resolves that by matching the
        target process against each installed version in turn. A single install
        is unambiguous and is reported even when it is unsupported.
      * ``pyaedt_version`` is None when the ``live`` extra is not installed.
        Not hypothetical: public CI runs ``uv sync`` WITHOUT that extra on both
        OS legs, so a required field here would be unconstructible in the very
        environment this report exists to describe.
      * ``python_version`` is always determinable — ``platform.python_version()``
        formats ``sys.version_info`` and cannot fail.
      * ``wrapper_version`` is always determinable: this code is running. Where
        the installed distribution's metadata is absent or unreadable, the
        established ``"0.0.0"`` fallback applies.

    OPTIONALISING NO MORE THAN REALITY REQUIRES IS THE POINT. A permanently-
    nullable field advertises a capability that cannot exist — the shape ADR-21
    gap 1 dropped two ``AedtProcess`` fields to avoid, and the shape ADR-22
    decision 4 refused to add to ``SessionStatus``. Two of these four fields
    have a real absent state; the other two do not, and do not get one.
    """

    aedt_version: str | None = None
    aedt_version_source: Literal["attached_session", "installed_scan"] | None = None
    pyaedt_version: str | None = None
    python_version: str
    wrapper_version: str

    @model_validator(mode="after")
    def _version_and_source_are_both_or_neither(self) -> "PreflightEnvironment":
        """A version claim always names where it came from, and a source never
        stands without a version.

        BOTH DIRECTIONS, for the reason ``AuditRecord`` enforces its own pair
        both ways: either half alone lets the report misstate what happened. A
        version with no source is an unattributed claim the consumer cannot
        weigh; a source with no version names the provenance of nothing.

        WHY THE SOURCE IS A TYPED FIELD AND NOT PROSE IN A ``detail`` STRING.
        The two sources are different claims, not two phrasings of one:
        ``attached_session`` is the version of the process we are talking to,
        read at attach; ``installed_scan`` is an inference about which process
        an attach MIGHT bind to, and that inference can be wrong whenever more
        than one version is installed. A consumer deciding whether to warn has
        to branch on that difference, and this repo structures provenance
        rather than narrating it (ADR-18 decision 13(b): typed so a consumer
        can branch "instead of string-matching the prose").
        """
        if (self.aedt_version is None) != (self.aedt_version_source is None):
            raise ValueError(
                "aedt_version and aedt_version_source must both be present or "
                f"both be absent; got version={self.aedt_version!r}, "
                f"source={self.aedt_version_source!r}. An AEDT version claim "
                "must always say whether it was read from an attached session "
                "or inferred from installed-version environment variables — "
                "the two are different claims and must not be confused."
            )
        return self


class ComponentCheck(StrictModel):
    """One component checked against the published support matrix (W-11).

    ``detected`` is None when the component is not present/detectable (e.g. no
    AEDT install found); the verdict then lives in ``status``.
    """

    component: str  # e.g. "aedt", "pyaedt", "python", "grpc", "license"
    detected: str | None
    required: str  # support-matrix requirement, in plain language
    status: Literal["ok", "incompatible", "unavailable"]
    detail: str


class PreflightReport(StrictModel):
    """Journey 1.0 environment health vs. the published support matrix (§3, W-11).

    Genuinely new — no §2 schema expresses a compatibility verdict — and it
    carries ``PreflightEnvironment`` for the version-identity block.

    IT USED TO CARRY THE §2 ``Environment`` AND COULD NOT BE BUILT. That is
    recorded here rather than quietly replaced, because the reason is the whole
    justification for the parallel type: ``Environment``'s four version strings
    all come from an attached session, preflight runs before any attach, and
    this response has no cannot_evaluate arm to fall back on — so a pre-attach
    report was unconstructible without fabricating a version. Restoring
    ``Environment`` here would re-create that dead end.
    """

    environment: PreflightEnvironment
    checks: list[ComponentCheck]
    support_matrix_ref: str
    overall: Literal["ok", "incompatible"]
    template_text: str


# --- list_aedt_processes -----------------------------------------------------


class AedtProcess(StrictModel):
    """One running AEDT process a user can attach to via ``attach(process_id)``.

    Process discovery is deferred to a future step — it is not W-2 in the MVP
    (ADR-18 decision 1), so this schema has no producer today. It carries only
    what a read-only listing can honestly supply.
    """

    process_id: int
    grpc_port: int | None = None


class AedtProcessList(StrictModel):
    """The running-AEDT-process listing (§3). New: no §2 schema describes a
    process (Selection carries only a bare ``process_id`` int)."""

    processes: list[AedtProcess]
    template_text: str


# --- attach / select / get_session_status (one shared status schema) ---------


class SelectionChain(StrictModel):
    """The selection chain as a *partial* state (§3 "selection chain").

    Cannot reuse DesignSnapshot.Selection: that schema requires every stage (a
    complete, solved selection). The chain is built stage by stage and reset
    downstream on any change (W-2), so every stage here is optional — a
    freshly-attached session has only ``process_id``. Reuses Project and
    Variation for the two stages that carry structured data.
    """

    process_id: int | None = None
    project: Project | None = None
    design: UntrustedStr | None = None
    solution_type: str | None = None
    setup: str | None = None
    sweep: str | None = None
    variation: Variation | None = None


class SessionStatus(StrictModel):
    """Session health + selection chain + suspect flag (§3): the shared response
    of attach, select, and get_session_status.

    ``suspect`` is the §6.7 flag raised after an abandoned stuck call. It is a
    distinct boolean (not folded into ``connection_health``) because §3 lists it
    separately and it drives distinct behaviour — the next op forces
    reconnect-and-verify.

    ``lost_cause`` is None unless the session is LOST; when LOST it names the
    recovery action, so a consumer can branch on it instead of string-matching
    the prose (ADR-18 decision 13(b); the ADR-16 decision 4 principle):

      * ``crash`` — the process exited: relaunch AEDT and attach a NEW pid;
      * ``disconnect`` — the link dropped, the process may still live: re-attach
        the SAME pid;
      * ``unverifiable`` — lost for a non-transport reason, where neither crash
        nor disconnect can be honestly claimed: re-attach to continue.

    ``connection_health`` stays the binary reachability signal (crash, disconnect
    and unverifiable all flatten to ``disconnected`` there — ADR-17 decision 3);
    this field is the WHY when disconnected, and nothing more. It deliberately
    does NOT distinguish detached-from-lost: a never-attached session has no
    cause to name, so it reports None like every other non-LOST state.
    """

    connection_health: Literal["connected", "disconnected"]
    suspect: bool
    lost_cause: Literal["crash", "disconnect", "unverifiable"] | None = None
    selection: SelectionChain
    template_text: str


# --- list_selection_options --------------------------------------------------


class SelectionOption(StrictModel):
    """One choice for the next unselected stage (§3).

    ``value`` is the token passed back to select(); ``display`` is the
    HFSS-sourced label (untrusted) for name-bearing stages; ``variation`` is
    populated only for the variation stage, reusing the Variation key.
    """

    value: str
    display: UntrustedStr | None = None
    variation: Variation | None = None


class SelectionOptions(StrictModel):
    """Options for the next unselected stage (§3). New: the §2 schemas have no
    "choices for a stage" concept."""

    stage: SelectionStage
    options: list[SelectionOption]
    template_text: str


# --- requests ----------------------------------------------------------------


class AttachRequest(StrictModel):
    process_id: int


class ListSelectionOptionsRequest(StrictModel):
    stage: SelectionStage


class SelectRequest(StrictModel):
    stage: SelectionStage
    choice: str


# --- response unions ---------------------------------------------------------
# preflight_environment -> PreflightReport and list_aedt_processes ->
# AedtProcessList have NO CannotEvaluate arm (see module docstring).

# attach has NO SelectionRefused arm, and that is a verified property of the
# implementation, not an oversight: ``Session.attach`` runs no session gate — it
# IS the operation that establishes a session, so "no usable session" cannot
# apply, and it takes no selection stage, so neither ordering nor selection
# completeness can apply. Its only non-success outcomes are a faulted attach
# (reported as a DETACHED SessionStatus) and a faithfully-mapped adapter
# cannot_evaluate. Giving it a refusal arm would advertise a state no producer
# can emit.
AttachResult = SessionStatus | CannotEvaluate

# select / list_selection_options route through the CALLABLE ``result_kind``
# discriminator rather than a declared ``Field(discriminator="outcome")`` (see
# result_kind's docstring): SessionStatus and SelectionOptions are shared across
# other unions, so they must NOT grow an ``outcome`` field. Success payloads stay
# untagged; every refusal and the cannot_evaluate arm are routed by their tag.
# SelectionRefused appears once per remedy tag — the arms are the same type, kept
# apart so an unknown outcome cannot slip in under a broad tag.
ListSelectionOptionsResult = Annotated[
    Annotated[SelectionOptions, Tag("success")]
    | Annotated[CannotEvaluate, Tag("cannot_evaluate")]
    | Annotated[SelectionRefused, Tag("refused_no_session")]
    | Annotated[SelectionRefused, Tag("refused_selection_order")]
    | Annotated[SelectionRefused, Tag("refused_incomplete_selection")],
    Discriminator(result_kind),
]
SelectResult = Annotated[
    Annotated[SessionStatus, Tag("success")]
    | Annotated[CannotEvaluate, Tag("cannot_evaluate")]
    | Annotated[SelectionRefused, Tag("refused_no_session")]
    | Annotated[SelectionRefused, Tag("refused_selection_order")]
    | Annotated[SelectionRefused, Tag("refused_incomplete_selection")],
    Discriminator(result_kind),
]
