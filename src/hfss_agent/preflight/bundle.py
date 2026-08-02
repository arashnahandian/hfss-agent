"""W-11 diagnostics bundle: the file a user decides whether to send (Point 21).

Composes the preflight report with the REDACTED audit log and states, in the
file itself, what was taken out and what that still does not guarantee.

THE READER OF THIS FILE IS A PERSON DECIDING WHETHER TO EMAIL IT. Every shape
decision below follows from that and from nothing else. It is one JSON
document rather than an archive so the user can open it and read it before
sending; it is indented so they can; and the honesty statement is IN the
document rather than in this docstring, because the person who needs it will
never see this file.

WHAT THIS MODULE DOES NOT DO. It does not decide what may leave the machine —
``redaction`` does, and the reasoning for every rule lives there. It does not
write to disk: the payload is handed to ``Broker.write_export``, the one
guarded write primitive, exactly as ``metrics/export.py`` hands over its
Touchstone and CSV content.

THE SMALL BUNDLE, DELIBERATELY. ``docs/pyaedt-coverage.md`` commits
``export_diagnostics_bundle`` to composing ``inspect`` + ``validate_native`` +
``read_solve_state`` + ``read_solved_data``. That contradicts Point 21's own
definition — "no geometry, no fields" — and it would require W-11 to reach the
adapter, which ADR-26 decision 1 forbids. This module builds the small bundle
(versions, the environment verdict, and the redacted call history) and the
four-read composition stays FLAGGED rather than built; correcting that document
is Step 3.x's.

ONE CONSEQUENCE WORTH STATING: because nothing here reaches an adapter,
``ExportResult``'s ``CannotEvaluate`` arm is UNREACHABLE for this tool as built.
It is not dead code to be removed — the type is shared with ``export_results``,
which does reach one — but a reader tracing this module's outcomes should know
only three of the four arms can occur.

THE BUNDLE CARRIES NO WALL-CLOCK STAMP, and that is a change from the plan made
for the reason W-5, W-6 and W-7 are all timestamp-free: the same machine state
must render identical bytes, so two bundles can be diffed and a test can pin the
wording. A ``generated_at`` field would make every pair of bundles differ in the
one place nothing changed. The "when" is not lost — the audit records carry
their own timestamps, and the file has an mtime.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from hfss_agent.broker import Broker, BrokerFileError
from hfss_agent.contract.tool_io import (
    AuditLog,
    ExportFailed,
    ExportResult,
    PreflightReport,
)
from hfss_agent.preflight.assembler import preflight_environment
from hfss_agent.preflight.probes import EnvironmentProbes
from hfss_agent.preflight.redaction import (
    REDACTION_RULESET_VERSION,
    redact_audit_records,
)

# The registered capability this module dispatches to read the log. Named once
# so a registry rename is one edit rather than a literal drifting out of step.
_AUDIT_CAPABILITY = "get_audit_log"

# The document's SHAPE. Separate from ``REDACTION_RULESET_VERSION``, which
# versions what is REMOVED, because the two change for unrelated reasons and a
# consumer needs to know which moved: a new section here is a parsing concern,
# a bumped ruleset is a sensitivity concern. Merging them would make a
# cosmetic re-layout look like a redaction change and vice versa.
BUNDLE_FORMAT_VERSION = 1

_WHAT_WAS_REMOVED = (
    "Project names, design names, and the project's absolute filesystem path.",
    "Setup, sweep, and solution-type names.",
    "All variation variable names and values. These are parametric dimensions "
    "— geometry, not just identity — and Point 21 excludes geometry.",
    "The variation hash: not a name, but a stable handle that would correlate "
    "two bundles from the same design.",
    "Every dispatch argument, including the project or design name passed to "
    "select. Argument KEY names were dropped with their values, because a key "
    "called (for example) customer_reference discloses a concept even empty.",
    "snapshot_id.",
    "Any tool name the capability registry does not declare. The broker "
    "records an unregistered dispatch under the name it was handed, verbatim, "
    "so that name is caller-controlled text; it is replaced with "
    "'<unregistered>'. The outcome field still says unknown_capability.",
    "The audit log's own prose summary, which is unaudited free text; the "
    "structured completeness flags below carry the same facts.",
)

_WHAT_WAS_KEPT = (
    "timestamp — call ordering, and correlating a failure with a solve.",
    "tool_name — which tool broke. Registry-declared names only.",
    "risk_tier — which guard set the call ran under.",
    "outcome — whether each call succeeded, was refused, or failed. This is "
    "the only persisted error trail in this software.",
    "duration — timeouts, hangs, and watchdog abandonment show up here.",
    "session_degraded — whether a call worsened the AEDT session.",
    "selection_present — WHETHER each selection stage was set when a call "
    "ran, never which project, design, setup, sweep, or variation it was.",
    "arguments_dropped — how many argument keys were removed, so the "
    "redaction is visible rather than invisible.",
    "The whole preflight report: version numbers and component verdicts. "
    "These carry no identifier by construction — the AEDT version is rebuilt "
    "from integers, and installed-version detection reads environment "
    "variable NAMES only, never their values.",
)

_WHAT_THIS_DOES_NOT_GUARANTEE = (
    "READ THIS BEFORE SENDING. What follows is what remains true after every "
    "rule above has been applied.",
    "Timestamps reveal when you work, and therefore your working hours and "
    "your time zone.",
    "The sequence of tool calls is a workflow fingerprint: the order and "
    "rhythm of what you do is characteristic even with every name removed.",
    "Two bundles from the same organisation are correlatable on those "
    "patterns, even though neither names anything.",
    "The selection presence map carries a pattern of its own. A log in which "
    "every record reads project/design/setup/sweep/variation all true says "
    "that this user runs complete, solved, variation-swept designs. Composed "
    "with duration it says more: all-true rows with multi-second durations "
    "say that this shop solves large models. That is weaker than a name and "
    "it is not nothing.",
    "The guarantee is bounded by its own construction. 'We removed the "
    "identifiers this ruleset knows how to name' is not 'this file is "
    "anonymous', and no redaction pass can make the second claim. If the "
    "contents of this file would matter in the wrong hands, judge it by "
    "reading it — that is why it is written to be readable.",
)

_WHAT_WAS_NEVER_COLLECTED = (
    "Geometry, field data, materials, and design notes. Never read, so never "
    "redacted — not collecting is a stronger protection than removing.",
    "The design itself, any solver message, any inspection read-out, and any "
    "solved S-parameter data.",
    "The design-intent file, including any target frequency or threshold.",
    "Environment variable VALUES. The installed-AEDT scan returns variable "
    "NAMES only, so a licence server address or an API token in your "
    "environment never entered this program's view of it in the first place.",
    "Stack traces — and their absence is not redaction. This software records "
    "none: there is no logging and no traceback capture anywhere in it, so "
    "there were none to include.",
    "The record of the audit-log read that produced this bundle. That record "
    "is appended after the read returns, so it is never in the log the read "
    "returned.",
)


class DiagnosticsBundleError(Exception):
    """The bundle could not be assembled honestly, so nothing is written.

    RAISED, NOT RETURNED, and forced by the contract exactly as it is for the
    three Layer-4 siblings. ``ExportResult``'s arms are written, refused,
    failed mid-write, and ``CannotEvaluate``; none can say "the audit dispatch
    did not return an audit log". Borrowing ``CannotEvaluate`` would blame
    PyAEDT for a wrapper-side problem, which is the misattribution ADR-16
    narrowed that type to prevent.

    WHY THIS EXISTS WHEN ``preflight_environment`` DELIBERATELY HAS NO SUCH
    CLASS. That function has one arm, total probes, and no dispatch boundary,
    so there is no failure left for an exception to carry. This module HAS a
    dispatch boundary — ``get_audit_log`` can come back as an
    ``UnknownCapability``, a ``DispatchRefused``, or an ``AuditFailure`` — and
    that is precisely the boundary W-5, W-6 and W-7 each define an assembly
    error for. The difference is the boundary, not a change of mind.
    """


def build_diagnostics_bundle(
    probes: EnvironmentProbes,
    known_tool_names: Iterable[str],
    broker: Broker,
) -> str:
    """The bundle as a JSON document, ready to write.

    Args:
        probes: the four machine reads, injected (see ``EnvironmentProbes``).
        known_tool_names: the names the capability registry declares, supplied
            by the site that BUILT the registry. Passed as data for the reason
            ``redaction`` takes them that way — and because reaching into a
            broker for them would mean either a new public accessor on W-4 or a
            private-attribute read, and neither belongs in a step that builds
            W-11.
        broker: required here, unlike in ``preflight_environment``, because the
            audit log can only be reached by dispatch.

    READING THE LOG NECESSARILY WRITES ONE. There is no non-dispatchable
    accessor for the audit log and there may not be: the broker's own
    control-plane rule requires an accessor to trigger "no external-program
    work (no AEDT, no disk, no network)", and reading the log is disk work. So
    this goes through ``dispatch``, which appends a record for the read. That
    record is appended AFTER the handler returns, so it is never in the log
    this bundle contains — stated in the bundle's own "never collected"
    section rather than left for a reader to notice.

    Raises:
        DiagnosticsBundleError: if the audit dispatch did not return a log.
    """
    report = preflight_environment(probes, broker)
    audit = _audit_log(broker)
    document = {
        "bundle_format_version": BUNDLE_FORMAT_VERSION,
        "redaction_ruleset_version": REDACTION_RULESET_VERSION,
        "preflight": report.model_dump(mode="json"),
        "audit": {
            "record_count": len(audit.records),
            "torn_tail": audit.torn_tail,
            "corrupt_lines": list(audit.corrupt_lines),
            "records": redact_audit_records(audit.records, known_tool_names),
        },
        "what_was_removed": list(_WHAT_WAS_REMOVED),
        "what_was_kept": list(_WHAT_WAS_KEPT),
        "what_this_does_not_guarantee": list(_WHAT_THIS_DOES_NOT_GUARANTEE),
        "what_was_never_collected": list(_WHAT_WAS_NEVER_COLLECTED),
    }
    # ``ensure_ascii=False`` so a non-ASCII character in a version string reads
    # as itself rather than as an escape: this file is meant to be read by a
    # person before they send it, and \u-escaped text is not readable.
    # Trailing newline so the file ends the way every other text artifact this
    # repo writes does.
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def export_diagnostics_bundle(
    path: str,
    probes: EnvironmentProbes,
    known_tool_names: Iterable[str],
    broker: Broker,
    *,
    overwrite: bool = False,
) -> ExportResult:
    """Build the bundle and write it through the broker's guarded primitive.

    Returns ``ExportWritten`` or ``ExportRefused`` from the broker VERBATIM —
    this module constructs neither, so the no-silent-overwrite guarantee stays
    the broker's single claim rather than being restated here.
    """
    payload = build_diagnostics_bundle(probes, known_tool_names, broker)
    try:
        return broker.write_export(path, payload, overwrite=overwrite)
    except BrokerFileError as exc:
        # A KNOWING, DOCUMENTED MISLABEL, AND ITS SCOPE IS THE POINT OF THIS
        # COMMENT.
        #
        # ``BrokerFileError`` is raised for TWO different things: a path
        # validation that refused before the disk was touched, and a write that
        # broke mid-operation. Those are ``ExportRefused`` and ``ExportFailed``
        # respectively — and the exception carries NO DISCRIMINATOR between
        # them. It has ``path``, ``reason`` and ``orphaned_temp``, and
        # ``orphaned_temp is None`` covers both a refusal and a failure that
        # died before its temp existed. So the two cannot be told apart here.
        #
        # ``ExportFailed`` is chosen because it is the safer of the two wrong
        # answers. Reporting ``ExportRefused`` — "declined before touching the
        # disk" — when a temp file WAS left behind would silently defeat the
        # one field that exists to stop a stray file being invisible. The
        # reverse error costs a caller an inaccurate label on a path they must
        # fix anyway.
        #
        # THIS DOES NOT GENERALISE, AND THE NEXT PERSON MUST NOT EXTEND IT. The
        # mislabel is correct ONLY because this exception type carries no
        # discriminator. An error type that CAN distinguish its cases must be
        # mapped case by case; collapsing a discriminated error into one arm
        # "for consistency with this" would be inventing an escape path from a
        # precedent that was never about consistency. (Step 2.3 has the
        # cautionary version: a raise authorised because a gate made a
        # condition unreachable, then extended to a sibling condition no gate
        # covered.) The real fix is contract gap 2's code half, whose
        # destination is Step 3.4 — not a wider reading of this comment.
        return ExportFailed(
            outcome="write_failed",
            path=exc.path,
            reason=exc.reason,
            orphaned_temp=exc.orphaned_temp,
            template_text=_write_failure_text(exc),
        )


def _audit_log(broker: Broker) -> AuditLog:
    """The whole audit log, via dispatch, narrowed to its declared type.

    ``dispatch`` is typed ``-> object``, so the result is CHECKED rather than
    assumed, following W-5 and W-6. Anything that is not an ``AuditLog`` is a
    dispatch-boundary failure — an unregistered capability, a tier refusal, a
    sink that could not write — and none of those is a reason to write a
    bundle with an empty or partial call history, which would read as "this
    machine has done nothing" rather than "the history could not be read".
    """
    result = broker.dispatch(_AUDIT_CAPABILITY)
    if not isinstance(result, AuditLog):
        raise DiagnosticsBundleError(
            f"dispatching '{_AUDIT_CAPABILITY}' returned a "
            f"{type(result).__name__} rather than an audit log, so the call "
            "history could not be read. No bundle is written: a bundle with a "
            "silently empty history would read as a machine that has done "
            "nothing, which is a different and false claim."
        )
    return result


def _write_failure_text(exc: BrokerFileError) -> str:
    """Deterministic failure wording, naming an orphaned temp when there is one.

    The orphan is stated because no deletion path exists anywhere in this
    codebase, so a file left behind on the user's disk is only ever visible if
    something says so.
    """
    text = f'The diagnostics bundle was not written to "{exc.path}": {exc.reason}.'
    if exc.orphaned_temp is not None:
        text += (
            f' A temporary file remains at "{exc.orphaned_temp}"; it was not '
            "removed, and you may delete it yourself."
        )
    return text


def preflight_report_for_bundle(
    probes: EnvironmentProbes, broker: Broker
) -> PreflightReport:
    """The report the bundle embeds, exposed for callers that want both.

    A convenience over ``preflight_environment`` with no logic of its own: the
    Step 3.x tool surface returns a report AND writes a bundle, and building
    the report twice would let the two disagree if the machine changed between
    them.
    """
    return preflight_environment(probes, broker)
