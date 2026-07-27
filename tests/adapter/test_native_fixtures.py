"""The six native-validation fixture cases (Step 2.2b; ADR-23's fixture ledger).

Every case is driven through the REAL public path —
``FakeAdapter(scenario).validate_native()`` — never by reading a fixture object
directly. That path runs the ``Adapter`` ABC's ``_run`` template, so the watchdog
and, more to the point here, ADR-9's sanitizer apply exactly as they do in
production. Asserting on a fixture alone would prove only that the fixture says
what it says; asserting on what comes back OUT of the capability boundary proves
what a caller actually receives.

Five cases are canned DATA (the ``scenario.py`` factories). The sixth is a FAULT,
injected through the same per-operation mechanism every other adapter op uses —
no native-specific injection path exists or is needed.
"""

from __future__ import annotations

from hfss_agent.adapter.fake import FakeAdapter, OpBehavior, Scenario
from hfss_agent.adapter.fake.scenario import (
    _empty_native_validation,
    _hostile_native_validation,
    _mixed_severity_native_validation,
    _multi_message_native_validation,
    _over_length_native_validation,
)
from hfss_agent.adapter.results import (
    AdapterCannotEvaluate,
    AdapterResult,
    SessionFault,
)
from hfss_agent.adapter.sanitize import MAX_UNTRUSTED_STR_LEN
from hfss_agent.contract import NativeValidation


def _validate(native: NativeValidation) -> AdapterResult[NativeValidation]:
    """Drive one canned native fixture through the fake adapter's public path.

    The scenario is built and then MUTATED rather than passed as a constructor
    kwarg, matching how the other suites override a single canned-data axis
    (``Scenario`` is a plain dataclass, not frozen) — everything else stays at
    its default so nothing but the native shape varies between these tests.
    """
    scenario = Scenario()
    scenario.native_validation = native
    return FakeAdapter(scenario).validate_native()


def test_empty_output_is_a_successful_validation_not_a_failure() -> None:
    """An empty ``raw_output`` means the validator RAN and reported nothing.

    It is a success arm, and it must never be conflated with "the validator
    could not be run" — that is an ``AdapterCannotEvaluate``, a different fact
    about a different thing. A caller that cannot tell the two apart cannot
    report either one honestly, which is why this shape is pinned on its own.
    """
    result = _validate(_empty_native_validation())
    assert isinstance(result, NativeValidation)
    assert result.raw_output == []
    assert not isinstance(result, AdapterCannotEvaluate)
    # The attribution survives an empty run: it is still HFSS's own output.
    assert result.source == "hfss_native"


def test_multi_message_output_preserves_order_and_count() -> None:
    fixture = _multi_message_native_validation()
    result = _validate(fixture)
    assert isinstance(result, NativeValidation)
    # Equality over the list covers both properties at once: same strings in the
    # same positions, so nothing was dropped, added, or moved.
    assert result.raw_output == fixture.raw_output
    assert len(result.raw_output) == len(fixture.raw_output)
    assert len(result.raw_output) > 1  # genuinely multi, not a one-element list


def test_mixed_severity_messages_pass_through_unranked() -> None:
    """This test deliberately makes NO claim about severity.

    Reading inside a native message — parsing it, classifying it, ranking it,
    counting errors or warnings — is where passing output through stops and
    judging it begins. We own no rule, no rule version, and no severity axis
    behind an Ansys validator message, so the only property there is to assert
    is that the list arrives exactly as it left.

    The fixture is deliberately not in severity order, so a sort applied
    anywhere on the path would surface here as a reordering rather than passing
    unnoticed.
    """
    fixture = _mixed_severity_native_validation()
    result = _validate(fixture)
    assert isinstance(result, NativeValidation)
    assert result.raw_output == fixture.raw_output


def test_over_length_message_is_capped_and_visibly_marked() -> None:
    """The sanitizer's cap, exercised on the native path.

    ``<=``, never ``==``: ``sanitize_str`` reserves marker room using the
    LARGEST possible omitted-count, so the actual marker is never longer than
    what was reserved and the result lands at or under the cap rather than
    exactly on it.

    Asserting the truncation marker is present is fine HERE. BRANCHING on it in
    ``src/`` is forbidden (ADR-23 decision 15): the marker is not
    authenticatable — an HFSS message can contain its exact wording — so no
    production code may key on it. A test checking our own sanitizer's output is
    not the same act as production code trusting an untrusted string.
    """
    result = _validate(_over_length_native_validation())
    assert isinstance(result, NativeValidation)
    (message,) = result.raw_output
    assert len(message) <= MAX_UNTRUSTED_STR_LEN
    assert "truncated by hfss-agent" in message


def test_hostile_message_is_stripped_but_never_rewritten() -> None:
    fixture = _hostile_native_validation()
    result = _validate(fixture)
    assert isinstance(result, NativeValidation)
    instruction, odd_bytes, structured = result.raw_output

    # STRIPPED: control characters are an injection vector once the untrusted
    # text is rendered downstream.
    assert "\x00" not in odd_bytes
    assert "\x1b" not in odd_bytes
    assert "\r" not in odd_bytes
    # ...and only those characters went. The surrounding words are untouched.
    assert odd_bytes == "[warning] Object name[31m contains odd bytes."

    # KEPT: tab and newline are legitimate structure in a multi-line solver
    # message, so sanitization does not mangle real content.
    assert "\n" in structured
    assert "\t" in structured
    assert structured == fixture.raw_output[2]

    # UNREWRITTEN: ADR-9 neutralizes hostile content by typing and framing it as
    # data, never by censoring or rewording it. Instruction-like text arrives
    # byte-identical to what HFSS reported.
    assert instruction == fixture.raw_output[0]
    assert "Ignore all previous instructions" in instruction


def test_injected_fault_makes_validate_native_cannot_evaluate() -> None:
    """The sixth ledger case, and the one needing no ``scenario.py`` change.

    ``_validate_native`` already routes through ``_injected("validate_native")``,
    so the per-op injection axis every other adapter operation uses covers this
    one too. A native-specific mechanism would be a second way to do one thing.
    """
    fake = FakeAdapter(
        Scenario(
            behavior={
                "validate_native": OpBehavior(
                    fault=AdapterCannotEvaluate(
                        reason="native validation unavailable",
                        limitation=(
                            "HFSS's own design validator could not be run "
                            "through PyAEDT for this design."
                        ),
                    )
                )
            }
        )
    )
    result = fake.validate_native()
    assert isinstance(result, AdapterCannotEvaluate)
    # Not a session fault: PyAEDT answered, so the session stays healthy and
    # nothing here drives it SUSPECT.
    assert not isinstance(result, SessionFault)
    assert result.reason == "native validation unavailable"
