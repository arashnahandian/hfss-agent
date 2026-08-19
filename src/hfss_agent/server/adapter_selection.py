"""Which ``Adapter`` this process gets (W-1, Step 2.8) — chosen once, fail-closed.

WHY THIS IS NOT A CONVENIENCE TOGGLE. The ``FakeAdapter`` returns canned data
that is deliberately plausible: a project, a design, converged solve state, a
full S-parameter series. A user silently served that data gets a WRONG ANSWER
WEARING HONEST PROVENANCE — the exact failure mode this product exists to
prevent, and the one the whole verification chain (gates, formulas, provenance
stamps) is built to make impossible. Every other guard in this repo assumes the
numbers came from the user's own HFSS. If the adapter is wrong, all of them are
faithfully certifying fiction.

A COMMAND-LINE FLAG, NOT AN ENVIRONMENT VARIABLE, AND THE REASON IS THE FAILURE
MODE RATHER THAN TASTE. An environment variable is the one mechanism that can be
set once at Windows user level and then apply silently to every MCP client on
the machine, forever, invisible at the point of use. Someone who exports it for
an afternoon of development keeps it for months. A flag cannot be set globally:
it lives in the ``args`` of the client configuration that spawns this server,
next to the command, visible to anyone who opens that file. The development
convenience an env var would have bought is illusory here — ``select_adapter``
takes its input as a parameter and ``build_composition`` takes an ``Adapter``
directly, so tests never touch process-wide state either way.

THERE IS EXACTLY ONE MECHANISM. No environment-variable fallback is read, by
design: two mechanisms need a precedence rule, and a precedence rule is one more
thing that can surprise someone at exactly the wrong moment.

SO THE DEFAULT IS LIVE AND THE FAKE REQUIRES SAYING SO. Three rules, each of
which is a refusal rather than a fallback:

  1. Flag absent -> LIVE. Absence of configuration must not select the
     safe-for-the-developer option; it must select the correct-for-the-user one.
  2. LIVE with no PyAEDT -> REFUSE TO START, naming the fix. Never a silent
     downgrade to the fake. This is ``RefuseAllConfirmer``'s ethos applied at
     startup: when the correct thing cannot be done, refuse; do not substitute
     something that will answer anyway.
  3. An unrecognised value -> REFUSE TO START. A typo (``--adapter fkae``) must
     not be read as "not fake, therefore live" or as "absent, therefore
     default". It means the operator intended something this server could not
     honour, and guessing which is how a fake session ships to a user.

A KNOWN AND DELIBERATE GAP, STATED HERE BECAUSE IT IS NOT FIXABLE FROM THIS
MODULE: nothing in any tool response distinguishes fake from real. ``Environment``
carries four fields (aedt_version, pyaedt_version, python_version,
wrapper_version) and the fake fills all four with realistic values — its
``pyaedt_version`` is literally the pinned real one, and ``preflight_environment``
run against a fake-backed broker reports ``overall="ok"`` with
``aedt_version_source="attached_session"``. So these refusals, plus the
handshake disclosure in ``app``, are the ONLY things standing between a fake
session and a user who believes it. Neither marks the VALUES; see ``app`` for
the honest bounds of what the disclosure can claim.

TAKES ITS INPUTS INJECTED, BOTH REQUIRED AND UNDEFAULTED, following
``preflight.preflight_environment``'s ``probes`` for the same stated reason:
with no default there is nothing for a forgotten argument to fall through to, so
no caller and no test can read the host machine by omission.
"""

from __future__ import annotations

from collections.abc import Callable

from hfss_agent.adapter import Adapter
from hfss_agent.preflight import VersionRead

# The flag this package reads, and its two legal values. LIVE is also the value
# assumed when the flag is absent; there is no third state and no "auto".
ADAPTER_FLAG = "--adapter"
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

    BOTH STRINGS ARE ASCII-ONLY, AND A TEST ENFORCES IT. These are an operator's
    only diagnostic, they go to stderr, and the primary development platform's
    console is cp1252 — a message that renders "refusing to start ? PyAEDT ?"
    fails at the one moment it exists for.
    """

    def __init__(self, reason: str, remedy: str) -> None:
        self.reason = reason
        self.remedy = remedy
        super().__init__(f"{reason} {remedy}")


def select_adapter(
    requested: str | None,
    pyaedt_version: Callable[[], VersionRead],
) -> Adapter:
    """The one ``Adapter`` this process will use, or a refusal to start.

    Args:
        requested: the ``--adapter`` value, or ``None`` when the flag was not
            given. REQUIRED AND UNDEFAULTED as a parameter — the caller must
            state what was asked for, including that nothing was.
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
    return build_adapter(resolve_adapter_kind(requested, pyaedt_version))


def resolve_adapter_kind(
    requested: str | None,
    pyaedt_version: Callable[[], VersionRead],
) -> str:
    """THE DECISION, with no construction: ``LIVE``, ``FAKE``, or a refusal.

    SPLIT OUT FROM ``select_adapter`` SO CI CAN TEST IT, and the reason is worth
    stating because the split looks like indirection otherwise. Constructing the
    live adapter imports the AEDT API, which is an OPTIONAL extra that public CI
    deliberately does not install — both legs run ``uv sync`` without it. If the
    decision and the construction stayed fused, then every test of the rules
    that matter most ("an absent flag means LIVE", "live without PyAEDT
    REFUSES") could only run on a machine with the extra, and would be skipped
    in exactly the environment that is supposed to prove them. The rules are
    pure logic over a probe result; only the final object needs the backend.

    ``__main__`` also needs the resolved kind separately from the adapter, to
    tell ``build_app`` which disclosure to publish. Resolving once here and
    passing the answer to both is what stops the kind being recomputed — a
    second ``strip().lower()`` elsewhere would be a second source of truth about
    whether this process is simulated, and the two could disagree.
    """
    if requested is None:
        choice = LIVE
    else:
        # Whitespace-tolerant and case-insensitive, because a stray space around
        # a value in a client's JSON config is a mis-set value, not a different
        # intention. Everything else is refused: an explicitly-passed empty
        # value is MALFORMED, not "absent", and is not silently treated as the
        # default — the operator passed the flag on purpose.
        choice = requested.strip().lower()
        if choice not in LEGAL_ADAPTER_VALUES:
            # Built outside the f-string below: nested same-type quotes inside
            # an f-string are a syntax error before Python 3.12, and this
            # package supports 3.10.
            legal = " or ".join(LEGAL_ADAPTER_VALUES)
            raise AdapterSelectionError(
                reason=(
                    f"{ADAPTER_FLAG} was given {requested!r}, which is not a "
                    f"recognised adapter. The server did not start, and did NOT "
                    f"fall back to a default: an unrecognised value means the "
                    f"intended adapter is unknown, and guessing could serve "
                    f"simulated data as if it were read from HFSS."
                ),
                remedy=(
                    f"Pass {ADAPTER_FLAG} with {legal}, or omit the flag "
                    f"entirely to use {LIVE}."
                ),
            )

    if choice == FAKE:
        return FAKE

    # The live branch is the only one that consults the probe: asking for the
    # fake must not depend on the live backend being readable, or a machine
    # without PyAEDT could not run the fake either.
    read = pyaedt_version()
    if read.state != "found":
        raise AdapterSelectionError(
            reason=_live_unavailable_reason(read),
            remedy=(
                "Install the live backend with: uv sync --extra live . To run "
                f"against simulated data instead (for development ONLY, never "
                f"to answer a question about a real design), pass "
                f"{ADAPTER_FLAG} {FAKE}."
            ),
        )
    return LIVE


def build_adapter(kind: str) -> Adapter:
    """Construct the adapter for an already-resolved kind.

    Both imports are deferred to their branch, so a process gets exactly the
    backend it asked for in ``sys.modules`` and no other. That is load-bearing
    on the live side: importing ``hfss_agent.adapter.real`` is PyAEDT-free by
    design, and only CALLING ``make_live_adapter`` pulls in the AEDT API.

    Takes the kind rather than re-deriving it, so this function makes no
    decisions at all -- an unknown kind is a programming error here, not an
    operator error, because ``resolve_adapter_kind`` is the only thing that
    should ever produce one.
    """
    if kind == FAKE:
        from hfss_agent.adapter.fake import FakeAdapter

        return FakeAdapter()
    if kind != LIVE:
        raise ValueError(
            f"build_adapter received {kind!r}; only {LIVE!r} and {FAKE!r} are "
            "constructible, and resolve_adapter_kind is what produces them."
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
