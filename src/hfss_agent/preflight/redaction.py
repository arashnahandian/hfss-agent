"""W-11 diagnostics redaction: audit records made safe to send (spec Point 21).

THIS IS THE "SANITIZED" THAT MEANS DISCLOSURE, not the one that means
injection. ``preflight/__init__.py`` sets the two apart at length; the short
form is that ``adapter.sanitize`` strips control characters and removes no
identity whatsoever, so a record that has been through it still spells a
customer's project name exactly as HFSS spelled it. This module is what makes
the difference.

THERE IS NO BACKSTOP BELOW THIS ONE, AND THAT SHAPES EVERY DECISION HERE. A
wrong ``overall`` raises a contract validator; a probe that fails is caught by
totality. A redaction miss is caught by nobody: the bundle is a file the user
emails to a support channel, nothing downstream inspects it, and the failure is
silent and in someone else's inbox. So the rules below fail toward dropping
data, and the diagnostic cost of that is accepted deliberately.

TWO MECHANISMS, WITH OPPOSITE DEFAULTS, AND CONFLATING THEM IS HOW THIS GOES
WRONG:

  * ``selection_state`` has SEVEN FIXED KEYS, pinned by ``AuditRecord``'s
    docstring and verified there by driving a real dispatch. A per-key policy
    over a known key set is total by construction, so this one is a fixed-key
    rule and every value is replaced by a presence bool.
  * ``sanitized_arguments`` has VARIABLE keys — ``stage``, ``choice`` and
    ``process_id`` today, whatever a future capability declares tomorrow. A
    deny-list here fails the day someone registers a tool taking
    ``customer_reference``, so this one is an ALLOW-LIST that drops by default.
    A key nobody has reviewed is omitted, and the cost is a diagnostic gap
    rather than a disclosure.

KEY-BASED IS LOAD-BEARING; KNOWN-VALUE MATCHING IS NOT USED AT ALL. The
tempting alternative — scrub the current project's name out of the text — fails
hardest exactly when the bundle matters most. It is built from the CURRENT
selection, and a bundle is most often produced pre-attach or after a failure,
when the chain is empty: the matcher then has zero values to match and redacts
NOTHING, while the log still names every project the user has ever opened. It
is also worse than incomplete, it is actively damaging: a design legitimately
named ``ok`` would have a value-matcher rewriting that substring throughout,
corrupting the ``outcome`` field of every record in the log. Active damage
beats incompleteness as a reason to refuse a mechanism.

SO THIS MODULE PERFORMS NO STRING SURGERY, AND THAT IS A DESIGN PROPERTY RATHER
THAN AN ACCIDENT. Everything below is dict reconstruction and attribute reads.
A maintainer adding a value-matcher later will reach for ``value.replace(name,
"<redacted>")`` and will be stopped by CI:
``tests/boundary/test_file_io_audit.py`` flags ``.replace`` on ANY receiver as
an ``ast.Attribute``, because ``Path.replace`` (which overwrites a file) and
``str.replace`` are indistinguishable in an AST. That over-breadth is
deliberate, documented there, and pinned by its own self-test. If a string
rewrite ever is genuinely needed, the legal idioms are
``"<new>".join(text.split("<old>"))`` (the ``metrics/export.py::_csv_field``
precedent), ``re.sub``, or ``str.translate`` — and the audit is not the thing to
change.

IMPORT-LIGHT AND BROKER-FREE ON PURPOSE. This module imports ``contract`` and
the standard library, nothing else. In particular it does NOT reach the
capability registry to learn which tool names are real — that arrives as data
(see ``redact_audit_record``), which keeps the redactor a pure function of its
inputs and testable with no broker, no session, and no adapter anywhere near it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from hfss_agent.contract import AuditRecord

# Bumped on ANY change to what is kept or dropped below. Emitted into the
# bundle so a file produced by an older, more permissive ruleset is never
# mistaken for one produced by a stricter one — a support engineer reading
# version 1 in a world where 3 is current must know to treat the file as MORE
# sensitive, not less. An integer, not semver: there is no meaningful
# "backwards-compatible" change to a redaction rule.
REDACTION_RULESET_VERSION = 1

# What replaces a tool name that is not in the caller-supplied registry.
UNREGISTERED_TOOL_NAME = "<unregistered>"

# THE KEEP-LIST: the ``AuditRecord`` fields that survive verbatim, by name.
# Everything not named here is dropped, including any field added to the schema
# after this list was written — see ``redact_audit_record``.
#
# Each survivor is a closed vocabulary, a number, or a bool, so none can carry a
# name, a path, or a dimension:
#
#   * ``timestamp``        ordering, and correlating a failure with a solve;
#   * ``tool_name``        which tool broke — GUARDED, see ``_tool_name``;
#   * ``risk_tier``        3-value literal: which guard set the call ran under;
#   * ``outcome``          5-value literal, and the ONLY persisted error trail
#                          in this codebase (nothing here records a traceback);
#   * ``duration``         timeouts, hangs, watchdog abandonment;
#   * ``session_degraded`` whether this call worsened the session.
#
# TWO FIELDS A READER WILL EXPECT AND NOT FIND, both deliberate:
#
#   * ``sanitized_arguments`` — dropped; ``select``'s ``choice`` IS a project
#     or design name. See ``_arguments``.
#   * ``snapshot_id`` — dropped, and it costs nothing today: the broker passes
#     ``snapshot_id=None`` for every capability on the current surface, so it
#     is a survivor by vacuity. Its future content is undecided — whether the
#     id will be a content hash of a design is not yet settled — and ADMITTING
#     A FIELD BECAUSE IT IS CURRENTLY ALWAYS NULL IS HOW AN ALLOW-LIST ROTS. If
#     the fact is ever needed, a bool "a snapshot was emitted" carries it
#     without the id.
SURVIVING_FIELDS: tuple[str, ...] = (
    "timestamp",
    "tool_name",
    "risk_tier",
    "outcome",
    "duration",
    "session_degraded",
)

# ``selection_state``'s seven keys, in the order ``AuditRecord``'s docstring
# lists them. Iterating THIS rather than the record's own dict is the second
# line of the fixed-key rule: a key that should not be there is not carried
# across, it is simply never looked at.
SELECTION_KEYS: tuple[str, ...] = (
    "process_id",
    "project",
    "design",
    "solution_type",
    "setup",
    "sweep",
    "variation",
)

# The allow-list for dispatch arguments. EMPTY IN VERSION 1, and the emptiness
# is the decision rather than a placeholder: of the argument names the current
# surface uses, ``choice`` is a project/design/setup name, ``stage`` is
# recoverable from the tool name, and ``process_id`` is a PID whose diagnostic
# value does not survive the session it belonged to. Adding an entry here
# requires a written justification and bumps REDACTION_RULESET_VERSION.
ALLOWED_ARGUMENT_KEYS: frozenset[str] = frozenset()


def redact_audit_records(
    records: Sequence[AuditRecord], known_tool_names: Iterable[str]
) -> list[dict[str, object]]:
    """Every record redacted, in order. See ``redact_audit_record``."""
    known = frozenset(known_tool_names)
    return [redact_audit_record(record, known) for record in records]


def redact_audit_record(
    record: AuditRecord, known_tool_names: Iterable[str]
) -> dict[str, object]:
    """One audit record, reduced to what may leave the machine.

    Args:
        record: the record as written, already ADR-9 sanitized and therefore
            still carrying every name and path exactly as HFSS spelled them.
        known_tool_names: the names the capability registry actually holds.
            Passed as DATA rather than read from a registry, so this module
            needs no broker and no session — see the module docstring.

    Returns a plain JSON-ready ``dict``, deliberately NOT a contract model:
    there is no schema for a redacted record, and adding one would be a semver
    event on a doubly-pinned artifact for a document fragment that never
    crosses the engine seam.

    DROP-BY-DEFAULT IS THE WHOLE MECHANISM. The result is built by naming the
    fields that survive, never by copying the record and removing fields from
    it. The difference is what happens to a field added to ``AuditRecord``
    tomorrow: under this construction it is absent from the output, so the
    failure of an un-updated redactor is a missing diagnostic. Under the
    copy-and-remove shape it would be present, and the failure would be a
    disclosure.
    """
    known = frozenset(known_tool_names)
    return {
        "timestamp": record.timestamp.isoformat(),
        "tool_name": _tool_name(record, known),
        "risk_tier": record.risk_tier,
        "outcome": record.outcome,
        "duration": record.duration,
        "session_degraded": record.session_degraded,
        "selection_present": _selection_presence(record.selection_state),
        "arguments": _arguments(record.sanitized_arguments),
        "arguments_dropped": _dropped_argument_count(record.sanitized_arguments),
    }


def _tool_name(record: AuditRecord, known_tool_names: frozenset[str]) -> str:
    """The tool name if the registry holds it, else a placeholder.

    ``tool_name`` IS CALLER-CONTROLLED ON ONE PATH, which is the whole reason
    this guard exists. ``Broker.dispatch`` looks the name up and, on a miss,
    writes the record with the name it was HANDED, verbatim, paired with
    ``outcome="unknown_capability"``. So a caller — an LLM driving the tool
    surface, or a typo — can put arbitrary text into the audit log, and
    ``export_northwind_q3_report`` is a name that identifies a customer while
    looking like a tool.

    The remedy is an allow-list, matching how every other untrusted input in
    this package is handled: emit the name only when it is one the registry
    actually declares. Nothing diagnostic is lost — ``outcome`` already says
    ``unknown_capability``, which is the fact a support engineer needs; WHICH
    unregistered name was attempted is not.

    THE ONLY FUNCTION HERE THAT TAKES A STRING AND RETURNS ONE, and it still
    performs no string surgery: it selects between the input and a constant.
    The module docstring records why nothing in this file may reach for
    ``.replace`` and what to use if that ever changes.
    """
    if record.tool_name in known_tool_names:
        return record.tool_name
    return UNREGISTERED_TOOL_NAME


def _selection_presence(selection_state: Mapping[str, object]) -> dict[str, bool]:
    """The seven selection keys as WAS-IT-SET bools, never as values.

    "Was a design selected when this call ran" is the diagnostically
    load-bearing fact; WHICH design never is. So the shape is preserved and
    every value is erased.

    THIS IS ALSO WHERE THE NO-GEOMETRY RULE IS ENFORCED, which is easy to miss
    because this field looks like a pure identity problem. ``variation`` holds a
    ``Variation`` — a map of variable NAMES to VALUES, e.g.
    ``{"element_pitch_mm": "12.5"}`` — which is parametric geometry, exactly
    what spec Point 21 excludes ("no geometry, no fields"). Collapsing the whole
    value to a bool takes the dimensions with it, and takes ``variation_hash``
    too: a hash is not a name, but it is a stable handle that correlates two
    bundles from the same design.

    Also dropped here, without needing a rule of its own: the project's
    ABSOLUTE FILESYSTEM PATH, which ``selection_state["project"]`` carries and
    which names the user and often the client directory.

    THE RESIDUAL THIS LEAVES, stated because the alternative is presenting the
    presence map as costless. Seven bools carry no name, but a log in which
    every record reads project/design/setup/sweep/variation all true reveals
    that this user runs complete, solved, variation-swept designs — an
    organisational fingerprint, weaker than a name and not nothing. The
    bundle's "what this does not guarantee" section must name this alongside
    timestamps and the call sequence.

    Read through ``SELECTION_KEYS`` rather than through the record's own keys:
    a key that should not be in the dict is then never looked at, rather than
    being carried across by an iteration over whatever happens to be there.
    """
    return {key: selection_state.get(key) is not None for key in SELECTION_KEYS}


def _arguments(sanitized_arguments: Mapping[str, object]) -> dict[str, object]:
    """Dispatch arguments filtered to the allow-list — empty in version 1.

    DROP-BY-DEFAULT, and the direction is the point. ``select``'s ``choice``
    argument is a project, design, setup or sweep NAME, so the values here are
    identifying today; the deeper reason for an allow-list is tomorrow, when a
    capability declares an argument nobody has reviewed. A deny-list would ship
    that argument's value; this ships nothing until someone decides otherwise.

    KEY NAMES ARE DROPPED WITH THE VALUES, deliberately. A presence map like
    ``_selection_presence``'s was considered and rejected here: those seven keys
    are fixed and wrapper-owned, while an argument name is declared by whoever
    registers the capability, and a key called ``customer_reference`` discloses
    a concept even with its value removed.
    """
    return {
        key: value
        for key, value in sanitized_arguments.items()
        if key in ALLOWED_ARGUMENT_KEYS
    }


def _dropped_argument_count(sanitized_arguments: Mapping[str, object]) -> int:
    """How many argument keys were removed.

    A count, not a list of names — see ``_arguments``. It exists so the
    redaction is VISIBLE in the artifact rather than invisible: a reader
    deciding whether to send this file can see that something was taken out,
    which an empty ``arguments`` dict alone would not tell them (it reads as
    "this call had no arguments").
    """
    return sum(
        1 for key in sanitized_arguments if key not in ALLOWED_ARGUMENT_KEYS
    )
