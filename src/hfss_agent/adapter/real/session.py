"""LiveSession (W-3): the ONE module in this repo — and its private sibling —
permitted to import the AEDT API.

The AEDT API ships on PyPI as ``pyaedt`` but imports as ``ansys.aedt.core`` (the
1.0 restructure moved the package to ``src/ansys/aedt/core/``). The import audit
(``tests/boundary/test_adapter_import_audit.py``) fails the build if either name
shape — ``import pyaedt`` / ``from pyaedt`` OR ``import ansys.aedt`` /
``from ansys.aedt`` — appears in any file other than this one.

Guarantee strength — stated exactly, not rounded up (ADR + CLAUDE.md honesty rule):
  * STRONG, structural: the adapter is a finite, human-authored set of reads
    with NO dynamic dispatch (no eval/exec/compile/subprocess, no
    getattr-by-caller-string), so no arbitrary or mutating AEDT method is
    reachable through the tool surface. The AST tests in
    ``tests/prohibited_ops/test_adapter_read_only.py`` enforce this on source.
  * WEAKER, explicitly labeled: each individual call written in this file is
    BELIEVED read-only from PyAEDT's documented 1.2.x API, PENDING LIVE
    VERIFICATION. With no licensed AEDT on the build machine this module is
    mock-only (docs/pyaedt-coverage.md); Phase 5.2 live validation is where each
    signature and side-effect assumption is actually confirmed. Do NOT read the
    strong guarantee as covering the weaker one.

Attach-only — by construction AND by omission:
  * connect with ``new_desktop=False`` (never launch AEDT), ``close_on_exit=False``
    (never close a session we do not own), ``aedt_process_id=<pid>`` (bind to the
    already-running process);
  * there is NO ``release_desktop()`` / ``close_desktop()`` call anywhere, with
    any arguments — we attached to a session we do not own and leave it as we
    found it. Both names are in the mutation denylist; the AST test fails if
    either ever appears. Attach happens once per session (not per call), so no
    per-call connection handle accumulates.

Explicit scoping (CHANGE-1 / ADR): reads are scoped by BINDING an ``Hfss`` app to
a specific ``(project, design)`` via ``application()``; this module never calls
``SetActiveProject`` / ``set_active_design``. Binding MAY set that design active
inside PyAEDT — a PyAEDT side effect, not an adapter action — and read
correctness does not depend on it, because every read flows through the bound
object's ``odesign``. This module changes no design content and never persists.
"""

from __future__ import annotations

from typing import Any

import ansys.aedt.core  # THE single permitted AEDT-API import (see module docstring)
from ansys.aedt.core import Desktop, Hfss


class LiveSession:
    """Owns the attach-only AEDT connection and hands back read-scoped handles.

    Structurally implements the ``LiveSession`` seam ``RealAdapter`` depends on
    (duck-typed — ``RealAdapter`` imports no AEDT API). Every method here is
    mock-only until live validation; the accessor names/return shapes carry
    inline uncertainty notes where PyAEDT's documented API is not something this
    build machine can confirm.
    """

    def __init__(self) -> None:
        self._desktop: Any = None
        # Cache of Hfss handles bound per (project, design); attach-only args, so
        # binding never launches or takes ownership of the session.
        self._apps: dict[tuple[str, str], Any] = {}

    def attach(self, process_id: int) -> None:
        # Attach-only: new_desktop=False → never launch AEDT; close_on_exit=False
        # → never close a session we don't own; aedt_process_id → bind to the
        # already-running process. Param names are 1.2.x-documented but unverified
        # on this machine (see docstring).
        #
        # LIMITATION (Phase 5.2 live-verify): on a re-attach this rebinds
        # ``self._desktop`` to a NEW Desktop and orphans the previous one with NO
        # release — release_desktop/close_desktop are attach-only-forbidden
        # (ADR-17 #10, mutation denylist, AST-enforced), so we cannot close it.
        # Whether the orphaned Desktop leaks a grpc/COM connection or a zombie
        # process reference is unanswerable without a live session; PyAEDT's
        # process-level session dedup is expected to reclaim/reuse it. If it
        # leaks, attach-only-without-release may be incompatible with re-attach
        # and recovery needs a different mechanism (see docs/pyaedt-coverage.md).
        self._desktop = Desktop(
            new_desktop=False,
            close_on_exit=False,
            aedt_process_id=process_id,
        )

    def reset_bindings(self) -> None:
        # Drop every cached (project, design) → Hfss handle. Called by
        # RealAdapter._attach on every (re)attach so a handle bound to a prior
        # desktop is never read after a new attach. Pure Python state — no AEDT
        # call, not a release (those are forbidden) — so it cannot close or
        # mutate a session; it only forgets our cache. The orphaned handles' live
        # fate is the same Phase 5.2 question as the orphaned Desktop above.
        self._apps.clear()

    def aedt_version(self) -> str:
        # e.g. "2026.1"; identity only, a getter on the attached Desktop.
        return str(self._desktop.aedt_version_id)

    def pyaedt_version(self) -> str:
        return str(ansys.aedt.core.__version__)

    def project_names(self) -> list[str]:
        # Names of the currently-open projects (attach-only: we choose among
        # already-open projects, never open/create one). `project_list` is a
        # PROPERTY in pyaedt 1.2.0 (verified) — accessed WITHOUT a call.
        return [str(name) for name in self._desktop.project_list]

    def project_path(self, project: str) -> str:
        # Full path of an already-open project, read WITHOUT activating it by
        # matching against the project COM objects. Accessor shape uncertain —
        # live-verify (Phase 5.2).
        for oproject in self._desktop.odesktop.GetProjects():
            if str(oproject.GetName()) == project:
                return str(oproject.GetPath())
        return ""

    def design_names(self, project: str) -> list[str]:
        # Design names within a project, read at the project level so enumeration
        # never binds an HFSS app to a possibly non-HFSS design. Shape uncertain —
        # live-verify.
        for oproject in self._desktop.odesktop.GetProjects():
            if str(oproject.GetName()) == project:
                return [str(design.GetName()) for design in oproject.GetDesigns()]
        return []

    def application(self, project: str, design: str) -> Any:
        # Bind (and cache) an Hfss app scoped to (project, design). Reads flow
        # through this bound object's odesign, so they are scoped by BINDING; this
        # module never calls SetActiveProject/set_active_design (CHANGE-1).
        # Attach-only args again so binding never launches/owns the session.
        # Footgun (flagged for live-verify): passing a design that is not an HFSS
        # design can error; the agent is HFSS-scoped, so callers pass HFSS designs.
        key = (project, design)
        app = self._apps.get(key)
        if app is None:
            app = Hfss(
                project=project,
                design=design,
                new_desktop=False,
                close_on_exit=False,
            )
            self._apps[key] = app
        return app

    def validate_native(self, project: str, design: str) -> list[str]:
        # Uses the design-level ValidateDesign + a message read, NOT
        # validate_full_design(): the latter writes a validation log file to the
        # project directory, and in this system only `broker` performs file I/O.
        # The message-read signature is uncertain — live-verify (Phase 5.2).
        app = self.application(project, design)
        app.odesign.ValidateDesign()
        messages = app.odesign.GetMessages("", "", 0)
        return [str(message) for message in messages]
