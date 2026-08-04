"""``DesignSnapshot.created_at`` is timezone-aware or it is refused (ADR-28).

``InspectionProvenance.read_at`` and ``NativeValidationProvenance.validated_at``
are both ``AwareDatetime``, and both carry a comment saying a naive value is
rejected rather than silently read as local time, so "when" is never ambiguous
by an offset. ``created_at`` predates both and was the last plain ``datetime``
among them; this amendment closed that asymmetry.

Tightening it cost nothing: W-8 is its only producer and mints it in UTC.
``SolveState.solve_timestamps`` was deliberately NOT tightened alongside it —
its producer is the adapter reading ``setup.get_profile()``, whose shape is
``mock-only`` and unverified against a live AEDT, so requiring awareness there
could make a live read fail in a way no test could catch before Phase 5.2. That
one is re-queued rather than guessed at.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from hfss_agent.contract import (
    CONTRACT_VERSION,
    DesignSnapshot,
    Environment,
    Inspection,
    InspectionSection,
    NativeValidation,
    Selection,
    SolveDataUnavailable,
    Variation,
)

_SECTION_NAMES = (
    "variables",
    "objects",
    "materials",
    "boundaries",
    "excitations_ports",
    "setups",
    "sweeps",
    "available_results",
)


def _kwargs(created_at: datetime) -> dict[str, object]:
    section = InspectionSection(data=[], read_status="ok")
    return {
        "contract_version": CONTRACT_VERSION,
        "created_at": created_at,
        "snapshot_id": "snap-001",
        "environment": Environment(
            aedt_version="2026.1",
            pyaedt_version="1.2.0",
            python_version="3.12.10",
            wrapper_version="0.0.0",
        ),
        "selection": Selection(
            process_id=12345,
            project="patch_antenna",
            design="HFSSDesign1",
            solution_type="DrivenModal",
            setup="Setup1",
            sweep="Sweep1",
            variation=Variation(values={}, variation_hash="sha256:x"),
        ),
        "inspection": Inspection(**{name: section for name in _SECTION_NAMES}),
        "native_validation": NativeValidation(raw_output=[]),
        "solve_state": SolveDataUnavailable(reason="no_solution", limitation="x"),
        "solved_data": SolveDataUnavailable(reason="no_solution", limitation="x"),
    }


def test_a_naive_created_at_is_refused() -> None:
    """The value this field used to accept silently.

    A naive datetime is not a UTC instant with the marker missing — it is an
    instant nobody can place, and reading it as local time is a guess dressed as
    data. Rejecting it is the same call both provenance types already made.
    """
    with pytest.raises(ValidationError) as caught:
        DesignSnapshot(**_kwargs(datetime(2026, 8, 3, 12, 0, 0)))  # type: ignore[arg-type]
    error = caught.value.errors()[0]
    assert error["loc"] == ("created_at",)
    assert "timezone" in error["msg"].lower()


def test_an_aware_created_at_is_accepted_and_keeps_its_offset() -> None:
    """Aware means aware, not "UTC only".

    W-8 mints UTC, but the field's contract is that the instant is unambiguous —
    so a non-UTC offset is valid data and must survive rather than being coerced.
    Asserting the offset SURVIVES, not merely that construction succeeded, is
    what distinguishes this from a test that would pass under a plain
    ``datetime``.
    """
    plus_two = timezone(timedelta(hours=2))
    aware = datetime(2026, 8, 3, 12, 0, 0, tzinfo=plus_two)
    snapshot = DesignSnapshot(**_kwargs(aware))  # type: ignore[arg-type]

    assert snapshot.created_at.utcoffset() == timedelta(hours=2)
    assert snapshot.created_at == datetime(
        2026, 8, 3, 10, 0, 0, tzinfo=timezone.utc
    )


def test_a_naive_created_at_is_refused_on_json_reload_too() -> None:
    """The engine seam is JSON, so the in-process constructor is only half the
    boundary. A hand-written or hand-edited snapshot arriving without an offset
    must be refused on the way IN as well."""
    valid = DesignSnapshot(**_kwargs(datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)))  # type: ignore[arg-type]
    payload = valid.model_dump(mode="json")
    payload["created_at"] = "2026-08-03T12:00:00"

    with pytest.raises(ValidationError) as caught:
        DesignSnapshot.model_validate(payload)
    assert caught.value.errors()[0]["loc"] == ("created_at",)
