"""Five structural audits that guard W-1's shape rather than its behaviour.

    1. where tools may be registered            (all of src/hfss_agent)
    2. how many servers exist to register on    (all of src/hfss_agent)
    3. what an assembler actually dispatches    (the assembler modules)
    4. what may reach stdout at import time     (all of src/hfss_agent)
    5. which transport may be named             (src/hfss_agent/server ONLY)

THE SCOPES DIFFER AND THE TABLE SAYS SO, because this docstring used to open
"five structural audits over ``src/``" while audit 5 walks ``server/`` alone.
That is the right scope for it -- a transport is only ever named where one is
started -- but a reader who took the blanket claim at face value would believe
a planted ``run("sse")`` anywhere in the package would be caught, and it
would not.

ALL FIVE ARE AST WALKS, NEVER TEXT SEARCHES, and one of them proves why that
matters: ``server/serialization.py`` contains the literal text
``@server.tool(name="...", description="...")`` inside a docstring, as the usage
example for the decorator. A grep-based registration audit would report that
file as a second registration site and be wrong. The walks below see code.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hfss_agent.server.tool_surface import TOOL_SURFACE

_SRC = Path(__file__).resolve().parents[2] / "src" / "hfss_agent"
_SERVER = _SRC / "server"


def _sources(root: Path) -> list[Path]:
    files = sorted(root.rglob("*.py"))
    assert files, f"no sources discovered under {root}"
    return files


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


# =============================================================================
# 1. THE SINGLE REGISTRATION SITE
# =============================================================================


def _registers_a_tool(tree: ast.Module) -> bool:
    """Whether this module registers an MCP tool, by either shape.

    Two shapes exist and both must be seen: ``server.add_tool(fn, ...)`` and the
    decorator ``@server.tool(...)`` / ``@server.tool``. The decorator is the one
    ``app.py`` uses; ``add_tool`` is the imperative form the test helpers use and
    that a future module would most likely reach for.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "add_tool":
                return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                target = (
                    decorator.func
                    if isinstance(decorator, ast.Call)
                    else decorator
                )
                if isinstance(target, ast.Attribute) and target.attr == "tool":
                    return True
    return False


def test_exactly_one_file_in_src_registers_tools() -> None:
    """THE ASSUMPTION UNDERNEATH EVERY GUARD IN ``tests/server/test_completeness.py``.

    That whole suite -- both completeness directions, every capability check,
    every tier comparison, and both tier proofs -- begins by calling
    ``build_app`` and reading the server it returns. None of them can see a tool
    registered anywhere else: a line added in ``__main__`` between
    ``build_composition`` and ``run("stdio")`` would expose a twelfth tool to
    every real client while every completeness test stayed green, because those
    tests build their own app.

    This audit is what makes ``build_app`` the whole surface. It is not tidiness;
    without it the completeness proof is a proof about one code path rather than
    about the server.
    """
    # ``as_posix`` because CI runs on Ubuntu as well as Windows and
    # ``str(PurePath)`` yields backslashes on one of them -- an assertion on the
    # raw string passes on Linux and fails on Windows for no real reason.
    registrars = sorted(
        path.relative_to(_SRC).as_posix()
        for path in _sources(_SRC)
        if _registers_a_tool(_tree(path))
    )
    assert registrars == ["server/app.py"], (
        f"tool registration found in {registrars}; exactly one file may "
        "register tools, and it must be server/app.py -- every completeness "
        "and tier guard reads the surface that build_app produces."
    )


def test_the_registration_detector_sees_both_shapes() -> None:
    """Positive limb: a detector that matched nothing would make the audit
    above pass vacuously and permanently."""
    assert _registers_a_tool(ast.parse("srv.add_tool(fn, name='x')\n"))
    assert _registers_a_tool(
        ast.parse("@srv.tool(name='x')\ndef f() -> str: ...\n")
    )
    assert _registers_a_tool(ast.parse("@srv.tool\ndef f() -> str: ...\n"))
    assert not _registers_a_tool(ast.parse("x = 1\n"))
    # The docstring case that a grep would get wrong.
    assert not _registers_a_tool(ast.parse('"""@server.tool(name=\'x\')"""\n'))


# =============================================================================
# 2. THE SINGLE SERVER-CONSTRUCTION SITE
# =============================================================================
#
# THE RESIDUE AUDIT 1 LEAVES, closed here. "Exactly one file registers
# tools" is NOT "exactly one server exists to register them on", and the gap is
# reachable: a second entry point could build its own ``MCPServer`` and register
# onto that. Every guard in ``tests/server/test_completeness.py`` and
# ``tests/prohibited_ops/test_mcp_tier_surface.py`` calls ``build_app`` and reads
# the server IT returns, so all of them would stay green while a client spawning
# the other entry point was offered a different surface -- one with no
# ``_describe`` lookup behind it, therefore no ``TOOL_SURFACE`` row, therefore no
# declared tier. The registration audit above cannot notice: the registrations
# would still be in ``app.py``, just onto a different object.
#
# COUNTS CALL SITES, NOT FILES, and the difference is not pedantry. A per-file
# check was written first and MEASURED not to fire against a second ``MCPServer``
# built inside ``app.py`` itself -- which is the likeliest place a second one
# actually appears, since that is where the SDK class is already imported. The
# unit that matters is the construction, so the audit reports ``file:line``.
#
# WHAT THIS WALK SEES: a call to the name ``MCPServer``, however it is locally
# bound -- ``from mcp.server.mcpserver import MCPServer as Srv`` then
# ``Srv(...)`` is resolved through the import -- and a call to
# ``<anything>.MCPServer(...)``.
#
# WHAT IT CANNOT SEE, stated rather than left to be discovered: a construction
# through a value computed at runtime (``getattr(module, "MCPServer")()``, the
# class held in a dict or returned by a factory), and a single call site reached
# twice at runtime (``build_app`` called by two entry points). No such shape
# exists in ``src/`` today, and the second is harmless anyway -- two apps built
# by the same code have the same surface. The honest claim is "the direct
# construction shapes appear at exactly one place in src/", not "no server can
# be built anywhere else".

_SERVER_CLASS = "MCPServer"


def _server_class_aliases(tree: ast.Module) -> set[str]:
    """Every local name bound to the SDK's server class in this module.

    Without this, ``import MCPServer as Srv`` followed by ``Srv(...)`` would be
    invisible to the walk below -- a one-line rename defeating the audit.
    """
    aliases = {_SERVER_CLASS}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == _SERVER_CLASS and alias.asname:
                    aliases.add(alias.asname)
    return aliases


def _server_construction_lines(tree: ast.Module) -> list[int]:
    """Line numbers at which this module CONSTRUCTS an ``MCPServer``.

    An annotation is not a construction: ``def f(app: MCPServer) -> MCPServer``
    names the class without building one, and only ``ast.Call`` nodes are
    consulted, so annotations do not register.
    """
    aliases = _server_class_aliases(tree)
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Name) and func.id in aliases) or (
            isinstance(func, ast.Attribute) and func.attr == _SERVER_CLASS
        ):
            lines.append(node.lineno)
    return sorted(lines)


def test_exactly_one_place_in_src_constructs_a_server() -> None:
    """THE OTHER HALF OF "``build_app`` IS THE WHOLE SURFACE".

    The registration audit proves tools are registered in one file. This proves
    there is one SERVER for them to be registered on, so the object every
    completeness and tier guard inspects is the object a client is served.

    The expected site is asserted as a ``file:line`` pair, so moving the
    construction is a visible edit to this line rather than a silent one.
    """
    builders = sorted(
        f"{path.relative_to(_SRC).as_posix()}:{line}"
        for path in _sources(_SRC)
        for line in _server_construction_lines(_tree(path))
    )
    assert len(builders) == 1 and builders[0].startswith("server/app.py:"), (
        f"MCPServer constructed at {builders}; exactly one place may build a "
        "server, and it must be in server/app.py -- every completeness and tier "
        "guard reads the surface of the server build_app returns, and a second "
        "server would carry tools none of them can see."
    )


def test_the_server_construction_detector_sees_the_shapes_it_claims() -> None:
    """Positive limb: a detector that matched nothing would make the audit above
    pass vacuously and permanently, which is how a guard rots into decoration."""
    assert _server_construction_lines(ast.parse("s = MCPServer(name='x')\n")) == [1]
    assert _server_construction_lines(ast.parse("s = mcpserver.MCPServer()\n")) == [1]
    assert _server_construction_lines(
        ast.parse("from mcp.server.mcpserver import MCPServer as Srv\ns = Srv()\n")
    ) == [2]
    # Two constructions in ONE file are two findings, which is the measured gap
    # a per-file check had.
    assert _server_construction_lines(
        ast.parse("a = MCPServer()\nb = MCPServer()\n")
    ) == [1, 2]
    assert _server_construction_lines(ast.parse("x = 1\n")) == []
    # Naming the type is not building one -- ``server_helpers`` and ``app`` both
    # annotate with it, and an audit that counted annotations would be wrong
    # about which files build a server.
    assert _server_construction_lines(
        ast.parse("def f(app: MCPServer) -> MCPServer: ...\n")
    ) == []
    # Prose, again: three server docstrings discuss ``MCPServer`` by name.
    assert _server_construction_lines(
        ast.parse('"""Registered onto MCPServer."""\n')
    ) == []


# =============================================================================
# 3. ASSEMBLER-DISPATCH AGREEMENT
# =============================================================================
#
# WHAT THIS CAN AND CANNOT SEE, stated before the code because the limit is the
# point. The walk resolves a dispatch name when it is a string literal at the
# call site OR a module-level constant assigned a string literal -- which is the
# shape every assembler in this repo actually uses (``_INSPECT_CAPABILITY =
# "inspect_design"`` then ``broker.dispatch(_INSPECT_CAPABILITY, ...)``). A name
# built at runtime -- from a parameter, an f-string, a dict lookup, a loop
# variable -- IS INVISIBLE TO THIS WALK.
#
# So the claim this audit supports is: "the dispatches this assembler makes
# STATICALLY are exactly the ones its row names." It is NOT "these are all the
# capabilities the assembler can reach." If a dynamic dispatch is ever
# introduced, ``_UNRESOLVED`` below records it and the audit fails rather than
# silently under-reporting -- refusing to vouch is the honest failure, and it is
# what stops this from quietly degrading into a check that sees nothing.

_UNRESOLVED = "<unresolved: not a literal or module-level constant>"


def _module_level_string_constants(tree: ast.Module) -> dict[str, str]:
    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = node.value.value
    return constants


def _dispatched_names(tree: ast.Module) -> set[str]:
    """Capability names passed to any ``.dispatch(...)`` in this module."""
    constants = _module_level_string_constants(tree)
    names: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "dispatch" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            names.add(first.value)
        elif isinstance(first, ast.Name) and first.id in constants:
            names.add(constants[first.id])
        else:
            names.add(_UNRESOLVED)
    return names


def _assembler_rows():
    return [b for b in TOOL_SURFACE if b.assembler is not None]


@pytest.mark.parametrize(
    "row", _assembler_rows(), ids=lambda row: row.name
)
def test_each_assembler_dispatches_exactly_what_its_row_names(row) -> None:
    """A SECOND, INDEPENDENT READING -- not a derivation.

    ``inner_capabilities`` stays stated by hand in ``tool_surface``, because a
    row computed from the assembler would make the completeness test compare the
    code to itself. This reads the assembler's source separately and requires
    the two to agree, in BOTH directions:

      * a row that UNDERSTATES (assembler dispatches something the row omits)
        means the transitive tier claim does not cover everything the tool
        reaches -- the exact hole ADR-5 exists to close;
      * a row that OVERSTATES (row names a dispatch the assembler does not make)
        means the accounting describes a reach that is not there, which is the
        kind of entry that survives a refactor and misleads the next reader.
    """
    module_path, _, _ = row.assembler.rpartition(".")
    path = _SRC / (module_path.split("hfss_agent.", 1)[1].replace(".", "/") + ".py")
    assert path.exists(), f"{row.name}: {path} does not exist"

    dispatched = _dispatched_names(_tree(path))
    assert _UNRESOLVED not in dispatched, (
        f"{row.name}: {path.name} dispatches a name this audit cannot resolve "
        "statically. The audit refuses to vouch for a row it cannot check; "
        "either make the name a literal or a module-level constant, or record "
        "in tool_surface that this row is unverifiable and why."
    )
    declared = set(row.inner_capabilities)
    assert dispatched == declared, (
        f"{row.name}: {path.name} dispatches {sorted(dispatched)} but its "
        f"tool_surface row declares {sorted(declared)}. "
        f"Undeclared: {sorted(dispatched - declared)}. "
        f"Declared but not dispatched: {sorted(declared - dispatched)}."
    )


def test_the_dispatch_walk_resolves_module_level_constants() -> None:
    """Positive limb, and the reason this audit needed constant resolution at
    all: EVERY assembler in this repo names its capability through a
    module-level constant, so a literal-only walk would find nothing."""
    literal = "b.dispatch('x')\n"
    viaconst = "_C = 'y'\n\ndef f(b):\n    return b.dispatch(_C)\n"
    dynamic = "def f(b, n):\n    return b.dispatch(n)\n"
    assert _dispatched_names(ast.parse(literal)) == {"x"}
    assert _dispatched_names(ast.parse(viaconst)) == {"y"}
    assert _dispatched_names(ast.parse(dynamic)) == {_UNRESOLVED}


def test_the_no_capability_row_really_dispatches_nothing() -> None:
    """``preflight_environment`` claims ``reaches_no_capability``. That claim is
    the reason its tier is uncorroborated by any ``CapabilitySpec``, so it is
    worth checking rather than trusting."""
    row = next(b for b in TOOL_SURFACE if b.name == "preflight_environment")
    assert row.reaches_no_capability is True
    path = _SRC / "preflight" / "assembler.py"
    assert _dispatched_names(_tree(path)) == set(), (
        "preflight/assembler.py now dispatches something; its row claims to "
        "reach no capability, and its tier depends on that being true."
    )


# =============================================================================
# 4. IMPORT-TIME STDOUT
# =============================================================================


def _stdout_writes_at_import(tree: ast.Module) -> list[str]:
    """Module-level (import-time) writes to stdout.

    ``print(..., file=sys.stderr)`` is permitted anywhere; a bare ``print`` and
    any ``sys.stdout.write`` are not. Only MODULE-LEVEL statements are examined:
    the SDK diverts fd 1 to fd 2 for the duration of serving, so a write from
    inside a function that runs after ``run()`` cannot reach the wire. The
    window this covers is the one that protection does not: import time, before
    the transport claims the descriptor.
    """
    offenders: list[str] = []

    def visit(node: ast.AST) -> None:
        # DO NOT DESCEND into a function or class body. ``ast.walk`` would --
        # skipping the def node itself does not skip its children, which is the
        # bug this shape exists to avoid. Everything inside a def runs after
        # import, where the SDK's fd-1 diversion already protects the wire.
        for child in ast.iter_child_nodes(node):
            if isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                continue
            if isinstance(child, ast.Call):
                func = child.func
                if isinstance(func, ast.Name) and func.id == "print":
                    if "file" not in {kw.arg for kw in child.keywords}:
                        offenders.append("bare print() at module level")
                if isinstance(func, ast.Attribute) and func.attr in {
                    "write",
                    "writelines",
                }:
                    value = func.value
                    if isinstance(value, ast.Attribute) and value.attr == "stdout":
                        offenders.append("sys.stdout.write at module level")
            visit(child)

    visit(tree)
    return offenders


# THE FILE SET, STATED RATHER THAN DERIVED: every ``*.py`` under
# ``src/hfss_agent``, at every depth, package ``__init__.py`` files included.
#
# It used to be a hand-written tuple of the twelve SUBPACKAGE names, walked as
# ``_SRC / package``. That set has a hole exactly where it matters most:
# ``src/hfss_agent/__init__.py`` sits above all twelve and was never walked,
# so a bare ``print()`` in the FIRST module a server process imports was
# invisible to the one audit that exists to catch it. Measured: planted there,
# every boundary test stayed green. A hand-written membership list is also the
# thing a thirteenth package would silently fall out of, so the list is gone
# rather than extended by one entry.


def _stdout_audited_sources() -> list[Path]:
    """Every source this audit examines. Whole tree, no exemptions."""
    return _sources(_SRC)


def test_no_module_writes_to_stdout_at_import_time() -> None:
    """THE NARROW FORM, and the reason it is narrow.

    Part 2 measured that the SDK claims fd 1 for JSON-RPC and points the
    process's own stdout at stderr while serving, so a stray ``print`` inside a
    handler lands on stderr and the session continues -- verified by driving it.
    A test forbidding ``print`` in handlers would therefore be asserting
    something the SDK already guarantees.

    What the SDK does NOT cover is the window before ``run()``: anything written
    at IMPORT time reaches the real descriptor and would sit ahead of the first
    JSON-RPC frame, which a client parses as a protocol error. Importing this
    package is exactly what a server process does first, so that window is
    reached on every single start.
    """
    offenders = {}
    for path in _stdout_audited_sources():
        found = _stdout_writes_at_import(_tree(path))
        if found:
            # ``as_posix`` so a failure reads the same on both CI legs.
            offenders[path.relative_to(_SRC).as_posix()] = found
    assert not offenders, (
        f"import-time stdout writes: {offenders}. Under stdio transport these "
        "land ahead of the first JSON-RPC frame and the client sees a protocol "
        "error. Route diagnostics to stderr."
    )


def test_the_stdout_audit_covers_the_package_root_not_just_subpackages() -> None:
    """THE FLOOR THE OLD FILE SET FAILED.

    ``src/hfss_agent/__init__.py`` is the first module a server process
    imports, so it is the worst possible place for an unguarded module-level
    ``print`` and the first place this audit must look. It was outside the
    walked set until Part 10. This pins the file set rather than the outcome:
    a future refactor that narrows the walk fails HERE, naming the omission,
    instead of leaving the audit quietly blind.
    """
    audited = {path.relative_to(_SRC).as_posix() for path in _stdout_audited_sources()}
    assert "__init__.py" in audited, (
        "the package root is outside the stdout audit's file set"
    )
    # And every subpackage root, since those were the old set and must not be
    # lost in the other direction.
    for package in (
        "adapter",
        "broker",
        "contract",
        "findings",
        "gating",
        "inspect",
        "metrics",
        "preflight",
        "server",
        "session",
        "snapshot",
        "validate_native",
    ):
        assert f"{package}/__init__.py" in audited, package


def test_stderr_directed_print_is_permitted() -> None:
    """``__main__`` prints two refusal lines to stderr. The audit must permit
    that -- an audit that forbade it would be forbidding the only diagnostic
    channel a refused startup has."""
    assert _stdout_writes_at_import(ast.parse("print('x')\n")) == [
        "bare print() at module level"
    ]
    assert _stdout_writes_at_import(ast.parse("print('x', file=sys.stderr)\n")) == []
    assert _stdout_writes_at_import(ast.parse("sys.stdout.write('x')\n")) == [
        "sys.stdout.write at module level"
    ]
    # Inside a function is out of scope: the fd diversion covers it.
    assert _stdout_writes_at_import(ast.parse("def f():\n    print('x')\n")) == []


# =============================================================================
# 5. THE TRANSPORT TRIPWIRE (server/ ONLY -- see the module docstring)
# =============================================================================

_FORBIDDEN_TRANSPORTS = frozenset({"sse", "streamable-http"})
_FORBIDDEN_RUNNERS = frozenset({"run_sse_async", "run_streamable_http_async"})


def _transport_violations(tree: ast.Module) -> list[str]:
    """Named transports other than stdio.

    Keyed on CALL ARGUMENTS and ATTRIBUTE NAMES, never on bare string constants:
    a docstring or comment discussing SSE is prose, and an audit that failed on
    prose would be one people route around by rewording rather than by fixing.
    """
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_RUNNERS:
            found.append(node.attr)
        if isinstance(node, ast.Call):
            for argument in [*node.args, *(kw.value for kw in node.keywords)]:
                if not isinstance(argument, ast.Constant):
                    continue
                if argument.value in _FORBIDDEN_TRANSPORTS:
                    found.append(f"transport argument {argument.value!r}")
    return found


def test_no_transport_other_than_stdio_is_named() -> None:
    """FAILS WHEN: someone wires an HTTP transport into the server package.

    That is not hypothetical -- the Stack Decision Record anticipates it in
    writing: "any future HTTP transport requires localhost-only binding and its
    own ADR." This fires exactly when that ADR is being skipped. stdio was
    chosen because it has NO NETWORK LISTENER AT ALL, which is strictly stronger
    than binding to localhost, and that property is lost silently the moment a
    different transport string is passed.
    """
    violations = {}
    for path in _sources(_SERVER):
        found = _transport_violations(_tree(path))
        if found:
            violations[path.name] = sorted(set(found))
    assert not violations, (
        f"non-stdio transport named in server/: {violations}. stdio has no "
        "network listener; an HTTP transport needs localhost-only binding and "
        "its own ADR (Stack Decision Record, Axis A)."
    )


def test_stdio_is_actually_named_somewhere() -> None:
    """Floor: if nobody names a transport at all, the tripwire above passes
    while the server does not start. Pins that the ONE reachable literal is
    present and is stdio."""
    main = _tree(_SERVER / "__main__.py")
    literals = [
        argument.value
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        for argument in node.args
        if isinstance(argument, ast.Constant)
        and argument.value in {"stdio", *_FORBIDDEN_TRANSPORTS}
    ]
    assert literals == ["stdio"], f"transport literals in __main__: {literals}"


def test_the_transport_detector_finds_every_shape_it_claims_to() -> None:
    assert _transport_violations(ast.parse("app.run('sse')\n"))
    assert _transport_violations(ast.parse("app.run(transport='streamable-http')\n"))
    assert _transport_violations(ast.parse("await app.run_sse_async()\n"))
    assert _transport_violations(ast.parse("await app.run_streamable_http_async()\n"))
    assert not _transport_violations(ast.parse("app.run('stdio')\n"))
    # Prose must not trip it -- otherwise the fix is a reword, not a fix.
    assert not _transport_violations(ast.parse('"""We refuse sse transport."""\n'))
