"""Validation tool I/O (§3): validate_setup."""

from typing import Annotated

from pydantic import Discriminator, Tag

from hfss_agent.contract.common import StrictModel
from hfss_agent.contract.design_snapshot import NativeValidation
from hfss_agent.contract.finding import Finding
from hfss_agent.contract.provenance_record import NativeValidationProvenance
from hfss_agent.contract.tool_io.common import (
    CannotEvaluate,
    EngineStatus,
    SelectionRefused,
    result_kind,
)


class NativeValidationBlock(StrictModel):
    """HFSS's own ValidateDesign output plus the provenance of the run that
    produced it (ADR-23, W-6).

    A thin carrier, and thin on purpose. ``NativeValidation`` is reused
    UNMODIFIED — it is the same type ``DesignSnapshot.native_validation``
    carries and the same object the adapter returns, so the messages travel
    adapter → session → W-6 → response with no re-shaping step, and a
    transformation that does not exist cannot misrepresent anything. Hanging
    the provenance directly on ``NativeValidation`` was rejected for the
    opposite reason: it would push a tool-response concern into a snapshot
    sub-model the engine consumes, where the field would mean nothing.

    The pairing is STRUCTURAL rather than validated. A ``NativeValidation``
    with no provenance, or provenance with no validation, are both meaningless;
    as two sibling fields on the report they would both be constructible and
    would need a both-or-neither validator to prevent (the ``AuditRecord``
    pattern). Inside one carrier with two required fields, the broken state
    cannot be built at all.

    WHAT ``validation.raw_output`` ACTUALLY CONTAINS. It is HFSS's output AS
    SANITIZED AT THE CAPABILITY BOUNDARY (ADR-9, §6.6), not a byte-for-byte
    copy: control characters other than tab and newline are stripped, and each
    message is individually length-capped at
    ``adapter.sanitize.MAX_UNTRUSTED_STR_LEN`` with a visible truncation marker
    appended. Two consequences are stated here rather than left for a reader to
    discover — W-6 passes messages through without rephrasing, filtering,
    ranking, or judging them, and that is a strong and real guarantee, but it
    is not a claim of byte equality. Truncation is disclosed in-band, inside
    the affected string; control-character stripping leaves no trace at all,
    and there is deliberately NO structural signal for either (ADR-23: an
    honest signal is sanitization-wide, not native-specific, and its shape
    should not be designed before Phase 5.2 live validation shows what real
    ValidateDesign output looks like).

    The messages are untrusted, HFSS-sourced strings. Nothing may read inside
    them: parsing, splitting, classifying, or counting them is where passing
    output through stops and judging it begins, and ADR-9 forbids untrusted
    text steering control flow regardless. Note in particular that the
    truncation marker is NOT authenticatable — instruction-like text passes
    through unrewritten, so a message can contain the marker's exact wording —
    which is why no branch may key on it.
    """

    validation: NativeValidation
    provenance: NativeValidationProvenance


class ValidationReport(StrictModel):
    """validate_setup response (§3, W-6/W-10): the native block, then the
    wrapper's own findings, then the explicit engine-presence notice.

    ``native`` IS DECLARED FIRST, and the placement is the mechanism. Pydantic
    preserves declaration order in ``model_dump()`` and in JSON serialization,
    so "native always first" (spec Point 2) is a property of the emitted
    artifact rather than a sort every producer must remember to apply. The
    guarantee is honestly bounded: it fixes BLOCK ORDER in the serialized
    response; it cannot constrain how a downstream renderer chooses to display
    things.

    ``findings`` means GATE AND ENGINE findings ONLY (ADR-23). A native HFSS
    message is not a ``Finding`` and cannot be made into one: we own no rule
    id, no rule version, no calculation, and no machine-checked applicability
    behind it, so most of the seven-field evidence superset would have to be
    faked to carry one. Structural separation STATES that; a shared type
    discriminated by a ``source`` label would only have asserted it, and labels
    can be wrong. Because ``FindingSource`` no longer carries ``hfss_native``,
    the separation now holds at the type level — which is also what keeps
    W-10's seven-field receipt gate UNCONDITIONAL: there is no "native is
    exempt" branch to write, or to forget.

    ``engine_status`` is the explicit present/absent notice. With the engine
    absent, the native block and the wrapper's own findings are still returned
    alongside it — graceful degradation, never a silent gap.
    """

    native: NativeValidationBlock
    findings: list[Finding]
    engine_status: EngineStatus
    template_text: str


class ValidateSetupRequest(StrictModel):
    include_supplemental: bool = True


# Routed by the CALLABLE ``result_kind`` discriminator, like the three session
# result unions (see result_kind's docstring): ``ValidationReport`` is a
# success shape that must NOT grow an ``outcome`` field, so success stays
# untagged and the absence of the key IS the success signal. validate_setup's
# session gates can refuse before PyAEDT is reached — no usable session, and an
# incomplete selection (native validation needs a project and a design) — and
# the ordering tag is carried too so all four unions route one identical tag
# set, matching InspectDesignResult. Carrying a tag this tool cannot emit is
# deliberate and is NOT in tension with attach's refusal-free union: an "arm"
# there is a union MEMBER TYPE, and attach can emit no refusal at all, whereas
# validate_setup genuinely emits two of these three remedies.
ValidateSetupResult = Annotated[
    Annotated[ValidationReport, Tag("success")]
    | Annotated[CannotEvaluate, Tag("cannot_evaluate")]
    | Annotated[SelectionRefused, Tag("refused_no_session")]
    | Annotated[SelectionRefused, Tag("refused_selection_order")]
    | Annotated[SelectionRefused, Tag("refused_incomplete_selection")],
    Discriminator(result_kind),
]
