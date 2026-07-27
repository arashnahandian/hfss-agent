"""W-5 assembly — ordering, completeness, provenance, template, and the
dispatch-boundary failures that must never be reported as a PyAEDT limitation.

Drives the real ``Broker`` over the licence-free ``FakeAdapter`` (ADR-20
decision 1: a broker dispatch is W-5's only data path). Three properties carry
most of the weight here and each has its own section below: nothing requested is
ever silently dropped; no provenance value is ever fabricated; and a non-success
result from the session is passed back verbatim, unwrapped and unassembled.
"""

from __future__ import annotations

import pytest
from inspect_helpers import (
    AEDT_VERSION,
    ALL_SECTIONS,
    DESIGN,
    PROJECT,
    WRAPPER_VERSION,
    RaisingSink,
    canned_spec,
    detached_broker,
    scoped_broker,
    with_replacement,
    without_capability,
)

from hfss_agent.adapter.fake import OpBehavior, Scenario
from hfss_agent.adapter.results import AdapterCannotEvaluate, AdapterCrash
from hfss_agent.broker import Broker, NoAttachedSessionError, session_routed_specs
from hfss_agent.contract import CONTRACT_VERSION, InspectionSection
from hfss_agent.contract.tool_io import (
    CannotEvaluate,
    InspectionResult,
    SelectionRefused,
)
from hfss_agent.inspect import InspectionAssemblyError, inspect_design
from hfss_agent.inspect.assembler import (
    _CANONICAL_ORDER,
    _SYNTHESIZED_LIMITATION,
)
from hfss_agent.session.status import _LostCause


def _inspection_missing(*names: str) -> Scenario:
    """A scenario whose canned inspection OMITS ``names`` — the fake's
    ``_inspect`` filters a subset request against what it holds, so a section it
    does not hold simply never comes back. That is the adapter-omitted-a-section
    case W-5 must synthesize an entry for."""
    scenario = Scenario()
    scenario.inspection = {
        name: section
        for name, section in scenario.inspection.items()
        if name not in names
    }
    return scenario


# --- ordering and completeness ------------------------------------------------


def test_canonical_order_is_a_permutation_of_the_eight_section_names() -> None:
    # The pin ADR-20 decision 8 asks for: one ordering tuple that can neither
    # lose a section nor invent one. Checked against the independently written
    # list in the helpers, not against the contract Literal the constant is
    # derived from, so a mistake in one place cannot validate itself.
    assert set(_CANONICAL_ORDER) == ALL_SECTIONS
    assert len(_CANONICAL_ORDER) == len(ALL_SECTIONS) == 8


def test_build_order_puts_the_downstream_consumers_first() -> None:
    # Spec Point 8: ports, setups, sweeps, variables first.
    assert _CANONICAL_ORDER[:4] == (
        "excitations_ports",
        "setups",
        "sweeps",
        "variables",
    )


def test_full_read_out_returns_all_eight_sections_in_canonical_order() -> None:
    broker, _, _, _ = scoped_broker()
    result = inspect_design(broker)
    assert isinstance(result, InspectionResult)
    assert tuple(result.sections) == _CANONICAL_ORDER
    assert all(
        isinstance(section, InspectionSection) for section in result.sections.values()
    )
    assert result.sections["objects"].data == ["Patch", "Substrate", "GroundPlane"]


def test_subset_is_returned_in_canonical_order_not_request_order() -> None:
    broker, _, _, _ = scoped_broker()
    # Requested in an order that is BOTH non-canonical and non-alphabetical, so
    # a pass-through of the request order would be visible.
    result = inspect_design(broker, ["variables", "setups", "excitations_ports"])
    assert isinstance(result, InspectionResult)
    assert tuple(result.sections) == ("excitations_ports", "setups", "variables")


def test_two_callers_asking_differently_get_identical_output() -> None:
    broker, _, _, _ = scoped_broker()
    first = inspect_design(broker, ["sweeps", "objects"])
    second = inspect_design(broker, ["objects", "sweeps"])
    assert isinstance(first, InspectionResult)
    assert isinstance(second, InspectionResult)
    assert tuple(first.sections) == tuple(second.sections)
    assert first.template_text == second.template_text


def test_missing_requested_section_is_synthesized_not_dropped() -> None:
    broker, _, _, _ = scoped_broker(_inspection_missing("materials"))
    result = inspect_design(broker)
    assert isinstance(result, InspectionResult)
    # Present, in its canonical slot — not absent, and not appended at the end.
    assert tuple(result.sections) == _CANONICAL_ORDER
    synthesized = result.sections["materials"]
    assert synthesized.read_status == "not_readable"
    assert synthesized.data is None
    assert synthesized.limitation == _SYNTHESIZED_LIMITATION


def test_synthesized_limitation_claims_no_pyaedt_limitation() -> None:
    # The distinguishability ADR-20 decision 8 requires: an adapter-produced
    # limitation names what PyAEDT could not do; this one says the wrapper wrote
    # it and that the reason is unknown. It must not manufacture a solver excuse.
    lowered = _SYNTHESIZED_LIMITATION.lower()
    assert "synthesized by the wrapper" in lowered
    assert "w-5" in lowered
    assert "no pyaedt limitation was reported" in lowered


def test_a_missing_subset_section_is_still_accounted_for() -> None:
    broker, _, _, _ = scoped_broker(_inspection_missing("setups"))
    result = inspect_design(broker, ["setups", "sweeps"])
    assert isinstance(result, InspectionResult)
    assert tuple(result.sections) == ("setups", "sweeps")
    assert result.sections["setups"].read_status == "not_readable"
    assert result.sections["sweeps"].read_status == "ok"


def test_unknown_requested_section_is_rejected_before_the_read() -> None:
    broker, sink, _, _ = scoped_broker()
    with pytest.raises(InspectionAssemblyError) as caught:
        inspect_design(broker, ["variables", "nonexistent_section"])  # type: ignore[list-item]
    assert "nonexistent_section" in str(caught.value)
    # Rejected BEFORE anything was dispatched: no read ran, so nothing was
    # audited and no section was silently dropped from a result that shipped.
    assert sink.records == []


# --- provenance ---------------------------------------------------------------


def test_provenance_is_stamped_from_its_three_sources() -> None:
    broker, _, _, _ = scoped_broker()
    result = inspect_design(broker)
    assert isinstance(result, InspectionResult)
    provenance = result.provenance
    # Session chain -> what was read.
    assert provenance.project == PROJECT
    assert provenance.design == DESIGN
    # Attach-time Environment -> the versions the read ran under.
    assert provenance.read_under_aedt_version == AEDT_VERSION
    assert provenance.wrapper_version == WRAPPER_VERSION
    # The contract's own constant -> the schema that shaped the record.
    assert provenance.contract_version == CONTRACT_VERSION


def test_read_at_is_timezone_aware_utc() -> None:
    broker, _, _, _ = scoped_broker()
    result = inspect_design(broker)
    assert isinstance(result, InspectionResult)
    # AwareDatetime on the schema already rejects a naive value; this pins that
    # W-5 supplies UTC specifically, so "when was this read" is never ambiguous
    # by an offset.
    assert result.provenance.read_at.tzinfo is not None
    assert result.provenance.read_at.utcoffset().total_seconds() == 0


def test_session_ending_between_read_and_stamp_is_caught_and_chained() -> None:
    # The Option-4 sentinel. require_environment() is called LAST precisely so a
    # session that ended between the two calls is detected for free — the ended
    # session's fresh state carries no attach-time Environment.
    class _DiesAfterRead(Broker):
        def dispatch(self, name: str, arguments: dict[str, object] | None = None):
            result = super().dispatch(name, arguments)
            if name == "inspect_design":
                self._session._to_lost(_LostCause.CRASH)
            return result

    broker, _, _, _ = scoped_broker(broker_class=_DiesAfterRead)
    with pytest.raises(InspectionAssemblyError) as caught:
        inspect_design(broker)
    # Chained, not swallowed: the underlying cause stays inspectable.
    assert isinstance(caught.value.__cause__, NoAttachedSessionError)
    assert "session ended" in str(caught.value)


def test_selection_lost_between_read_and_stamp_is_caught() -> None:
    # The other half of "never fabricate": the session is still ATTACHED (so the
    # environment IS available), but its chain no longer names the project the
    # read ran against. There is no honest value to substitute.
    class _ResetsAfterRead(Broker):
        def dispatch(self, name: str, arguments: dict[str, object] | None = None):
            result = super().dispatch(name, arguments)
            if name == "inspect_design":
                self._session._reset_from("project", "the project was closed")
            return result

    broker, _, _, _ = scoped_broker(broker_class=_ResetsAfterRead)
    with pytest.raises(InspectionAssemblyError) as caught:
        inspect_design(broker)
    message = str(caught.value)
    assert "no longer names a project" in message
    assert "discarded" in message


def test_no_partial_result_escapes_when_provenance_cannot_be_stamped() -> None:
    # Stated as its own property: assembly failure DISCARDS the sections. A
    # read-out with an absent or guessed stamp is never the fallback.
    class _DiesAfterRead(Broker):
        def dispatch(self, name: str, arguments: dict[str, object] | None = None):
            result = super().dispatch(name, arguments)
            if name == "inspect_design":
                self._session._to_lost(_LostCause.CRASH)
            return result

    broker, _, _, _ = scoped_broker(broker_class=_DiesAfterRead)
    with pytest.raises(InspectionAssemblyError):
        inspect_design(broker)


# --- template_text ------------------------------------------------------------


def test_template_reports_counts_and_names_the_sections() -> None:
    broker, _, _, _ = scoped_broker()
    result = inspect_design(broker)
    assert isinstance(result, InspectionResult)
    text = result.template_text
    assert f'project "{PROJECT}"' in text
    assert f'design "{DESIGN}"' in text
    assert '8 section(s) requested, 8 with read_status "ok", 0 "not_readable".' in text
    assert '"excitations_ports"' in text


def test_template_names_the_not_readable_sections_separately() -> None:
    broker, _, _, _ = scoped_broker(_inspection_missing("materials", "boundaries"))
    result = inspect_design(broker)
    assert isinstance(result, InspectionResult)
    text = result.template_text
    assert '6 with read_status "ok", 2 "not_readable".' in text
    assert 'Not readable: "materials", "boundaries".' in text


def test_template_is_byte_deterministic_and_timestamp_free() -> None:
    broker, _, _, _ = scoped_broker()
    first = inspect_design(broker)
    second = inspect_design(broker)
    assert isinstance(first, InspectionResult)
    assert isinstance(second, InspectionResult)
    # Same read, rendered twice: identical bytes. The two calls have different
    # read_at values, so an echoed timestamp would break this.
    assert first.template_text == second.template_text
    assert str(first.provenance.read_at) not in first.template_text


@pytest.mark.parametrize(
    "omitted",
    [
        pytest.param((), id="all-sections-ok"),
        pytest.param(("materials",), id="mixed"),
        pytest.param(tuple(sorted(ALL_SECTIONS)), id="all-sections-not-readable"),
    ],
)
def test_template_makes_no_assessment_and_says_so(omitted: tuple[str, ...]) -> None:
    """The guardrail for "W-5 does not judge": the read-out states what was
    read and says outright that it assesses nothing.

    SWEPT ACROSS ALL THREE RENDERINGS. The mixed case is today's MAXIMAL text —
    both the "Read:" and "Not readable:" clauses fire there — so the other two
    close no present hole. They are here because this is a core-property
    guardrail and a later branch (a new clause, a differently-worded empty
    case) would otherwise ship unswept.

    TEST-FIXTURE CONSTRAINT, NOT A PRODUCT BUG — read this before "fixing" a
    spurious failure. The template renders the project and design names, which
    are UNTRUSTED HFSS-sourced strings. This assertion is safe only because the
    fixture uses the fake adapter's defaults ("patch_antenna" / "HFSSDesign1"),
    which contain no banned substring. A real design named "failsafe_v2" would
    trip this test, and that is the fixture's limitation, not W-5 overstepping:
    echoing a user's own design name back inside quotes as data is not a
    verdict. The fix in that case is a fixture whose names avoid the list —
    NEVER a shorter list. This guardrail may only ever move in one direction.
    """
    broker, _, _, _ = scoped_broker(_inspection_missing(*omitted))
    result = inspect_design(broker)
    assert isinstance(result, InspectionResult)
    text = result.template_text
    assert "makes no assessment of the design" in text
    # W-5 does not judge: no verdict vocabulary anywhere, in either direction.
    #
    # This list is the UNION of two independently derived lists — the approved
    # plan's §7 spec and the one written against the principle during build —
    # so its breadth is deliberate, not accumulated. The plan contributed the
    # canonical verdict words ("complete", "pass", "fail"); the build pass
    # contributed the ADVICE vocabulary ("should", "recommend"), a failure mode
    # §7 missed: a tool that says "you should increase mesh density" has
    # overstepped exactly as far as one that says "invalid".
    #
    # "only" is deliberately NOT banned, though §7 listed it. It is a scoping
    # adverb, and the disclaimer needs it to do the narrowing that makes it a
    # disclaimer ("This is a structural read-out only: ..."). Banning it would
    # forbid the sentence this very test asserts is present.
    #
    # Substring, not token, matching: "error" also catches "errors". The
    # over-breadth is intentional — a false positive fails loud and is cheap to
    # inspect, while a false negative is a judgment shipped in a read-out.
    lowered = text.lower()
    for word in (
        "valid",
        "invalid",
        "correct",
        "incorrect",
        "healthy",
        "complete",
        "pass",
        "fail",
        "problem",
        "issue",
        "error",
        "warning",
        "good",
        "bad",
        "should",
        "recommend",
    ):
        assert word not in lowered, (
            f"template_text carries verdict vocabulary {word!r}: {text}"
        )


# --- verbatim passthrough of the two non-success arms -------------------------


def test_selection_refused_passes_through_verbatim() -> None:
    broker, sink, _ = detached_broker()
    result = inspect_design(broker)
    assert isinstance(result, SelectionRefused)
    assert result.outcome == "refused_no_session"
    # Untouched: no wrapper text layered over the session's own wording.
    assert result.template_text.startswith("Cannot proceed: ")
    # And NO assembly happened — the status dispatch was never issued, so one
    # logical call produced exactly one audit record here, not two.
    assert [record.tool_name for record in sink.records] == ["inspect_design"]


def test_incomplete_selection_refusal_passes_through_verbatim() -> None:
    broker, _, session, _ = scoped_broker()
    session._reset_from("project", "the project was closed")
    result = inspect_design(broker)
    assert isinstance(result, SelectionRefused)
    assert result.outcome == "refused_incomplete_selection"


def test_any_refusal_tag_passes_through_untouched() -> None:
    # The third tag is unreachable through inspect's own gates (it is not a
    # selection stage), so it is driven through a canned handler: the point is
    # that the passthrough routes on TYPE, not on which remedy the tag names.
    refusal = SelectionRefused(
        outcome="refused_selection_order",
        reason="selection order",
        limitation="synthetic",
        template_text="Cannot proceed: synthetic",
    )
    broker, _, _, _ = scoped_broker(
        specs=with_replacement(canned_spec("inspect_design", refusal))
    )
    result = inspect_design(broker)
    assert result is refusal


def test_cannot_evaluate_passes_through_verbatim() -> None:
    scenario = Scenario(
        behavior={
            "inspect": OpBehavior(
                fault=AdapterCannotEvaluate(
                    reason="unreadable",
                    limitation="sections not exposed by pyaedt",
                )
            )
        }
    )
    broker, sink, _, _ = scoped_broker(scenario)
    result = inspect_design(broker)
    assert isinstance(result, CannotEvaluate)
    assert result.reason == "unreadable"
    assert result.limitation == "sections not exposed by pyaedt"
    assert (
        result.template_text
        == "Cannot evaluate via PyAEDT: sections not exposed by pyaedt"
    )
    assert [record.tool_name for record in sink.records] == ["inspect_design"]


def test_mid_read_fault_passes_its_cannot_evaluate_through() -> None:
    scenario = Scenario(
        behavior={"inspect": OpBehavior(fault=AdapterCrash(detail="died"))}
    )
    broker, _, _, _ = scoped_broker(scenario)
    result = inspect_design(broker)
    # The session's fault report reaches the caller unchanged — W-5 does not
    # re-word a failure it did not observe, and does not stamp provenance onto
    # a read that never completed.
    assert isinstance(result, CannotEvaluate)
    assert "inspection" in result.reason


# --- the dispatch boundary ----------------------------------------------------
#
# Every arm below must raise InspectionAssemblyError. None may be reported as a
# CannotEvaluate: none of them is PyAEDT declining to evaluate anything.


def test_unregistered_read_capability_raises() -> None:
    broker, _, _, _ = scoped_broker(specs=without_capability("inspect_design"))
    with pytest.raises(InspectionAssemblyError) as caught:
        inspect_design(broker)
    message = str(caught.value)
    assert "inspect_design" in message
    assert "no capability named" in message


def test_unregistered_status_capability_raises() -> None:
    broker, _, _, _ = scoped_broker(specs=without_capability("get_session_status"))
    with pytest.raises(InspectionAssemblyError) as caught:
        inspect_design(broker)
    message = str(caught.value)
    assert "get_session_status" in message
    assert "no capability named" in message


def test_refused_dispatch_raises_rather_than_reporting_a_limitation() -> None:
    # A synthetic medium tier under the Tier 1 refuse-all confirmer: the handler
    # never runs, so there is no read to report and no provenance to stamp.
    broker, _, _, _ = scoped_broker(
        specs=with_replacement(
            canned_spec("inspect_design", {}, tier="medium"),
        )
    )
    with pytest.raises(InspectionAssemblyError) as caught:
        inspect_design(broker)
    assert "refused at the medium-tier gate" in str(caught.value)


def test_audit_failure_raises_rather_than_reporting_an_unaudited_read() -> None:
    broker, _, _, _ = scoped_broker(sink=RaisingSink())
    with pytest.raises(InspectionAssemblyError) as caught:
        inspect_design(broker)
    assert "audit record could not be written" in str(caught.value)


def test_unexpected_read_type_raises() -> None:
    broker, _, _, _ = scoped_broker(
        specs=with_replacement(canned_spec("inspect_design", "not a section dict"))
    )
    with pytest.raises(InspectionAssemblyError) as caught:
        inspect_design(broker)
    assert "returned a str" in str(caught.value)


def test_wrong_typed_section_value_raises_rather_than_being_relabelled() -> None:
    broker, _, _, _ = scoped_broker(
        specs=with_replacement(
            canned_spec("inspect_design", {"variables": "not a section"})
        )
    )
    with pytest.raises(InspectionAssemblyError) as caught:
        inspect_design(broker)
    message = str(caught.value)
    assert "carried a str for section 'variables'" in message
    # Specifically NOT silently turned into a synthesized not_readable, which
    # would hide a wiring bug inside normal-looking output.
    assert _SYNTHESIZED_LIMITATION not in message


def test_unexpected_status_type_is_a_boundary_problem_not_a_wiring_bug() -> None:
    # The addition this suite exists to pin: an unexpected get_session_status
    # value must be reported as a dispatch-boundary problem, NOT allowed to fall
    # through to the project/design check and be blamed on the selection chain.
    broker, _, _, _ = scoped_broker(
        specs=with_replacement(canned_spec("get_session_status", "not a status"))
    )
    with pytest.raises(InspectionAssemblyError) as caught:
        inspect_design(broker)
    message = str(caught.value)
    assert "dispatching 'get_session_status'" in message
    assert "returned a str" in message
    assert "selection chain no longer names" not in message


def test_boundary_failures_are_never_reported_as_pyaedt_limitations() -> None:
    broker, _, _, _ = scoped_broker(specs=without_capability("inspect_design"))
    with pytest.raises(InspectionAssemblyError) as caught:
        inspect_design(broker)
    lowered = str(caught.value).lower()
    assert "cannot evaluate via pyaedt" not in lowered
    assert "not a pyaedt limitation" in lowered


# --- registration boundary ----------------------------------------------------


def test_successful_assembly_issues_exactly_two_dispatches() -> None:
    broker, sink, _, _ = scoped_broker()
    inspect_design(broker)
    # ADR-20 decision 4's acknowledged consequence, pinned so it stays a known
    # cost rather than drifting: one logical inspection, two audit records.
    assert [record.tool_name for record in sink.records] == [
        "inspect_design",
        "get_session_status",
    ]
    assert all(record.outcome == "ok" for record in sink.records)


def test_w5_is_not_itself_a_registered_capability() -> None:
    _, _, session, _ = scoped_broker()
    specs = session_routed_specs(session)
    assert {spec.name for spec in specs} == {
        "attach",
        "list_selection_options",
        "select",
        "get_session_status",
        "inspect_design",
        "validate_native",
    }
    # The capability NAMED inspect_design is the session read, not the W-5
    # assembler. Registering the assembler would put a second, differently
    # shaped inspect_design in the registry and audit an assembly step as a tool
    # call.
    assert all(spec.handler is not inspect_design for spec in specs)
    inspect_spec = next(spec for spec in specs if spec.name == "inspect_design")
    assert inspect_spec.handler == session.inspect
    assert inspect_spec.tier == "safe"
