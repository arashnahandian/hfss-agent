"""Read-only / no-arbitrary-execution AST audit for the real adapter (W-3).

The STRONG, structural guarantee: the real adapter is a finite, human-authored
set of reads with NO dynamic dispatch, so no arbitrary or mutating AEDT method is
reachable through the tool surface. This test enforces that on source (it never
runs a live session), three ways:

  1. no dynamic-execution primitives (eval / exec / compile / __import__, and no
     ``import subprocess``);
  2. no dynamic attribute dispatch — ``getattr`` / ``setattr`` / ``delattr`` with
     a non-literal name (a caller-supplied string must never become a call);
  3. no known mutating / persisting / session-owning / SOLVE AEDT method NAMES
     appear — in BOTH the PyAEDT snake_case wrappers AND the native COM
     PascalCase layer the adapter also reaches (e.g. ``odesign.ValidateDesign()``
     in session.py). Guarding only one spelling guards the wrong surface.

What it does NOT and CANNOT prove: that each *authored read* is side-effect-free.
That is the weaker, live-verified assurance (see ``real/session.py`` docstring).
This proves the surface is finite and free of escape hatches — not that a given
getter has no side effects on a live solver.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REAL = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "hfss_agent"
    / "adapter"
    / "real"
)


def _audited_files() -> list[Path]:
    """Every module under ``real/`` — discovered by glob, never hardcoded, so a
    file added to the package later cannot escape the audit silently."""
    return sorted(_REAL.rglob("*.py"))


# Callables that introduce arbitrary execution.
_FORBIDDEN_CALLS = frozenset({"eval", "exec", "compile", "__import__"})
# Attribute-dispatch builtins: forbidden only when the attribute NAME is dynamic.
_DYNAMIC_ATTR_BUILTINS = frozenset({"getattr", "setattr", "delattr"})

# Mutating / persisting / session-owning / SOLVE AEDT names, listed explicitly in
# BOTH conventions. Redundant with the prefixes below in places — kept explicit
# so the intent is legible and the named risks are obviously covered.
_FORBIDDEN_NAMES = frozenset(
    {
        # session lifecycle / ownership (CHANGE-2: never tear down or launch a
        # session we do not own) + attach-only footguns from the plan.
        "release_desktop",
        "close_desktop",
        "launch_desktop",
        "new_desktop",
        "open_project",
        "rename_design",
        # active-selection setters — proved unnecessary (CHANGE-1), both spellings.
        "set_active_project",
        "set_active_design",
        "SetActiveProject",
        "SetActiveDesign",
        # persistence / project-design lifecycle (native COM PascalCase included).
        "save",
        "save_project",
        "save_as",
        "close",
        "close_project",
        "close_design",
        "delete_project",
        "delete_design",
        "Save",
        "SaveAs",
        "SaveProjectAs",
        "Close",
        "CloseProject",
        "Delete",
        "DeleteDesign",
        "DeleteProject",
        # SOLVE / ANALYZE — HIGH tier in this project's risk taxonomy; the single
        # most dangerous family, denied in both conventions.
        "analyze",
        "analyze_setup",
        "analyze_all",
        "analyze_nominal",
        "submit_job",
        "Analyze",
        "AnalyzeAll",
        "AnalyzeDistributed",
        "SubmitJob",
        # Bare "solve" names are EXACT (not a prefix): a ``Solve`` prefix would
        # false-positive on the ``SolveState`` / ``SolvedData`` contract types.
        "solve",
        "solve_setup",
        "Solve",
        "SolveSetup",
    }
)
# Family heads: any name starting with one of these is a mutator, in either
# convention. Catches future *_setup / Create* / Assign* variants automatically.
_FORBIDDEN_PREFIXES = (
    # snake_case (PyAEDT wrappers)
    "create_",
    "assign_",
    "edit_",
    "insert_",
    "modify_",
    "delete_",
    "duplicate_",
    "import_",
    "export_",
    "move_",
    "rotate_",
    "mirror_",
    "analyze_",
    "submit_",
    "rename_",
    "open_",
    "save_",
    "close_",
    # PascalCase (native COM). NOTE: no ``Solve`` prefix — it would match the
    # ``SolveState`` / ``SolvedData`` contract types; bare solve names are exact.
    "Create",
    "Assign",
    "Edit",
    "Insert",
    "Modify",
    "Delete",
    "Duplicate",
    "Import",
    "Export",
    "Move",
    "Rotate",
    "Mirror",
    "Analyze",
    "Submit",
    "Rename",
    "Open",
    "Save",
    "Close",
    "Paste",
    "Cut",
)


def _is_forbidden_name(name: str) -> bool:
    return name in _FORBIDDEN_NAMES or name.startswith(_FORBIDDEN_PREFIXES)


def _is_str_literal(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _violations(source: str) -> list[str]:
    """Every read-only / no-execution violation in ``source`` (AST, no exec)."""
    out: list[str] = []
    for node in ast.walk(ast.parse(source)):
        # (1) arbitrary execution + (2) dynamic attribute dispatch.
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name in _FORBIDDEN_CALLS:
                out.append(f"arbitrary-execution call: {name}()")
            elif (
                name in _DYNAMIC_ATTR_BUILTINS
                and len(node.args) >= 2
                and not _is_str_literal(node.args[1])
            ):
                out.append(f"dynamic attribute dispatch: {name}(..., <non-literal>)")
        # (3) mutating names, as attribute access (x.Save) or bare name (Save()).
        if isinstance(node, ast.Attribute) and _is_forbidden_name(node.attr):
            out.append(f"mutating name: .{node.attr}")
        if isinstance(node, ast.Name) and _is_forbidden_name(node.id):
            out.append(f"mutating name: {node.id}")
    return out


def _imports_subprocess(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "subprocess" for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] == "subprocess":
                return True
    return False


# --- the audit, over every discovered file in real/ --------------------------


def test_audit_discovers_the_real_package_files() -> None:
    # A broken path must not let the audit pass vacuously: require files, and
    # require the known modules to be among them.
    names = {path.name for path in _audited_files()}
    assert names, f"no files discovered under {_REAL}"
    assert {"__init__.py", "session.py", "real_adapter.py"} <= names


def test_real_adapter_has_no_mutation_or_execution_hatch() -> None:
    files = _audited_files()
    assert files, f"no files discovered under {_REAL}"
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert not _violations(source), (path.name, _violations(source))
        assert not _imports_subprocess(source), f"{path.name} imports subprocess"


# --- the audit must actually bite: self-tests on synthetic snippets ----------


def test_audit_flags_release_and_close_desktop() -> None:
    assert _violations("hfss.release_desktop()")
    assert _violations("hfss.close_desktop(close_projects=True)")


def test_audit_flags_active_selection_setters() -> None:
    assert _violations("app.set_active_design('D1')")
    assert _violations("desktop.SetActiveProject('P1')")


def test_audit_flags_snake_case_mutating_prefixes() -> None:
    assert _violations("modeler.create_box([0, 0, 0])")
    assert _violations("hfss.assign_material('obj', 'copper')")


def test_audit_flags_native_pascalcase_mutators() -> None:
    # The native COM layer session.py reaches (odesign.ValidateDesign, etc.) uses
    # PascalCase — the spelling that matters most, and previously unguarded.
    assert _violations("oproject.Save()")
    assert _violations("oproject.Close()")
    assert _violations("odesign.DeleteDesign()")


def test_audit_flags_solve_and_analyze_family_both_conventions() -> None:
    # HIGH-tier batch solves — denied in both conventions.
    assert _violations("hfss.analyze_setup('S1')")
    assert _violations("odesign.AnalyzeAll()")
    assert _violations("hfss.submit_job()")
    assert _violations("scheduler.SubmitJob()")


def test_audit_flags_attach_only_footguns() -> None:
    assert _violations("desktop.launch_desktop()")
    assert _violations("desktop.open_project('p.aedt')")
    assert _violations("app.new_desktop()")
    assert _violations("oproject.rename_design('D2')")


def test_audit_flags_arbitrary_execution_and_dynamic_dispatch() -> None:
    assert _violations("eval('1 + 1')")
    assert _violations("exec(user_code)")
    assert _violations("getattr(hfss, method_name)()")  # non-literal attribute


def test_audit_flags_subprocess_import() -> None:
    assert _imports_subprocess("import subprocess")
    assert _imports_subprocess("from subprocess import run")


def test_audit_allows_literal_getattr_and_plain_reads() -> None:
    # A constant-name getattr is not dynamic dispatch; plain reads are clean.
    assert not _violations("getattr(hfss, 'setup_names')")
    assert not _violations("names = hfss.setup_names")
    assert not _violations("data = hfss.post.get_solution_data(expressions=e)")


# --- construction-call-site audit: forbidden constructor ARGUMENTS -----------
# The mutation-name audit above guards method NAMES; a mutating risk can also
# live in the ARGUMENT LIST of an application constructor, carried by ast.keyword
# nodes that the name audit never sees (the same reason new_desktop=False is
# safely ignored there). These arguments to Hfss()/Desktop() MUTATE:
#   * remove_lock  — strips another user's project lock (attach-only forbids it);
#   * solution_type — as a CONSTRUCTOR arg SETS the design's solution type
#                     (reading the hfss.solution_type PROPERTY after binding is
#                     correct and unrelated — only the ctor arg is forbidden);
#   * setup        — as a CONSTRUCTOR arg SETS rather than reads.
# Positional args and **kwargs unpacking are denied too: either could smuggle a
# forbidden argument past a kwarg-name check.
_APP_CONSTRUCTORS = frozenset({"Hfss", "Desktop"})
_FORBIDDEN_CONSTRUCTOR_KWARGS = frozenset({"remove_lock", "solution_type", "setup"})


def _constructor_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):  # e.g. ansys.aedt.core.Hfss(...)
        return func.attr
    return None


def _constructor_arg_violations(source: str) -> list[str]:
    """Forbidden arguments at any Hfss()/Desktop() construction site."""
    out: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = _constructor_name(node.func)
        if name not in _APP_CONSTRUCTORS:
            continue
        if node.args:
            out.append(f"{name}(...): positional arg (attach args must be keyword)")
        for keyword in node.keywords:
            if keyword.arg is None:
                out.append(f"{name}(**kwargs): unpacking defeats the kwarg audit")
            elif keyword.arg in _FORBIDDEN_CONSTRUCTOR_KWARGS:
                out.append(f"{name}(..., {keyword.arg}=...): mutating constructor arg")
    return out


def test_real_adapter_passes_no_mutating_constructor_kwargs() -> None:
    for path in _audited_files():
        source = path.read_text(encoding="utf-8")
        assert not _constructor_arg_violations(source), (
            path.name,
            _constructor_arg_violations(source),
        )


def test_ctor_audit_flags_forbidden_kwargs() -> None:
    assert _constructor_arg_violations("Hfss(project=p, remove_lock=True)")
    assert _constructor_arg_violations("Hfss(project=p, solution_type='DrivenModal')")
    assert _constructor_arg_violations("Hfss(project=p, setup='S1')")
    assert _constructor_arg_violations("Desktop(remove_lock=True)")


def test_ctor_audit_flags_positional_and_star_kwargs() -> None:
    # Positional smuggling: Hfss(p, d, 'DrivenModal') sets solution_type by
    # position; **opts hides the keys from a kwarg-name check entirely.
    assert _constructor_arg_violations("Hfss(p, d, 'DrivenModal')")
    assert _constructor_arg_violations("Hfss(**opts)")


def test_ctor_audit_allows_legit_attach_construction() -> None:
    assert not _constructor_arg_violations(
        "Hfss(project=p, design=d, new_desktop=False, close_on_exit=False)"
    )
    assert not _constructor_arg_violations(
        "Desktop(new_desktop=False, close_on_exit=False, aedt_process_id=pid)"
    )
