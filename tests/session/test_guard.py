"""The suspect guard is STRUCTURAL, not remembered (ADR-17 decision 2 pattern).

Every public adapter-touching method must carry ``@reconnect_guarded``. This is
enforced by dynamic reflection over ``Session`` — never a hardcoded method list —
so a new unguarded method added later fails CI rather than shipping.
"""

from __future__ import annotations

import inspect

from hfss_agent.session import Session

# Public methods that legitimately do NOT carry the reconnect guard. Kept HERE in
# the test file (not in the module) so widening it appears as a reviewable test
# diff. Each entry carries its justification.
_EXEMPT = {
    # attach re-establishes the session; running reconnect-and-verify BEFORE the
    # operation that creates the session is meaningless.
    "attach",
    # get_session_status is a pure read of internal state — it makes no adapter
    # call and must report suspect honestly rather than silently re-verify.
    "get_session_status",
}


def _public_methods() -> list[tuple[str, object]]:
    return [
        (name, member)
        for name, member in inspect.getmembers(Session, predicate=inspect.isfunction)
        if not name.startswith("_")
    ]


def test_every_public_method_is_reconnect_guarded_or_exempt() -> None:
    for name, member in _public_methods():
        if name in _EXEMPT:
            continue
        assert getattr(member, "__reconnect_guarded__", False), (
            f"public Session method {name!r} is neither @reconnect_guarded nor in "
            f"_EXEMPT — a new adapter-touching op must go through the suspect guard "
            f"or be explicitly exempted (with justification) in this test"
        )


def test_exempt_entries_are_real_methods() -> None:
    # A typo'd or stale _EXEMPT entry would silently exempt a nonexistent method
    # and weaken the guarantee — so every exemption must name a real public method.
    names = {name for name, _ in _public_methods()}
    missing = _EXEMPT - names
    assert not missing, f"_EXEMPT names that are not public Session methods: {missing}"


def test_the_two_operations_are_actually_guarded() -> None:
    # Positive anchor: the adapter-touching operations really carry the marker.
    assert getattr(Session.select, "__reconnect_guarded__", False) is True
    guarded = getattr(Session.list_selection_options, "__reconnect_guarded__", False)
    assert guarded is True
