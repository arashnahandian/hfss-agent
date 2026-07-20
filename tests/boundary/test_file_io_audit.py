"""THE file-I/O boundary audit (System Design §5): nothing outside ``broker``
performs file I/O.

This invariant was unenforceable before Step 1.4 because nothing in ``src/``
did file I/O at all; the broker's file layer (Parts 3-4) created the first
permitted sites, so the audit now has something real to distinguish. It
checks, over glob-discovered sources (ADR-17 decision 11 — never a hardcoded
file list):

  * NON-BROKER ``src/``: no ``open()`` calls; no ``tempfile``/``shutil``
    imports; no ``os.<fn>()`` file calls; no Path-style file-op attribute
    names;
  * POSITIVE: ``broker/files/`` and ``broker/audit/`` actually CONTAIN file
    I/O — so the exemption cannot silently hollow out into a rule that
    permits everything and requires nothing;
  * IN-BROKER modes: ``broker/audit/`` writes only in ``"a"`` (reads: the
    reader's text read and the writer's binary ``"rb"`` tail check);
    ``broker/files/`` writes via exclusive create (``"x"``/``"xb"``) or the
    temp-then-``os.replace`` path (``os.fdopen`` ``"w"``/``"wb"``);
    ``os.makedirs`` only in ``files/locations.py``; ``os.rename`` nowhere;
  * NO DELETION PRIMITIVE anywhere in ``src/``, broker included — the
    structural no-deletion claim (plan decision 3), machine-checked rather
    than reviewed.

All checks are AST-based, not substring-based: Part 3 demonstrated why when a
grep for delete primitives matched "platformdirs" (it contains "rmdir"); a
self-test below pins that a docstring word can never trip this audit.

DELIBERATE BOUNDARY: metadata-only reads (``os.path.exists``, ``os.path.isdir``,
``os.stat``) are outside the denylist — the invariant targets file CONTENT and
NAMESPACE mutation, not existence checks (``paths.py``'s parent-dir check must
remain legal exactly where it is).

HONEST LIMITATION: this is a CI-enforced denylist heuristic, not a proof. It
catches every ordinary route to a file handle and distinguishes broker from
everything else, but AST denylisting cannot be exhaustive — an I/O-capable
third-party import could evade it until the import audits catch the import
itself. One accepted over-breadth: ``x.replace(...)`` on ANY receiver is
flagged (``Path.replace`` and ``str.replace`` are indistinguishable in AST);
non-broker source uses only the bare dataclasses ``replace(...)``, which is
not flagged, and a self-test pins that distinction.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "hfss_agent"
_BROKER = _SRC / "broker"
_LOCATIONS = _BROKER / "files" / "locations.py"

# os-module functions that open, mutate, or truncate the filesystem namespace.
_OS_FILE_FUNCS = frozenset(
    {
        "open",
        "fdopen",
        "remove",
        "unlink",
        "rename",
        "replace",
        "mkdir",
        "makedirs",
        "rmdir",
        "truncate",
    }
)
# Path-method names that read/write content or mutate the namespace, flagged
# on ANY receiver (the adapter read-only audit's attribute-name pattern).
_PATH_METHOD_NAMES = frozenset(
    {
        "open",
        "write_text",
        "write_bytes",
        "read_text",
        "read_bytes",
        "unlink",
        "mkdir",
        "rename",
        "replace",
        "touch",
    }
)
# Deletion: os-receiver functions, plus method names valid on any receiver.
# "remove" is deliberately NOT in the any-receiver set — ``list.remove`` is
# ordinary Python; the os-receiver check covers ``os.remove``.
_OS_DELETE_FUNCS = frozenset({"remove", "unlink", "rmdir", "removedirs"})
_DELETE_METHOD_NAMES = frozenset({"unlink", "rmdir", "rmtree"})
_FORBIDDEN_IO_IMPORTS = ("tempfile", "shutil")


def _all_sources() -> list[Path]:
    files = sorted(_SRC.rglob("*.py"))
    assert files, f"no source files discovered under {_SRC}"
    return files


def _non_broker_sources() -> list[Path]:
    files = [path for path in _all_sources() if not path.is_relative_to(_BROKER)]
    assert files, "non-broker discovery is broken (would pass vacuously)"
    return files


def _package_sources(package: Path) -> list[Path]:
    files = sorted(package.rglob("*.py"))
    assert files, f"no source files discovered under {package}"
    return files


def _is_os_attr(node: ast.expr, names: frozenset[str]) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
        and node.attr in names
    )


def _io_violations(source: str) -> list[str]:
    """Every file-I/O denylist hit in ``source`` (AST, no exec)."""
    out: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            out += [
                f"import of I/O module: {alias.name}"
                for alias in node.names
                if alias.name.split(".")[0] in _FORBIDDEN_IO_IMPORTS
            ]
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in _FORBIDDEN_IO_IMPORTS:
                out.append(f"import of I/O module: {node.module}")
            elif root == "os":
                out += [
                    f"from os import {alias.name}"
                    for alias in node.names
                    if alias.name in _OS_FILE_FUNCS
                ]
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "open":
                out.append("open() call")
            elif _is_os_attr(node.func, _OS_FILE_FUNCS):
                out.append(f"os.{node.func.attr}() call")
        elif isinstance(node, ast.Attribute) and node.attr in _PATH_METHOD_NAMES:
            out.append(f"Path-style file op: .{node.attr}")
    return out


def _deletion_violations(source: str) -> list[str]:
    out: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _is_os_attr(node.func, _OS_DELETE_FUNCS):
            out.append(f"os.{node.func.attr}() call")
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            out += [
                f"from os import {alias.name}"
                for alias in node.names
                if alias.name in _OS_DELETE_FUNCS
            ]
        elif isinstance(node, ast.Attribute) and node.attr in _DELETE_METHOD_NAMES:
            out.append(f"deletion method: .{node.attr}")
    return out


def _rename_violations(source: str) -> list[str]:
    out: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _is_os_attr(
            node.func, frozenset({"rename"})
        ):
            out.append("os.rename() call")
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            out += ["from os import rename" for a in node.names if a.name == "rename"]
    return out


def _is_str_constant(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _mode_argument(call: ast.Call) -> str:
    """The literal mode of an open/fdopen call; "r" when omitted; "<dynamic>"
    when non-literal, so a computed mode fails the mode audits loudly."""
    if len(call.args) >= 2:
        return call.args[1].value if _is_str_constant(call.args[1]) else "<dynamic>"
    for keyword in call.keywords:
        if keyword.arg == "mode":
            return (
                keyword.value.value
                if _is_str_constant(keyword.value)
                else "<dynamic>"
            )
    return "r"


def _open_calls(source: str) -> list[tuple[str, str]]:
    """(kind, mode) for every builtin ``open()`` and ``os.fdopen()`` call."""
    calls: list[tuple[str, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            calls.append(("open", _mode_argument(node)))
        elif _is_os_attr(node.func, frozenset({"fdopen"})):
            calls.append(("os.fdopen", _mode_argument(node)))
    return calls


def _makedirs_hits(source: str) -> int:
    return sum(1 for hit in _io_violations(source) if "makedirs" in hit)


# --- the repo-wide invariant --------------------------------------------------


def test_discovery_covers_the_known_tree() -> None:
    names = {path.name for path in _all_sources()}
    assert {"broker.py", "session.py", "base.py", "writes.py", "writer.py"} <= names
    assert all(
        not path.is_relative_to(_BROKER) for path in _non_broker_sources()
    )


def test_nothing_outside_broker_performs_file_io() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _non_broker_sources():
        violations = _io_violations(path.read_text(encoding="utf-8"))
        if violations:
            offenders[str(path.relative_to(_SRC))] = violations
    assert not offenders, f"file I/O outside broker: {offenders}"


def test_broker_files_and_audit_actually_contain_file_io() -> None:
    # The positive assertion (the permitted-module pattern from the AEDT-API
    # audit): the exemption must be EARNED, or the rule permits everything
    # and requires nothing.
    for package in (_BROKER / "files", _BROKER / "audit"):
        hits = [
            hit
            for path in _package_sources(package)
            for hit in _io_violations(path.read_text(encoding="utf-8"))
        ]
        assert hits, f"{package} is expected to contain the permitted file I/O"


def test_broker_outside_files_and_audit_touches_no_files() -> None:
    # Within broker, the file surface lives in files/ and audit/ ONLY; the
    # dispatch layer (broker.py, registry.py, confirmation.py) orchestrates
    # through those primitives and opens nothing itself.
    offenders: dict[str, list[str]] = {}
    for path in _package_sources(_BROKER):
        if path.is_relative_to(_BROKER / "files") or path.is_relative_to(
            _BROKER / "audit"
        ):
            continue
        violations = _io_violations(path.read_text(encoding="utf-8"))
        if violations:
            offenders[path.name] = violations
    assert not offenders, f"file I/O outside broker/files and broker/audit: {offenders}"


# --- in-broker mode audits (what Parts 3-4 actually built) --------------------


def test_audit_package_write_mode_is_append_only() -> None:
    modes: list[str] = []
    for path in _package_sources(_BROKER / "audit"):
        modes += [mode for _, mode in _open_calls(path.read_text(encoding="utf-8"))]
    # "a" append (writer), "r" text read (reader), "rb" tail check (writer).
    assert set(modes) <= {"a", "r", "rb"}, modes
    assert "a" in modes  # the append-only writer actually exists


def test_files_package_writes_are_exclusive_create_or_temp_replace() -> None:
    for path in _package_sources(_BROKER / "files"):
        for kind, mode in _open_calls(path.read_text(encoding="utf-8")):
            if kind == "open":
                # Direct opens: exclusive create ("x"/"xb", the ADR-8
                # overwrite guard) or a plain text read.
                assert mode in {"x", "xb", "r"}, (path.name, kind, mode)
            else:
                # os.fdopen: ONLY the mkstemp temp that os.replace promotes.
                assert mode in {"w", "wb"}, (path.name, kind, mode)


def test_makedirs_only_in_files_locations() -> None:
    offenders: dict[str, int] = {}
    locations_hits = 0
    for path in _all_sources():
        hits = _makedirs_hits(path.read_text(encoding="utf-8"))
        if not hits:
            continue
        if path == _LOCATIONS:
            locations_hits = hits
        else:
            offenders[str(path.relative_to(_SRC))] = hits
    assert not offenders, f"makedirs outside files/locations.py: {offenders}"
    assert locations_hits >= 1  # the one permitted site actually exists


def test_os_rename_appears_nowhere_in_src() -> None:
    offenders = {
        str(path.relative_to(_SRC)): violations
        for path in _all_sources()
        if (violations := _rename_violations(path.read_text(encoding="utf-8")))
    }
    assert not offenders, (
        f"os.rename in src (os.replace is the required call): {offenders}"
    )


def test_no_deletion_primitive_anywhere_in_src() -> None:
    # The structural no-deletion claim (plan decision 3): provable because no
    # deletion call site exists, broker included.
    offenders = {
        str(path.relative_to(_SRC)): violations
        for path in _all_sources()
        if (violations := _deletion_violations(path.read_text(encoding="utf-8")))
    }
    assert not offenders, f"deletion primitives in src: {offenders}"


# --- the audits must actually bite: self-tests on synthetic snippets ---------


def test_io_audit_flags_every_denylisted_category() -> None:
    assert _io_violations("open('f.txt')")
    assert _io_violations("import tempfile")
    assert _io_violations("from shutil import copyfileobj")
    assert _io_violations("os.replace(a, b)")
    assert _io_violations("os.makedirs(p)")
    assert _io_violations("from os import unlink")
    assert _io_violations("p.write_text('x')")
    assert _io_violations("p.touch()")


def test_io_audit_allows_metadata_reads_and_plain_code() -> None:
    # Metadata-only reads are DELIBERATELY legal (module docstring), and the
    # bare dataclasses replace(...) the session uses is a Name, not a
    # Path-style attribute.
    assert _io_violations("os.path.exists(p)") == []
    assert _io_violations("os.path.isdir(p)") == []
    assert _io_violations("os.stat(p)") == []
    assert _io_violations("import os") == []
    assert _io_violations("replace(state, health=h)") == []


def test_io_audit_over_breadth_on_replace_is_pinned() -> None:
    # Accepted over-breadth (module docstring): AST cannot tell str.replace
    # from Path.replace, so ANY attribute .replace is flagged. If a future
    # non-broker module legitimately needs str.replace, this audit will say
    # so loudly and the exemption becomes a reviewable decision.
    assert _io_violations("text.replace('a', 'b')")


def test_deletion_audit_bites_and_ignores_docstring_words() -> None:
    assert _deletion_violations("os.remove(p)")
    assert _deletion_violations("p.unlink()")
    assert _deletion_violations("shutil.rmtree(d)")
    assert _deletion_violations("from os import unlink")
    # The Part 3 grep false positive, pinned impossible here: "platformdirs"
    # contains the substring "rmdir", but a word inside a docstring is a
    # string constant the AST walk never reads attributes from.
    assert _deletion_violations('"""prefers platformdirs over hand-rolling"""') == []
    # ...and ordinary list.remove is not a filesystem deletion.
    assert _deletion_violations("items.remove(x)") == []


def test_rename_audit_bites_and_allows_replace() -> None:
    assert _rename_violations("os.rename(a, b)")
    assert _rename_violations("from os import rename")
    assert _rename_violations("os.replace(a, b)") == []


def test_mode_extraction_reads_literal_and_default_modes() -> None:
    assert _open_calls("open(p)") == [("open", "r")]
    assert _open_calls("open(p, 'x', encoding='utf-8')") == [("open", "x")]
    assert _open_calls("open(p, mode='a')") == [("open", "a")]
    assert _open_calls("os.fdopen(fd, 'w')") == [("os.fdopen", "w")]
    assert _open_calls("open(p, m)") == [("open", "<dynamic>")]
