"""W-10 · findings — receipt validation, attribution, sanitization.

Validates every finding the engine returns against the findings schema and
rejects malformed or evidence-incomplete findings as protocol errors; refuses any
finding carrying an object rather than a value in either of the two fields
pydantic does not validate; merges gate and engine findings with per-finding
source attribution; applies the untrusted-string envelope to every HFSS-sourced
string.

Native HFSS validation does NOT pass through here (ADR-23). It is not a
``Finding``, it never enters the merge, and W-6 delivers it as its own
structural block. That is what makes the rejection gate above UNCONDITIONAL
rather than a check with a native-shaped hole in it: there is no source for
which the requirement could be relaxed, so there is no branch to write and none
to forget.

THE FIELD COUNTS, MEASURED, because the runbook uses two phrasings in one
paragraph and a reader will meet both. ``Finding`` declares SEVENTEEN fields, of
which SIXTEEN are required (``suggested_action`` is the one optional). The
"seven-field" phrasing names the seven NUMBERED EVIDENCE fields -- ``inspected``,
``observed_values``, ``calculation_ref``, ``reason_flagged``, ``rule_version``,
``classification``, ``limitations_and_assumptions`` -- which are a subset of the
sixteen, marked ``# field 1`` .. ``# field 7`` at their declarations. There is no
separate seven-field schema to validate against: validating against ``Finding``
validates all sixteen, which is strictly stronger.

WHERE A REJECTION IS SURFACED TO A USER -- a boundary worth stating, because both
the runbook's Done bar and this module's own first paragraph describe rejected
findings as "never displayed", which reads as though this module owned a display.
It does not, and cannot: nothing in ``src/`` constructs a
``tool_io.ValidationReport`` today, that type declares exactly ``native``,
``findings``, ``engine_status`` and ``template_text`` under ``extra="forbid"``,
and no contract type anywhere can carry a rejection or the reason for one. That
response is Step 3.3's, and so is the decision about whether a refusal count
reaches a user at all.

So the refusals live here as ``FindingReceipt.rejected``: a local frozen
dataclass, complete, machine-readable, and Step 3.3's to compose with. It is here
rather than in Step 3.3 because the commitments it has to keep -- that a refusal
never carries the offending object, that its reason is wrapper-authored, that
identity is positional rather than read off an unvalidated input -- are
properties of the gate, and this is the module that owns the gate and has the
fixtures to test it against. Until Step 3.3 lands it is read only by this
module's tests; that is a deliberate trade, not an oversight.

BUILDING THE FIELD NOW WAS CONSIDERED AND REFUSED. Adding ``rejections`` to
``ValidationReport`` at this step would have been a version event on a type with
no producer at all -- ADR-30 dec. 3's "the slot then advertises a capability that
does not exist", one level further out than usual, since there it is a field
nobody fills and here it would be a field on a type nobody builds. The precedent
runs the same way: ``broker/audit/reader.py`` shipped ``torn_tail`` and
``corrupt_lines`` on its own local ``AuditReadResult`` at Step 1.4 while
``AuditLog`` had no field for either, and the contract caught up at the later
amendment that surfaced them on the response. When it lands there it is a PACKAGE
version event and not a ``CONTRACT_VERSION`` one: ``tool_io`` is not reachable
FROM ``DesignSnapshot`` or ``Finding`` and carries no ``contract_version``, so
both clauses of ``contract/common.py``'s version rule fail.

CONTRACT GAP, RECORDED AND NOT FIXED HERE (§6.6 clause (a)).
``FindingProvenance.solution_type``, ``.setup`` and ``.sweep`` are declared plain
``str`` while ``.project`` and ``.design`` are ``UntrustedStr``, although all five
are HFSS-sourced names arriving from the same adapter read via ``Selection``.
§6.6 requires untrusted strings to be "carried in dedicated schema fields typed
as untrusted", and three of the five are not. It is recorded rather than fixed
because it changes NOTHING this module can do: ``UntrustedStr`` IS ``str``
(``contract/common.py``), so all five resolve to bare ``str`` with empty metadata
at runtime and no consumer can discriminate on the annotation -- measured, not
assumed. This module's envelope must therefore work by FIELD NAME regardless of
how the gap is resolved. Fixing it would fire the first clause of the version
rule (``FindingProvenance`` is reachable from ``Finding``) for a change with zero
wire or validation effect, so it belongs to the next amendment that moves for a
reason of its own -- the way Step 1.4 banked ten gaps for the Step 2.1 amendment.
"""

from hfss_agent.findings.merge import ENGINE_STREAM, GATE_STREAM, merge_findings
from hfss_agent.findings.receipt import (
    ANY_TYPED_FIELDS,
    EVIDENCE_FIELDS,
    INERT_LEAF_TYPES,
    validate_finding,
)
from hfss_agent.findings.results import (
    FindingReceipt,
    RejectedFinding,
    RejectionReason,
)

__all__ = [
    # The entry point, and the two stream labels a caller needs to read a refusal
    "merge_findings",
    "GATE_STREAM",
    "ENGINE_STREAM",
    # The receipt gate, public because it is the unit the rejection tests drive
    # directly and because Part 2's evidence check extends it
    "validate_finding",
    # WHICH fields the evidence gate requires content in. Exported rather than
    # kept private for the reason ``GATE_OUTCOMES_THAT_QUALIFY_COMPUTATION`` is:
    # it is a decision, and a consumer or a test comparing against it must read
    # the SAME list the gate enforces rather than a second copy of it.
    "EVIDENCE_FIELDS",
    # WHICH fields carry values pydantic does not validate, and WHICH types may
    # travel in them. Exported for the identical reason: both are decisions, and
    # the calibration test that proves the wrapper's own output survives the walk
    # must compare against the tuples the walk actually enforces. A test carrying
    # its own copy of the allow-list would pass while the gate refused everything.
    "ANY_TYPED_FIELDS",
    "INERT_LEAF_TYPES",
    # W-10's own result types. LOCAL, NOT CONTRACT -- see the module docstring
    "FindingReceipt",
    "RejectedFinding",
    "RejectionReason",
]
