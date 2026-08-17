"""W-10 · findings — receipt validation, attribution, sanitization.

Validates every finding the engine returns against the findings schema and
rejects malformed or evidence-incomplete findings as protocol errors; refuses any
finding carrying an object rather than a value in either of the two fields
pydantic does not validate; merges gate and engine findings with per-finding
source attribution; and frames every untrusted string it hands on as data.

THE ENVELOPE IS FOUR CLAUSES WITH FOUR DIFFERENT ANSWERS HERE, and stating them
separately is the whole of Part 4 -- an envelope that looks like all four and
does one would be worse than none. §6.6 requires untrusted strings to be (a)
carried in fields typed as untrusted, (b) length-capped and control-character
stripped ON READ IN THE ADAPTER, (c) rendered inside explicit data delimiters,
and (d) never allowed to influence control flow.

  (a) THE CONTRACT'S. Satisfied except at the one place recorded at the end of
      this docstring, which is a gap with no runtime effect.
  (b) THE ADAPTER'S, in §6.6's own words, and MEASURED to be done: a hostile
      project name driven through the real path (fake adapter -> session ->
      ``assemble_snapshot`` -> ``evaluate_gates``) reaches a gate finding with
      ESC, BEL and NUL already removed and its instruction text intact, and an
      over-length setup name arrives capped and marked. On a gate finding the
      only fields carrying HFSS text are SIX, all on ``provenance``: the five
      selection names, PLUS ``provenance.variation.values``, whose keys and
      values are the design's own variable names and settings and are read from
      HFSS exactly as the five are (``adapter/real/real_adapter.py`` builds them;
      ``sanitize_result`` recurses into nested models, so they arrive stripped
      and capped like everything else). The count said FIVE until the variation
      was walked -- the conclusion is unchanged, but this paragraph's whole
      weight is that it is a claim about SURFACE, and a surface enumeration that
      misses a carrier is worth correcting even when the carrier is clean. None
      of the eleven free-text fields on ``Finding`` itself carries any. THIS
      PACKAGE ADDS NO CAPPING AND NO STRIPPING, on either
      stream. Not as an exemption -- there is no branch on source anywhere in the
      accept-or-refuse path or in the renderer, so there is no source for which a
      requirement could be relaxed. It is that ``sanitize_str`` and
      ``MAX_UNTRUSTED_STR_LEN`` live in ``hfss_agent.adapter.sanitize``, which
      Layer 6 may not import, and a hand-rolled second stripper with an invented
      cap would be a second enforcement point drifting from the first -- the
      shape ``validate_native/assembler.py`` refused one layer closer to the
      constant: "Naming a number we cannot read would be worse than not naming
      it."
  (c) THIS PACKAGE'S, and it is what ``render.py`` builds. Engine-authored text
      never came through the adapter and has had nothing removed from it; framing
      it as data, attributed, is the remedy §6.6 actually prescribes and the one
      ``adapter/sanitize`` describes as neutralizing "by framing/typing ... never
      by rewriting".
  (d) A PROPERTY OF THIS PACKAGE, PROVEN RATHER THAN IMPLEMENTED -- see below.

CLAUSE (d), STATED NARROWLY ENOUGH TO BE TRUE. The tempting claim is "no
untrusted string reaches a branch anywhere in this package", and it is FALSE:
``merge._id_anomalies`` tests ``finding_id.strip()`` for blankness, the evidence
rules test the same of their fields, and ``receipt._schema_detail`` tests an
engine-chosen field name for membership in ``Finding.model_fields``. The true
claim is §6.6(d)'s own list: NO UNTRUSTED STRING SELECTS A TOOL, A TIER, A FILE
PATH, OR ANY CODE PATH REACHING A CAPABILITY. The three branches that do read
untrusted strings read only BLANKNESS -- never what a string says -- or test
membership in a wrapper-owned allow-list whose polarity can only ever REMOVE
engine text from output. That is asserted behaviourally by
``tests/findings/test_untrusted_strings.py``; the STRUCTURAL form of the same
property is Part 7's audit and is a different claim, not a second copy of this
one (behavioural says a decision did not change on these inputs; structural says
no such decision exists to change).

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

WHERE A REJECTION IS SURFACED TO A USER -- a boundary worth stating, because the
runbook's Done bar describes rejected findings as "not displayed", and the answer
has two halves that sound like one.

THIS PACKAGE DOES OWN A DISPLAY, SINCE PART 4. ``render.findings_template_text``
is it, and it surfaces refusals rather than hiding them: a count on the first
line, then one entry per refusal carrying the stream it arrived on, its position,
its wrapper-authored reason and detail, and its claimed ``finding_id`` verbatim,
under a heading saying they were NOT shown above. That is framed data and it is
deliberate -- a refusal a reader cannot see is a refusal nobody acts on. WHAT IS
NOT DISPLAYED IS THE REFUSED FINDING ITSELF: none of its own text reaches the
paragraph, only the wrapper's account of why it did not travel.

(THIS PARAGRAPH SAID THE OPPOSITE -- "It does not, and cannot" own a display --
and went on to assign "whether a refusal count reaches a user at all" to Step
3.3. Part 4 landed the renderer eighty lines below the claim, in this same file,
and neither sentence was revisited. It also cited "this module's own first
paragraph" for the words "never displayed", which that paragraph does not contain
and may never have. Recorded rather than silently corrected, because a docstring
that was confidently wrong about its own module is the thing this package's
review convention exists to catch.)

WHAT THIS PACKAGE DOES NOT OWN IS THE TOOL RESPONSE. Nothing in ``src/``
constructs a ``tool_io.ValidationReport`` today; that type declares exactly
``native``, ``findings``, ``engine_status`` and ``template_text`` under
``extra="forbid"``, and no contract type anywhere can carry a rejection or the
reason for one. So Step 3.3 decides whether this paragraph is composed into a
response at all -- and if it is, the refusal count and the refusal list travel
with it, because they are part of the paragraph and not a separate switch.

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
from hfss_agent.findings.render import findings_template_text
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
    # §6.6 clause (c): the deterministic findings paragraph, with every untrusted
    # string framed as data. PUBLIC BUT UNCALLED IN ``src/`` until Step 3.3
    # composes it -- the same deliberate trade ``native_template_text`` and
    # ``touchstone_port_count`` already make, for the same reason.
    "findings_template_text",
    # W-10's own result types. LOCAL, NOT CONTRACT -- see the module docstring
    "FindingReceipt",
    "RejectedFinding",
    "RejectionReason",
]
