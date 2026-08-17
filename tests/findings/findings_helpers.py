"""Shared fixtures for the W-10 receipt suite (Step 2.7, Part 1).

ACCEPTED-PATH INPUTS COME FROM THE REAL PIPELINE. ``accepted_gate_findings()``
drives ``assemble_snapshot`` and then ``evaluate_gates``, both imported from
``src``, so every finding the gate is asked to accept is one a caller could
genuinely hand it. No ``Finding`` is hand-built anywhere on that path -- a
hand-built one would prove the gate accepts a fixture, which is a different and
much weaker claim.

MALFORMED FIXTURES ARE HAND-BUILT, AND ONLY THERE. Below the accepted path, the
objects are constructed by ``model_construct``, by subclassing, or as plain
Python values, because in those tests the malformed object IS the subject rather
than a shortcut to one. The catalogue mirrors the ten input shapes this step's
Probe 4 measured, so the suite tests the shapes that were observed rather than
the ones that were imagined.

WHY THIS DUPLICATES A LITTLE OF ``tests/gating/gating_helpers``, stated because
the duplication is deliberate and a reader will otherwise read it as sloppiness.
``tests/findings`` sorts BEFORE ``tests/gating``, and the suite has no
``__init__.py``, so ``gating_helpers`` is not yet on ``sys.path`` when this module
is imported at collection time -- the same constraint ``gating_helpers`` itself
records about ``snapshot_helpers``. Importing it would make this suite pass or
fail on collection order, which is worse than a short builder. What is NOT
duplicated is anything from ``src``: the assembler, the gates and every contract
type are imported directly, so only the fixture VALUES live here.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import datetime, timezone

from hfss_agent.contract import (
    CONTRACT_VERSION,
    Applicability,
    ComplexSample,
    DesignSnapshot,
    Environment,
    Finding,
    FindingProvenance,
    FreshnessEvidence,
    InspectionProvenance,
    InspectionSection,
    IntentObject,
    NativeValidation,
    NativeValidationProvenance,
    Project,
    SolutionExists,
    SolveDataUnavailable,
    SolvedData,
    SolveState,
    Variation,
)
from hfss_agent.contract.tool_io import (
    InspectionResult,
    NativeValidationBlock,
    SelectionChain,
)
from hfss_agent.gating import evaluate_gates
from hfss_agent.snapshot import assemble_snapshot

PROJECT_NAME = "patch_antenna"
PROJECT_PATH = r"C:\Users\Owner\Documents\Ansoft\patch_antenna.aedt"
DESIGN = "HFSSDesign1"
SETUP = "Setup1"
SWEEP = "Sweep1"
TARGET_HZ = 2.4e9

_SECTIONS = (
    "variables",
    "objects",
    "materials",
    "boundaries",
    "excitations_ports",
    "setups",
    "sweeps",
    "available_results",
)


def _variation() -> Variation:
    return Variation(values={"w": "2mm"}, variation_hash="sha256:deadbeefcafef00d")


def _selection() -> SelectionChain:
    """A complete chain carrying the project's real path, so W-8's path drop is
    exercised rather than arranged away."""
    return SelectionChain(
        process_id=12345,
        project=Project(name=PROJECT_NAME, path=PROJECT_PATH),
        design=DESIGN,
        solution_type="DrivenModal",
        setup=SETUP,
        sweep=SWEEP,
        variation=_variation(),
    )


def _solve_state() -> SolveState:
    return SolveState(
        solution_exists=[
            SolutionExists(
                setup=SETUP, sweep=SWEEP, variation=_variation(), exists=True
            )
        ],
        adaptive_pass_history=[
            {"pass": 1, "delta_s": 0.05},
            {"pass": 2, "delta_s": 0.004},
        ],
        delta_s_progression=[0.05, 0.004],
        convergence_status="converged",
        solve_timestamps={
            f"{SETUP}:{SWEEP}": datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)
        },
        solver_messages=["Adaptive passes converged at pass 2."],
        # The REAL adapter's unconditional value, not the fake's, so the freshness
        # gate takes the arm every live design takes.
        freshness_evidence=FreshnessEvidence(available_signals={}, determinable=False),
    )


def _solved_data() -> SolvedData:
    return SolvedData(
        frequencies=[2.3e9, 2.4e9, 2.5e9],
        s_parameters={
            "S(1,1)": [
                ComplexSample(real=-0.10, imag=0.02),
                ComplexSample(real=-0.50, imag=0.10),
                ComplexSample(real=-0.20, imag=0.05),
            ]
        },
    )


def _inspection() -> InspectionResult:
    return InspectionResult(
        sections={  # type: ignore[arg-type]
            name: InspectionSection(data=[], read_status="ok") for name in _SECTIONS
        },
        provenance=InspectionProvenance(
            project=PROJECT_NAME,
            design=DESIGN,
            read_at=datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc),
            contract_version=CONTRACT_VERSION,
            wrapper_version="0.0.0",
            read_under_aedt_version="2026.1",
        ),
        template_text="read-out",
    )


def _native() -> NativeValidationBlock:
    return NativeValidationBlock(
        validation=NativeValidation(raw_output=[]),
        provenance=NativeValidationProvenance(
            project=PROJECT_NAME,
            design=DESIGN,
            validated_at=datetime(2026, 8, 3, 9, 30, tzinfo=timezone.utc),
            contract_version=CONTRACT_VERSION,
            wrapper_version="0.0.0",
            validated_under_aedt_version="2026.1",
        ),
    )


def snapshot() -> DesignSnapshot:
    """One snapshot through the REAL W-8 entry point."""
    return assemble_snapshot(
        inspection=_inspection(),
        native_validation=_native(),
        solve_state=_solve_state(),
        solved_data=_solved_data(),
        selection=_selection(),
        environment=Environment(
            aedt_version="2026.1",
            pyaedt_version="1.2.0",
            python_version="3.12.10",
            wrapper_version="0.0.0",
        ),
    )


def accepted_gate_findings() -> list[Finding]:
    """The four real gate findings, through the real assembler and real gates."""
    return evaluate_gates(snapshot(), TARGET_HZ)


# --- the calibration sweep ---------------------------------------------------
#
# EVERY SNAPSHOT SHAPE THE GATES CAN BE HANDED, so the evidence gate is calibrated
# against the whole space rather than one fixture. This is the Q6 recon sweep
# rebuilt here: a gate that rejects the wrapper's own output on some rare arm is
# exactly the defect a single-shape test cannot see.

_ABSENCE_REASONS = (
    "no_solution",
    "not_exposed_by_pyaedt",
    "not_found_in_design",
    "unrecognised_by_wrapper",
)


def _unavailable(reason: str) -> SolveDataUnavailable:
    return SolveDataUnavailable(
        reason=reason,  # type: ignore[arg-type]
        limitation=f"synthetic limitation for reason {reason}",
    )


def _solve_state_variants() -> dict[str, SolveState | SolveDataUnavailable]:
    base = _solve_state()
    variants: dict[str, SolveState | SolveDataUnavailable] = {
        "converged": base,
        "stopped": base.model_copy(update={"convergence_status": "stopped"}),
        "no-matching-entry": base.model_copy(update={"solution_exists": []}),
        "determinable": base.model_copy(
            update={
                "freshness_evidence": FreshnessEvidence(
                    available_signals={"design_modified_since_solve": False},
                    determinable=True,
                )
            }
        ),
        "no-history": base.model_copy(
            update={"adaptive_pass_history": [], "delta_s_progression": []}
        ),
    }
    variants.update({f"absent-{r}": _unavailable(r) for r in _ABSENCE_REASONS})
    return variants


def _solved_data_variants() -> dict[str, SolvedData | SolveDataUnavailable]:
    variants: dict[str, SolvedData | SolveDataUnavailable] = {
        "three-samples": _solved_data(),
        "one-sample": SolvedData(
            frequencies=[1e9],
            s_parameters={"S(1,1)": [ComplexSample(real=-0.1, imag=0.0)]},
        ),
        # A sweep that RAN and returned nothing -- distinct from an absent one,
        # and the shape that drives target_coverage's smallest evidence payload.
        "swept-empty": SolvedData(frequencies=[], s_parameters={}),
    }
    variants.update({f"absent-{r}": _unavailable(r) for r in _ABSENCE_REASONS})
    return variants


def _intent_variants() -> dict[str, IntentObject | None]:
    return {
        "none": None,
        "2.4GHz": IntentObject(
            target_frequency_hz=2.4e9, threshold_type="s11", threshold_value=-10.0
        ),
        "nan": IntentObject(
            target_frequency_hz=float("nan"),
            threshold_type="s11",
            threshold_value=-10.0,
        ),
    }


SWEEP_TARGETS = (None, 2.4e9, 9.9e9, float("nan"), float("inf"), 0.0)


def swept_gate_findings() -> Iterator[tuple[str, Finding]]:
    """Every gate finding the sweep can produce, labelled by the shape behind it.

    Yields ``(label, finding)`` so a calibration failure names the snapshot shape
    that produced the offending finding rather than only that one exists.
    """
    for solve_label, solve in _solve_state_variants().items():
        for data_label, data in _solved_data_variants().items():
            for intent_label, intent_value in _intent_variants().items():
                snap = assemble_snapshot(
                    inspection=_inspection(),
                    native_validation=_native(),
                    solve_state=solve,
                    solved_data=data,
                    selection=_selection(),
                    environment=Environment(
                        aedt_version="2026.1",
                        pyaedt_version="1.2.0",
                        python_version="3.12.10",
                        wrapper_version="0.0.0",
                    ),
                    intent=intent_value,
                )
                for target in SWEEP_TARGETS:
                    label = (
                        f"solve={solve_label} data={data_label} "
                        f"intent={intent_label} target={target}"
                    )
                    for finding in evaluate_gates(snap, target):
                        yield label, finding


# The empty value for each evidence field, by its declared shape. Used to empty
# ONE field at a time, so no single check can carry the others.
EMPTY_FOR: dict[str, object] = {
    "inspected": [],
    "observed_values": {},
    "calculation_ref": "",
    "reason_flagged": "",
    "rule_version": "",
    "limitations_and_assumptions": "",
}


# --- engine-shaped findings: valid in every field, built here because no engine
# --- exists to produce one. These are the CONTROL for the malformed fixtures:
# --- they must be accepted, or a rejection test proves nothing about rejection.


def _provenance() -> FindingProvenance:
    return FindingProvenance(
        project=PROJECT_NAME,
        design=DESIGN,
        solution_type="DrivenModal",
        setup=SETUP,
        sweep=SWEEP,
        variation=_variation(),
        snapshot_id="snap-engine-fixture",
        contract_version=CONTRACT_VERSION,
        wrapper_version="0.0.0",
        engine_version="e-1.0.0",
    )


def engine_finding_kwargs(**overrides: object) -> dict[str, object]:
    """The complete keyword set for a well-formed engine finding."""
    values: dict[str, object] = {
        "finding_id": "engine-rule-001",
        "source": "engine_rule",
        "rule_id": "engine.port_impedance",
        "rule_version": "1.0.0",
        "rule_purpose": "Checks the port reference impedance against the intent.",
        "inspected": ["inspection.excitations_ports"],
        "observed_values": {"port_count": 1},
        "calculation_ref": "engine.rules.port_impedance:evaluate",
        "reason_flagged": "The port reference impedance matches the intent.",
        "outcome": "pass",
        "classification": "judgment_call",
        "severity": "info",
        "limitations_and_assumptions": "Reads the snapshot only.",
        "applicability": Applicability(conditions={"has_ports": True}, held=True),
        "provenance": _provenance(),
        "template_text": "[engine] port_impedance: pass.",
    }
    values.update(overrides)
    return values


def engine_finding(**overrides: object) -> Finding:
    return Finding(**engine_finding_kwargs(**overrides))  # type: ignore[arg-type]


# --- the malformed catalogue, mirroring Probe 4's ten measured shapes ---------


class MethodOnlySubclass(Finding):
    """A subclass adding ONLY a method: identical fields, extra behaviour.

    The shape ``isinstance`` waves through. Its ``model_dump()`` is byte-identical
    to a plain ``Finding``'s, so the receipt gate NORMALIZES it rather than
    refusing it -- and the method must not survive that.
    """

    def render(self) -> str:
        return "SIDE EFFECT: engine-controlled code ran inside the wrapper"


class FieldAddingSubclass(Finding):
    """A subclass declaring an extra field, which ``extra="forbid"`` refuses."""

    confidence: float = 0.99


class ForeignFinding:
    """Not a ``Finding`` at all, and not a pydantic model either."""

    def __init__(self, finding_id: str = "foreign-1") -> None:
        self.finding_id = finding_id


class RaisingAccessor:
    """An object whose ``finding_id`` access raises something other than
    ``AttributeError``.

    ``getattr(x, name, default)`` returns the default ONLY for ``AttributeError``,
    so this propagates through a naive accessor. Measured in Probe 4's follow-up,
    not imagined.
    """

    @property
    def finding_id(self) -> str:
        raise RuntimeError("an engine object refused to be inspected")


class RaisingClassAttribute:
    """An object whose CLASS cannot be read -- the sibling of ``RaisingAccessor``,
    one attribute over, and the one that was missed.

    ``__class__`` is an ordinary attribute, and ``isinstance(x, Finding)``
    consults it when the exact type does not match. So the identical trick that
    made a raising ``finding_id`` propagate through ``getattr`` makes a raising
    ``__class__`` propagate through ``isinstance`` -- measured escaping
    ``validate_finding`` and ``merge_findings`` before either was guarded, past a
    docstring promising neither ever raises.

    Deliberately placed BESIDE ``RaisingAccessor`` rather than in a new section:
    the two are one shape (an attribute an object of unknown provenance defines
    as a raising property) reached through two different builtins, and a reader
    who understands one should meet the other immediately.
    """

    @property
    def __class__(self):  # type: ignore[override]
        raise RuntimeError("an engine object refused to report its class")


class SpoofsFinding:
    """``__class__`` RETURNS ``Finding``: passes ``isinstance`` while being
    nothing of the kind, and carries no ``model_dump`` at all.

    THE OTHER HALF OF THE SAME FACT AS ``RaisingClassAttribute``. That one shows
    ``__class__`` can RAISE; this one shows it can LIE -- it is an ordinary
    assignable attribute, and ``isinstance`` reads it. Passing the type check is
    therefore not proof of type, which is why both stage sentences say the object
    "presented itself as" a Finding rather than that it is one.

    Reaches STAGE 1: attribute lookup for ``model_dump`` does not go through
    ``__class__``, so it raises ``AttributeError`` and the reduction fails.
    """

    @property
    def __class__(self):  # type: ignore[override]
        return Finding


class SpoofsFindingAndDumpsHostile:
    """A spoof that REDUCES, so it reaches stage 2 rather than stage 1.

    MEASURED AS A SECOND ARM, not assumed to be the same one. A first reading of
    this defect found only the stage-1 sentence; this shape shows
    ``_UNVALIDATABLE_DETAIL`` carried the identical false claim, and it is why the
    repair touched two constants instead of one.
    """

    @property
    def __class__(self):  # type: ignore[override]
        return Finding

    def model_dump(self, **kwargs: object) -> Mapping:
        return _HostileMapping()


class SpoofsFindingAndDumpsValid:
    """A spoof whose reduction is a VALID payload -- and which is ACCEPTED.

    THE COMPANION THAT KEEPS THE FIX HONEST. The repair is to two sentences, not
    to the gate, and this is why: what establishes validity is stage 2's fresh
    ``model_validate``, which no ``__class__`` can spoof. An object that lies
    about its type and then produces a correct payload yields an exact
    ``Finding`` -- the type it claimed never mattered, the data it produced did.
    A test asserting "spoofs are refused" would be asserting something false.
    """

    @property
    def __class__(self):  # type: ignore[override]
        return Finding

    def model_dump(self, **kwargs: object) -> dict[str, object]:
        return Finding(**engine_finding_kwargs()).model_dump()  # type: ignore[arg-type]


# The two spoof shapes that are REFUSED, keyed by the stage each one reaches.
# Both must be refused with a detail that does not assert what was never checked.
CLASS_SPOOF_SHAPES: dict[str, object] = {
    "spoof reaching stage 1 (no model_dump)": SpoofsFinding(),
    "spoof reaching stage 2 (model_dump raises)": SpoofsFindingAndDumpsHostile(),
}


class _HostileMapping(Mapping):
    """A mapping that reduces fine as an object and explodes when READ.

    Not imagined: this is what makes ``Finding.model_validate`` raise a
    non-``ValidationError``, which is the only way to reach the receipt gate's
    second stage-specific refusal.
    """

    def __getitem__(self, key: object) -> object:
        raise RuntimeError("an engine payload refused to be read")

    def __iter__(self):  # type: ignore[no-untyped-def]
        raise RuntimeError("an engine payload refused to be iterated")

    def __len__(self) -> int:
        return 1


class DumpsButDoesNotValidate(Finding):
    """``model_dump()`` SUCCEEDS; validating what it returned raises.

    The shape that proved a single guard over both stages could report something
    false -- the object reduces cleanly, so any detail claiming it "could not be
    reduced to plain data" is a lie about it.
    """

    def model_dump(self, **kwargs: object) -> Mapping:  # type: ignore[override]
        return _HostileMapping()


class RaisesWhileDumping(Finding):
    """``model_dump()`` itself raises: a failure at the FIRST stage.

    The companion to the class above. Together they are the only way to show the
    two stage-specific details are attached to the stages they name.
    """

    def model_dump(self, **kwargs: object) -> dict[str, object]:  # type: ignore[override]
        raise RuntimeError("an engine override raised while reducing")


class DumpsAList(Finding):
    """``model_dump()`` returns a LIST: it reduces cleanly to something that is
    not a mapping at all.

    The shape that produces a validation error whose ``loc`` is EMPTY -- pydantic
    reports ``model_type`` about the payload as a whole, naming no field and no
    key. It is the arm on which counting empty locations as "undeclared keys"
    made ``_schema_detail`` assert that engine-authored key names were present
    when the payload contained no keys whatever.
    """

    def model_dump(self, **kwargs: object) -> list[object]:  # type: ignore[override]
        return ["not", "a", "mapping"]


class DumpsAString(Finding):
    """``model_dump()`` returns a STRING: the same empty-``loc`` arm, reached by
    a different reduction, so the fix is shown to be about the location and not
    about one container type."""

    def model_dump(self, **kwargs: object) -> str:  # type: ignore[override]
        return "not a mapping at all"


# The two reductions that are not mappings, keyed by what they return. Both land
# on ``schema_invalid`` with at least one empty-``loc`` problem.
NON_MAPPING_DUMP_SHAPES: dict[str, type[Finding]] = {
    "model_dump returns a list": DumpsAList,
    "model_dump returns a string": DumpsAString,
}


def ghost(**fields: object) -> Finding:
    """A ``Finding`` built by ``model_construct``: validation bypassed entirely.

    Passes ``isinstance(x, Finding)`` with required fields simply ABSENT --
    reading one raises ``AttributeError``. This is the shape a separately built
    wheel produces, and the reason a required-field check against a constructed
    object cannot fire.
    """
    return Finding.model_construct(**fields)


def ghost_missing(field: str) -> Finding:
    """A ghost missing EXACTLY ONE field, with the other sixteen present and
    correct.

    THE DONE BAR'S OWN WORDING NEEDED THIS AND NOTHING HAD IT. "A fixture finding
    missing any of the seven evidence fields" has two readings against a pydantic
    model -- present-but-empty, and genuinely ABSENT -- and only the first was
    covered. The catalogue's other ghosts are missing almost everything, so they
    cannot show which field's absence produced which refusal.

    Built from ``engine_finding_kwargs`` so the sixteen survivors are the same
    values the accepted-path fixture uses: whatever refusal comes back is
    attributable to the one removed field and to nothing else.
    """
    return Finding.model_construct(
        **{name: value for name, value in engine_finding_kwargs().items()
           if name != field}
    )


def free_text_field_names() -> set[str]:
    """The free-text fields on ``Finding``, DERIVED FROM THE MODEL.

    ONE DERIVATION, SHARED, because three tests need this set and three copies of
    a rule is how the count drifted in the first place. A field is free text when
    its declared type admits arbitrary producer prose: a bare ``str``, the
    optional ``str | None``, or a ``list[str]`` whose elements are prose just as
    much. The three ``str``-shaped fields that are closed ``Literal``s --
    ``source``, ``outcome``, ``classification`` -- are excluded, because the
    schema refuses anything but their members at construction and counting them
    would overstate the untrusted surface.

    ``inspected`` IS THE ONE THIS EXISTS FOR. It is the eleventh member, it is a
    ``list[str]``, and the two pipeline tests that swept "every str field" missed
    it for exactly that reason -- an ``isinstance(value, str)`` filter skips a
    list. Iterating this set instead makes the coverage structural.
    """
    names: set[str] = set()
    for name, spec in Finding.model_fields.items():
        annotation = str(spec.annotation)
        if "Literal" in annotation:
            continue
        if spec.annotation is str or annotation in ("str | None", "list[str]"):
            names.add(name)
    return names


def free_text_values(finding: Finding, name: str) -> list[str]:
    """Every producer-authored string carried by one free-text field.

    A ``list[str]`` yields its elements and a ``str | None`` holding ``None``
    yields nothing, so a caller can iterate uniformly without re-deciding the
    shape at each site -- which is the decision the two sweeps got wrong.
    """
    value = getattr(finding, name)
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


# The nine non-Finding / malformed inputs, keyed by the Probe 4 label they came
# from, so a failure names the measured shape rather than a fixture number.
NOT_A_FINDING_SHAPES: dict[str, object] = {
    "a plain dict carrying an id": {"finding_id": "dict-id", "severity": "info"},
    "a plain dict with no id": {"severity": "info"},
    "a bare string": "not a finding at all",
    "None": None,
    "a foreign object": ForeignFinding(),
    "an object whose accessor raises": RaisingAccessor(),
    "an object whose class cannot be read": RaisingClassAttribute(),
    "an int": 12345,
}

SCHEMA_INVALID_SHAPES: dict[str, object] = {
    "ghost: only finding_id": ghost(finding_id="ghost-known-id"),
    "ghost: only severity": ghost(severity="info"),
    "ghost: nothing set": ghost(),
    "ghost: finding_id is not a string": ghost(finding_id=12345),
    "ghost: finding_id is None": ghost(finding_id=None),
    "ghost: nested ghost provenance": ghost(
        finding_id="nested-ghost", provenance=FindingProvenance.model_construct()
    ),
    "ghost: wrong types throughout": ghost(
        finding_id=12345, inspected="not-a-list", provenance="nope"
    ),
}
