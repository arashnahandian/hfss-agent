"""Static PyAEDT API-contract check (W-3): verify the real adapter's documented
API assumptions against the ACTUALLY-INSTALLED pyaedt — no live session needed.

Skips per-test when pyaedt is absent (the ``live`` extra is not installed in CI),
so CI skips these tests rather than failing on them. Everything here is SIGNATURE
/ attribute-existence verification via ``inspect`` + ``hasattr`` against the real
classes; no application is instantiated and no AEDT session is contacted.

This is NOT live verification. A parameter existing, or a property being defined
on the class, is not proof its getter is side-effect-free or returns the shape we
assume — so nothing in docs/pyaedt-coverage.md is promoted off ``mock-only`` on
the strength of this file. Anything reachable only through an instance
(hfss.modeler.*, hfss.post.*, setup objects) stays unverified until live.

Why a per-test ``skipif`` and not a module-level ``pytest.importorskip``: the
import is guarded by try/except into a boolean (never raising at import time) so
all tests are COLLECTED in every environment and skip individually at run time.
Without the extra this reports "27 skipped" — one legible line per test in the CI
log a stranger reads cold — instead of collapsing to a single module-level skip
that hides how many checks the absent extra silenced.
"""

from __future__ import annotations

import inspect

import pytest

try:
    import ansys.aedt.core as aedt_core
    from ansys.aedt.core import Desktop, Hfss

    _HAS_PYAEDT = True
except ImportError:  # the `live` extra is not installed; every test skips below
    aedt_core = Desktop = Hfss = None
    _HAS_PYAEDT = False

pytestmark = pytest.mark.skipif(
    not _HAS_PYAEDT,
    reason="pyaedt (the `live` extra) is not installed",
)


def _params(func: object) -> set[str]:
    return set(inspect.signature(func).parameters)


# --- (1) THE CRITICAL ONE: attach parameters ---------------------------------
# An unrecognised keyword silently falls back to the LAUNCHING default instead of
# attaching, which would start a new AEDT session on the user's machine. So we
# assert, against the real signature, the exact names the adapter passes.

_ATTACH_PARAMS_HFSS = (
    "new_desktop",
    "aedt_process_id",
    "close_on_exit",
    "project",
    "design",
)
_ATTACH_PARAMS_DESKTOP = ("new_desktop", "aedt_process_id", "close_on_exit")


@pytest.mark.parametrize("name", _ATTACH_PARAMS_HFSS)
def test_hfss_constructor_has_attach_param(name: str) -> None:
    params = _params(Hfss.__init__)
    assert name in params, f"Hfss.__init__ has no {name!r}; params={sorted(params)}"


@pytest.mark.parametrize("name", _ATTACH_PARAMS_DESKTOP)
def test_desktop_constructor_has_attach_param(name: str) -> None:
    params = _params(Desktop.__init__)
    assert name in params, f"Desktop.__init__ has no {name!r}; params={sorted(params)}"


def test_new_desktop_is_the_current_name_not_new_desktop_session() -> None:
    # Settle the rename: 1.2.0 uses ``new_desktop``; the old ``new_desktop_session``
    # is gone under both classes. The adapter passes ``new_desktop=False`` — this
    # locks that it is the recognised name, not a silently-ignored kwarg.
    hfss_params = _params(Hfss.__init__)
    desktop_params = _params(Desktop.__init__)
    assert "new_desktop" in hfss_params and "new_desktop" in desktop_params
    assert "new_desktop_session" not in hfss_params
    assert "new_desktop_session" not in desktop_params


# --- (2) class-level members the real adapter reads --------------------------
# Only members the adapter actually reads, and only those checkable without an
# instance. Sub-object members (modeler.object_names, post.get_solution_data,
# setup.is_solved, available_variations.get_variation_strings, …) need a live
# instance and are intentionally absent here (UNVERIFIABLE).

_HFSS_MEMBERS = (
    "solution_type",       # real_adapter._select
    "setup_names",         # real_adapter._list_options / _inspect
    "get_sweeps",          # real_adapter._list_options / _inspect
    "available_variations",  # real_adapter._list_variations
    "variable_manager",    # real_adapter._inspect_variables
    "modeler",             # real_adapter._inspect_objects
    "materials",           # real_adapter._inspect_materials
    "boundaries",          # real_adapter._inspect_boundaries
    "excitation_names",    # real_adapter._inspect_ports / _read_solved_data
    "post",                # real_adapter._inspect_results / _read_solved_data
    "setups",              # real_adapter._read_solve_state
    "odesign",             # session.validate_native
)
_DESKTOP_MEMBERS = (
    "project_list",        # session.project_names
    "aedt_version_id",     # session.aedt_version
    "odesktop",            # session.project_path / design_names
)


@pytest.mark.parametrize("name", _HFSS_MEMBERS)
def test_hfss_exposes_member(name: str) -> None:
    assert hasattr(Hfss, name), f"Hfss has no class-level {name!r}"


@pytest.mark.parametrize("name", _DESKTOP_MEMBERS)
def test_desktop_exposes_member(name: str) -> None:
    assert hasattr(Desktop, name), f"Desktop has no class-level {name!r}"


def test_project_list_is_a_property_read_without_a_call() -> None:
    # session.py reads ``desktop.project_list`` (no parens). Assert it really is a
    # property, so a ``project_list()`` call would be the bug it once was.
    assert isinstance(inspect.getattr_static(Desktop, "project_list"), property)


def test_get_sweeps_is_callable() -> None:
    # real_adapter calls ``app.get_sweeps(setup)`` — assert it is a method, not a
    # property, so the call form is correct.
    assert callable(inspect.getattr_static(Hfss, "get_sweeps"))


# --- (3) version pin ----------------------------------------------------------


def test_installed_version_matches_pin() -> None:
    assert aedt_core.__version__.startswith("1.2."), aedt_core.__version__
