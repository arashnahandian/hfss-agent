"""DesignSnapshot — the versioned wrapper->engine contract artifact (W-8).

Assembled by the snapshot module and handed to the (optional) closed engine.
Plain JSON-serializable data only — never live handles, sessions, paths, or
callables (W-8). The structure below follows System Design §2 field for field;
it is the public, auditable statement of exactly what the engine ever sees.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime

from hfss_agent.contract.common import (
    ConvergenceStatus,
    NativeValidationUnavailableReason,
    ReadStatus,
    SolveDataUnavailableReason,
    StrictModel,
    UntrustedStr,
    Variation,
)
from hfss_agent.contract.intent_object import IntentObject


class Environment(StrictModel):
    """Identity/environment block (§2 DesignSnapshot.environment)."""

    aedt_version: str
    pyaedt_version: str
    python_version: str
    wrapper_version: str


class Project(StrictModel):
    """The selected project — name plus path.

    ``name`` is an HFSS-sourced string and therefore untrusted; ``path`` is
    filesystem data the wrapper itself resolves.

    CARRIED BY ``SessionStatus.SelectionChain`` ONLY, as of ADR-28. The snapshot
    used to hold one of these too (§2 said "project (name+path)"); it now holds
    the bare name — see ``Selection.project`` for why. The path is not dead
    weight here: the session compares it to detect a project that moved between
    a read and a re-verification, and the audit log keeps it.
    """

    name: UntrustedStr
    path: str


class Selection(StrictModel):
    """The explicit selection chain captured in the snapshot (§2 selection).

    ``variation`` originates here — the one explicitly user-selected variation
    the Tier 1 UX computes for (§2; no silent "nominal"). §2 gave the variation
    key two standalone homes, this one and ``ProvenanceRecord``; ADR-30 added a
    third, ``FindingProvenance``, when a judgment turned out to need the key
    without any of the solve fields that surround it there. Everywhere else it
    travels via provenance.
    """

    process_id: int
    # THE PROJECT NAME, NOT A ``Project`` (ADR-28). §1.1 W-8 says a snapshot
    # carries "never live handles, sessions, paths, or callables", and §2's
    # "project (name+path)" put a filesystem path in the one block that crosses
    # into the engine. §1.1 is the safety line and wins; §2 was edited to match.
    # A default AEDT project path also carries the operator's Windows account
    # name, which nothing downstream of this field has any use for.
    #
    # ACCEPTED CONSEQUENCE, recorded rather than discovered later: two projects
    # with the same name in different directories are indistinguishable by this
    # field alone, so ADR-6's "diffing two snapshots answers what changed" role
    # cannot separate them. That is the intended trade — the session and the
    # audit log still hold the path, and the artifact that LEAVES is the one that
    # should not.
    project: UntrustedStr
    design: UntrustedStr
    solution_type: str
    setup: str
    sweep: str
    variation: Variation


class InspectionSection(StrictModel):
    """One inspection section (§2 inspection).

    Every section carries the same shape: its ``data``, a ``read_status``, and —
    when ``not_readable`` — the exact PyAEDT limitation named in ``limitation``.
    Where PyAEDT cannot read something, that is stated here rather than papered
    over.
    """

    data: Any
    read_status: ReadStatus
    limitation: str | None = None


class Inspection(StrictModel):
    """The full structured read-out (§2 inspection).

    Each of the eight sections carries the {data, read_status, limitation?}
    shape consistently, so a partially-readable design is represented honestly
    section by section rather than failing whole.
    """

    variables: InspectionSection
    objects: InspectionSection
    materials: InspectionSection
    boundaries: InspectionSection
    excitations_ports: InspectionSection
    setups: InspectionSection
    sweeps: InspectionSection
    available_results: InspectionSection


class NativeValidation(StrictModel):
    """Raw HFSS ValidateDesign output, attributed (§2 native_validation).

    The messages are untrusted HFSS-sourced strings; ``source`` is fixed so the
    passthrough is always attributable to HFSS itself and structurally separable
    from supplemental findings (spec Point 2).
    """

    raw_output: list[UntrustedStr]
    source: Literal["hfss_native"] = "hfss_native"


class FreshnessEvidence(StrictModel):
    """Freshness signals plus an explicit determinability flag (§2, ADR-4).

    ``determinable`` is what lets the freshness gate return
    "insufficient_evidence" honestly instead of guessing when PyAEDT does not
    expose enough to decide whether the design/variables/setup changed since the
    solve (§1.1 W-9). It is deliberately not collapsed into a plain freshness
    boolean.
    """

    # THERE IS NO KEY VOCABULARY HERE, and that absence is the fact worth
    # documenting rather than a gap in this comment. A reader who greps for a key
    # will find one and reasonably conclude it is the convention; it is not.
    #
    # THE TWO PRODUCERS DISAGREE IN KIND, not merely in which keys they choose:
    #
    #   * the REAL adapter emits ``available_signals={}`` with
    #     ``determinable=False``, unconditionally and with no branch above it
    #     (``adapter/real/real_adapter.py:575-577``). On real hardware this
    #     mapping is ALWAYS empty, so no key vocabulary exists in production at
    #     all. The comment directly above that call says why: PyAEDT exposes no
    #     reliable design-modified-since-solve signal, so we report nothing rather
    #     than guess (ADR-4).
    #   * the FAKE adapter emits ``{"design_modified_since_solve": False}`` with
    #     ``determinable=True`` (``adapter/fake/scenario.py:227-230``).
    #
    # So the one key name a reader can find is the fake's invention, naming the
    # exact signal the real adapter states it cannot obtain — an ASSERTED
    # DETERMINATION where the real path has no observation. Reading it as the
    # vocabulary would tell you this package has a design-modified signal, which
    # is the one thing ADR-4 recorded that it does not. The fake carries it so the
    # determinable=True branch of the freshness gate is reachable in tests, and
    # for no other reason.
    #
    # ``dict[str, Any]`` IS THEREFORE HONEST RATHER THAN LAZY: what signals a
    # future PyAEDT might expose is unknown, and fixing a key set now would be
    # inventing one. Consumers must treat this as evidence to render, keyed by
    # whatever the producer chose, and must never branch on a key name —
    # ``determinable`` is the field to branch on, which is why it is separate.
    available_signals: dict[str, Any]
    determinable: bool


class SolutionExists(StrictModel):
    """Whether a solution exists for one specific setup/sweep/variation
    combination (§2 solve_state: "solution-exists flags per
    setup/sweep/variation").

    Keyed per combination, not a single design-wide flag, because the first
    validity gate asks about the exact combination the user selected — the
    design as a whole having *some* solution is not the question.
    """

    setup: str
    sweep: str
    variation: Variation
    exists: bool


class SolveState(StrictModel):
    """Solve-state block (§2 solve_state).

    Carries enough convergence and freshness evidence for the gating module to
    decide validity without touching HFSS, and already holds the signals the
    Tier 2.1 failed-solve autopsy will extend (§7) — no field here is
    S-parameter-metric-specific.
    """

    solution_exists: list[SolutionExists]
    adaptive_pass_history: list[Any]
    delta_s_progression: list[float]
    convergence_status: ConvergenceStatus  # converged / stopped (§2)
    # KEY CONVENTION: ``f"{setup}:{sweep}"`` — the two names joined by a bare
    # colon, NO SURROUNDING SPACES. Both producers spell it that way:
    # ``adapter/real/real_adapter.py:569`` builds
    # ``{f"{selection.setup}:{selection.sweep}": timestamp}`` and
    # ``adapter/fake/scenario.py:223-225`` mints ``"Setup1:Sweep1"`` to match.
    #
    # DO NOT CONFUSE IT WITH PyAEDT'S SETUP-SWEEP NAME, which is spelled WITH
    # spaces — the same file builds ``f"{selection.setup} : {selection.sweep}"``
    # at ``real_adapter.py:634`` to hand to ``get_solution_data``. Two spellings
    # of one pair live in one module; only the un-spaced one is ever a key here,
    # and a consumer that reuses PyAEDT's spelling to look one up gets a miss
    # rather than an error.
    #
    # EXACTLY ONE ENTRY, always. The ``dict`` shape reads as "many setups", but
    # both producers emit a single pair — the one the session has SELECTED — so a
    # consumer must not treat a lookup miss as "that setup was never solved". The
    # variation is deliberately not in the key: a snapshot is scoped to one
    # variation already, carried on ``Selection.variation``.
    #
    # The VALUE is a plain ``datetime``, not ``AwareDatetime``, and the asymmetry
    # with ``DesignSnapshot.created_at`` is deliberate — see
    # ``tests/schemas/test_snapshot_created_at_is_aware.py``, which records that
    # tightening this one is re-queued to Phase 5.2 rather than guessed at,
    # because ``setup.get_profile()``'s shape is mock-only and unverified live.
    solve_timestamps: dict[str, datetime]
    solver_messages: list[UntrustedStr]  # surfaced as untrusted strings (§6.6)
    freshness_evidence: FreshnessEvidence


class ComplexSample(StrictModel):
    """One complex S-parameter value as JSON-serializable real/imag parts.

    Python ``complex`` is not JSON-serializable and the snapshot is plain data
    only (W-8), so complex S is carried as explicit ``real`` + ``imag``.
    """

    real: float
    imag: float


class SolvedData(StrictModel):
    """Raw S-parameter series scoped to the selection (§2 solved_data).

    These are the inputs W-7's open formulas consume. ``s_parameters`` maps each
    S-parameter name (e.g. "S(1,1)") to a complex series aligned index-for-index
    with ``frequencies``.
    """

    frequencies: list[float]
    s_parameters: dict[str, list[ComplexSample]]


class SolveDataUnavailable(StrictModel):
    """Why a snapshot carries no solve state, or no solved data (ADR-28).

    The absence arm of ``DesignSnapshot.solve_state`` and ``.solved_data``. It
    exists because ``ConvergenceStatus`` has two members and neither is true of
    a design that was never run: before this type, the only constructible
    snapshot for an unsolved design asserted ``convergence_status="stopped"``
    for a solve that never started, which is a fabricated value in a required
    field.

    SHAPED AFTER ``InspectionSection``, deliberately — a machine-checkable
    status beside the exact limitation named. That is this package's existing
    answer to "something could not be read", and a second convention for the
    same job would only invite a reader to wonder which one means more.

    ``limitation`` IS REQUIRED, where ``InspectionSection.limitation`` is
    optional, and the difference is not an inconsistency. That field is optional
    because its ``read_status="ok"`` case legitimately has nothing to explain;
    this type exists ONLY in the absent case, and every refusal behind it
    carries a limitation string from the adapter. Declaring it optional would
    advertise a state — a reason with no explanation — that no producer can
    produce.

    ``limitation`` IS A WRAPPER-AUTHORED TEMPLATE THAT CAN INTERPOLATE AN
    AEDT-SOURCED VALUE. Three of the refusals behind these reasons splice in
    something read from the design — the setup name ("setup not found"), the
    setup:sweep pair ("no solved data") and the sweep's unit token ("unknown
    frequency unit"). Typed plain ``str``, following the four sites that already
    made this call the same way (``InspectionSection.limitation``,
    ``CannotEvaluate.limitation``, ``SelectionRefused.limitation``,
    ``AdapterCannotEvaluate.limitation``) rather than inventing a third
    convention for one field. The interpolated values are not raw: every string
    an adapter operation returns is control-character-stripped and length-capped
    by ``sanitize_result`` at the capability boundary (ADR-9), including the
    fields of the outcome dataclasses. Render it as data, never in an
    instruction position (§6.6).
    """

    reason: SolveDataUnavailableReason
    limitation: str


class NativeValidationUnavailable(StrictModel):
    """Why a snapshot carries no native-validation output (ADR-28).

    ABSENCE IS NOT AN EMPTY ``NativeValidation``, and that distinction is the
    whole reason this type exists. A ``raw_output=[]`` is a validator that RAN
    and reported nothing — a completed run, and a success. The adapter refuses
    the conflation in as many words at the refusal site: "it is not the same as
    a validator that ran and reported nothing." Before this arm, a snapshot had
    nowhere to put "the validator could not be run" except that empty list, and
    conflating the two is the misread ADR-23 most guards against. Now the
    difference is structural rather than a convention someone has to remember.

    A SEPARATE TYPE FROM ``SolveDataUnavailable``, sharing no base class, and
    the separation is load-bearing rather than stylistic. One shared reason
    vocabulary would let this field carry ``no_solution``,
    ``not_found_in_design`` or ``unrecognised_by_wrapper`` — three states that
    mean nothing for a design-level validation run that reads no setup, needs no
    solution and normalises no units. Three nonsense states the type would
    permit is three too many, and the fix is two vocabularies, not a validator
    policing one.

    THE SHARED SPELLING OF ``not_exposed_by_pyaedt`` IS A COINCIDENCE OF
    WORDING, NOT A KINSHIP. Nothing may come to depend on the two reason sets
    staying aligned; a member added to one is not a member of the other. This is
    the same independence ADR-23 fixed between the provenance types — three of
    them then, four since ADR-30 — for the same reason.

    ``limitation`` is required and carries the same typing note as
    ``SolveDataUnavailable.limitation``; the one refusal behind this type
    interpolates nothing, but the field is typed for the convention rather than
    for today's single producer.
    """

    reason: NativeValidationUnavailableReason
    limitation: str


class DesignSnapshot(StrictModel):
    """The versioned design snapshot (W-8) — ``contract_version`` carries the
    semver-tagged schema version (``common.CONTRACT_VERSION``).

    See System Design §2. ``intent`` is the only optional top-level block: a
    snapshot is valid whether or not the user has set a design intent.

    THREE FIELDS CARRY AN ABSENCE ARM, AND ``inspection`` DELIBERATELY DOES NOT
    (ADR-28). The three below can each be absent while the snapshot as a whole
    is still honest and worth emitting — a design that was never solved is the
    ordinary case. ``inspection`` cannot: every whole-read failure it has is
    either a session fault or a session/adapter state divergence, and under
    either the snapshot itself is not trustworthy, so W-8 refuses to build one
    rather than emitting a partial artifact. Its PARTIAL failures need no arm at
    all — each of the eight sections already carries its own ``read_status`` and
    ``limitation``, which is a finer-grained honesty than an arm could give.

    ``SelectionRefused`` HAS NO REPRESENTATION HERE, for a reason worth stating
    so nobody adds one: a refusal means a selection stage was missing, and
    ``Selection`` requires all seven stages — so a snapshot with a refused
    selection is not a lesser snapshot, it is no snapshot. W-8 raises.

    The two arms of each union are told apart by their disjoint field sets under
    ``extra="forbid"``; no discriminator field is needed, and adding one would
    mean changing ``SolveState``/``SolvedData``, which this amendment does not
    touch.
    """

    contract_version: str
    # AwareDatetime, not datetime: a naive value is REJECTED rather than
    # silently read as local time, so "when was this captured" is never
    # ambiguous by an offset. This matches ``InspectionProvenance.read_at`` and
    # ``NativeValidationProvenance.validated_at``, which each carry the same
    # note; ``created_at`` predates both and was the last plain ``datetime``
    # among them. Tightening it costs nothing: W-8 is its only producer and
    # mints it in UTC.
    created_at: AwareDatetime
    snapshot_id: str
    environment: Environment
    selection: Selection
    inspection: Inspection
    native_validation: NativeValidation | NativeValidationUnavailable
    solve_state: SolveState | SolveDataUnavailable
    solved_data: SolvedData | SolveDataUnavailable
    intent: IntentObject | None = None
