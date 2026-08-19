"""Which ``Adapter`` this process gets (W-1, Step 2.8) — chosen once, fail-closed.

WHY THIS IS NOT A CONVENIENCE TOGGLE. The ``FakeAdapter`` returns canned data
that is deliberately plausible: a project, a design, converged solve state, a
full S-parameter series. A user silently served that data gets a WRONG ANSWER
WEARING HONEST PROVENANCE — the exact failure mode this product exists to
prevent, and the one the whole verification chain (gates, formulas, provenance
stamps) is built to make impossible. Every other guard in this repo assumes the
numbers came from the user's own HFSS. If the adapter is wrong, all of them are
faithfully certifying fiction.

SO THE DEFAULT IS LIVE AND THE FAKE REQUIRES SAYING SO. Three rules, each of
which is a refusal rather than a fallback:

  1. Unset -> LIVE. Absence of configuration must not select the safe-for-the-
     developer option; it must select the correct-for-the-user one.
  2. LIVE with no PyAEDT -> REFUSE TO START, naming the fix. Never a silent
     downgrade to the fake. This is ``RefuseAllConfirmer``'s ethos applied at
     startup: when the correct thing cannot be done, refuse; do not substitute
     something that will answer anyway.
  3. An unrecognised value -> REFUSE TO START. A typo (``HFSS_AGENT_ADAPTER=
     fkae``) must not be read as "not fake, therefore live" or as "unset,
     therefore default". It means the operator intended something this server
     could not honour, and guessing which is how a fake session ships to a user.

A KNOWN AND DELIBERATE GAP, STATED HERE BECAUSE IT IS NOT FIXABLE FROM THIS
MODULE: nothing in any tool response distinguishes fake from real. ``Environment``
carries four fields (aedt_version, pyaedt_version, python_version,
wrapper_version) and the fake fills all four with realistic values — its
``pyaedt_version`` is literally the pinned real one. So this module's refusals
are the ONLY barrier between a fake session and a user who believes it. That is
why they are refusals and not warnings. Adding a provenance field to say which
adapter answered would be a contract change and is not proposed here.

TAKES ITS INPUTS INJECTED, BOTH REQUIRED AND UNDEFAULTED, following
``preflight.preflight_environment``'s ``probes`` for the same stated reason:
with no default there is nothing for a forgotten argument to fall through to, so
no caller and no test can read the host machine — or the host environment — by
omission.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from hfss_agent.adapter import Adapter
from hfss_agent.preflight import VersionRead

# The one environment variable this package reads. Prefixed, because an
# unprefixed name like ADAPTER would collide with anything else on the machine
# and this variable can select a session that answers with fiction.
ADAPTER_ENV_VAR = "HFSS_AGENT_ADAPTER"

# The two legal values. LIVE is also the value assumed when the variable is
# unset; there is no third state and no "auto".
LIVE = "live"
FAKE = "fake"
LEGAL_ADAPTER_VALUES = (LIVE, FAKE)


class AdapterSelectionError(Exception):
    """Startup refusal: the requested adapter cannot be provided.

    An exception rather than a typed outcome, and the distinction matters. The
    typed-outcome discipline (``cannot_evaluate``, ``SelectionRefused``) governs
    the TOOL SURFACE — a tool that cannot answer must say so in a shape the
    caller can read. This failure happens before any tool exists, before the
    transport is up, and before there is anyone to hand an outcome to. The
    honest response is not to start, which is what ``__main__`` turns this into:
    a message on stderr and a non-zero exit. Assembly failures elsewhere in the
    repo (``InspectionAssemblyError``, ``SnapshotAssemblyError``,
    ``DiagnosticsBundleError``) already set this precedent.

    Carries ``remedy`` separately from ``reason`` so the caller renders "what is
    wrong" and "what to do about it" as two things. A refusal that does not name
    its fix is how a user concludes the tool is broken.
    """

    def __init__(self, reason: str, remedy: str) -> None:
        self.reason = reason
        self.remedy = remedy
        super().__init__(f"{reason} {remedy}")


def select_adapter(
    environ: Mapping[str, str],
    pyaedt_version: Callable[[], VersionRead],
) -> Adapter:
    """The one ``Adapter`` this process will use, or a refusal to start.

    Args:
        environ: the process environment. REQUIRED AND UNDEFAULTED — see the
            module docstring. Tests pass a plain dict; ``__main__`` passes
            ``os.environ``.
        pyaedt_version: reads whether PyAEDT is installed, as the same
            three-state ``VersionRead`` preflight uses. REQUIRED AND UNDEFAULTED
            for the same reason. Reusing preflight's probe rather than writing a
            second detector here is deliberate: two ways to answer "is PyAEDT
            installed" would eventually disagree, and preflight's already
            distinguishes NOT INSTALLED from INSTALLED BUT UNREADABLE, which
            send a user to different fixes.

    Returns:
        A ``FakeAdapter`` or a live ``RealAdapter``. Never a fallback: if the
        requested one cannot be built, this raises.

    Raises:
        AdapterSelectionError: on an unrecognised value, or when live was
            selected (explicitly or by default) and PyAEDT is not usable.
    """
    requested = environ.get(ADAPTER_ENV_VAR)
    if requested is None:
        choice = LIVE
    else:
        # Whitespace-tolerant and case-insensitive, because a trailing space in
        # a Windows environment variable is a mis-set value, not a different
        # intention. Everything else is refused: an explicitly-set-but-empty
        # value is MALFORMED, not "unset", and is not silently treated as the
        # default — the operator touched this variable on purpose.
        choice = requested.strip().lower()
        if choice not in LEGAL_ADAPTER_VALUES:
            # Built outside the f-string below: nested same-type quotes inside
            # an f-string are a syntax error before Python 3.12, and this
            # package supports 3.10.
            legal = " or ".join(repr(value) for value in LEGAL_ADAPTER_VALUES)
            raise AdapterSelectionError(
                reason=(
                    f"{ADAPTER_ENV_VAR} is set to {requested!r}, which is not a "
                    f"recognised adapter. The server did not start, and did NOT "
                    f"fall back to a default: an unrecognised value means the "
                    f"intended adapter is unknown, and guessing could serve "
                    f"simulated data as if it were read from HFSS."
                ),
                remedy=(
                    f"Set {ADAPTER_ENV_VAR} to {legal}, or unset it entirely "
                    f"to use {LIVE!r}."
                ),
            )

    if choice == FAKE:
        # Imported HERE, not at module scope, for the reason the live branch
        # defers its own import: neither backend should be loaded by a process
        # that did not ask for it.
        from hfss_agent.adapter.fake import FakeAdapter

        return FakeAdapter()

    read = pyaedt_version()
    if read.state != "found":
        raise AdapterSelectionError(
            reason=_live_unavailable_reason(read),
            remedy=(
                "Install the live backend with: uv sync --extra live . To run "
                f"against simulated data instead (for development ONLY, never "
                f"to answer a question about a real design), set "
                f"{ADAPTER_ENV_VAR}={FAKE}."
            ),
        )
    from hfss_agent.adapter.real import make_live_adapter

    return make_live_adapter()


def _live_unavailable_reason(read: VersionRead) -> str:
    """Why live could not be provided, keeping preflight's two absences apart.

    "Not installed" and "installed but its metadata is unreadable" send a user
    to different fixes — install versus reinstall — and collapsing them into one
    message costs whoever hits the second one a wasted debugging session.
    """
    if read.state == "absent":
        detail = "PyAEDT is not installed"
    else:
        detail = (
            "PyAEDT appears to be installed but its version metadata could not "
            "be read, so it cannot be vouched for"
        )
    return (
        f"the live adapter was selected but {detail}. The server did not start, "
        f"and did NOT fall back to the simulated adapter: answering with canned "
        f"data while a user believes they are reading their own design is the "
        f"one failure this tool must never produce."
    )
