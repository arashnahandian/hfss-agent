"""The deterministic findings paragraph: a receipt rendered as framed data.

WHAT THIS IS FOR. §6.6 clause (c) requires untrusted strings to be "rendered
inside explicit data delimiters in all template text, quoted as data -- never
interpolated into instruction-like positions". Clauses (b) and (d) are settled
elsewhere and are settled differently, which is the whole reason this module
exists rather than a single function called "the envelope":

  * CLAUSE (b) -- length-cap and control-character strip -- is the ADAPTER'S, in
    §6.6's own words: "ON READ IN THE ADAPTER". Measured through the real path
    (fake adapter -> session -> ``assemble_snapshot`` -> ``evaluate_gates``): a
    hostile project name arrives with ESC, BEL and NUL already removed and its
    instruction text intact, and an over-length setup name arrives capped and
    carrying the truncation marker. W-10 re-doing that would be a second
    enforcement point for one rule, and it CANNOT do it anyway -- see
    ``_NO_CAP_IS_NAMED`` below.
  * CLAUSE (d) -- never influence control flow -- is a PROPERTY OF THE OTHER
    MODULES, proven rather than implemented. Nothing here is what makes it true.
  * CLAUSE (a) -- carried in fields typed as untrusted -- is the contract's, and
    ``findings/__init__`` records the one place it is unsatisfied.

So this module owns exactly clause (c), for exactly the strings that reach a
reader through W-10's own output.

A PURE ``FindingReceipt -> str`` FUNCTION, FOLLOWING ``native_template_text``.
W-6 faced the identical shape one layer down -- its wording is not a field on its
own output type, because ``template_text`` belongs to ``ValidationReport`` and
that response is Step 3.3's. The same holds here, one stream over:
``FindingReceipt`` is a frozen dataclass with four fields and no text field, and
adding one would be the version event ``findings/__init__`` already refuses.

CALLED BY NOTHING BUT THIS MODULE'S TESTS UNTIL STEP 3.3 LANDS. That is a
deliberate trade, not an oversight, and it is the same trade W-6 made for
``native_template_text`` and W-7 for ``touchstone_port_count``. The commitments
this text has to keep -- that a source label was CHECKED rather than believed,
that engine prose is framed rather than trusted, that no claim of safety is made
about it -- are properties of the RECEIPT, and this is the module that owns the
receipt and has the fixtures to test against.

WHAT STEP 3.3 OWNS AND THIS DOES NOT ATTEMPT. ``ValidationReport.template_text``
is the text for the WHOLE ``validate_setup`` response: the native paragraph
(W-6's), this findings paragraph, and the engine-status notice, composed. This
function returns one paragraph and takes no position on the order they appear in,
on whether a refusal count reaches a user at all, or on what a renderer does with
either collection -- ``findings/__init__`` records that those are Step 3.3's
decisions. It also renders nothing about the design: a finding's judgment is its
producer's, and this text neither summarises nor ranks them.
"""

from __future__ import annotations

from hfss_agent.contract import Finding
from hfss_agent.findings.results import FindingReceipt, RejectedFinding

# --- why this is not a second rendering of something already rendered --------
#
# THE OBJECTION, WRITTEN OUT BECAUSE THE NEXT READER WILL RAISE IT AND IT IS A
# GOOD ONE: every ``Finding`` already carries ``template_text``, described in the
# contract as "deterministic core text, complete without any LLM". Rendering a
# finding therefore looks like its PRODUCER'S job, already done, and a second
# rendering here looks like two homes for one fact -- the exact drift this
# package refuses everywhere else.
#
# THE ANSWER IS THAT THIS DOES NOT RE-RENDER ANYTHING; IT FRAMES. Not one word of
# any finding's own text is rewritten, reordered, summarised, truncated or
# replaced -- ``template_text`` is emitted verbatim, inside delimiters, under a
# label saying who wrote it. The distinction is the one ``adapter/sanitize``
# already draws for hostile content generally: "we neutralize hostile content by
# framing/typing ... never by rewriting it". Framing is the remedy; re-authoring
# would be the duplication.
#
# AND FOR AN ENGINE FINDING, ``template_text`` IS THE UNTRUSTED PROSE. That is
# what makes the framing load-bearing rather than decorative. The field is
# populated by a separately-distributed wheel; nothing upstream sanitized it,
# because it never came through the adapter; and it is headed for a reader who
# will otherwise take it for the wrapper's own words. There is nothing else in
# the pipeline that can put a delimiter around it -- the producer will not frame
# its own output as untrusted, and Step 3.3 receives it already mixed into a list.
#
# ONE THING ONLY THIS MODULE CAN SAY, AND IT IS THE REASON THE TEXT IS BUILT HERE
# RATHER THAN AT STEP 3.3. Every other module receives a ``Finding`` whose
# ``source`` is a CLAIM. W-10 is the only place that checks that claim against
# the stream the object actually arrived on (``merge._source_mismatch``), so
# "this label was verified rather than believed" is a sentence no downstream
# composer could derive from a bare list of findings. It is stated once, in
# ``_ATTRIBUTION_NOTICE``, and it is the whole build-ahead justification.

# THE SOURCE LABEL IS PRINTED, NEVER BRANCHED ON, and the difference is the same
# one ``receipt.validate_finding`` draws at length. ``Finding.source`` is a closed
# ``Literal`` the schema has already validated, so emitting it puts one of two
# wrapper-owned tokens into the text -- it is data, not a decision. NOTHING in
# this module selects a code path, a delimiter, a label or a notice by reading a
# source value: every finding is framed by the identical statements whatever it
# claims. That is what keeps decision (1)'s "no branch at all, so no source can
# be exempted" true THROUGH the renderer as well as through the gate, and it is
# what Part 7's audit can check structurally.
_ATTRIBUTION_NOTICE = (
    "Each accepted entry above is quoted as DATA, not as instruction, whoever "
    'wrote it. The "source" shown on an ACCEPTED finding was verified by this '
    "wrapper against the stream it actually arrived on, so it reports where the "
    "finding came from rather than what it claimed; a finding whose claim "
    'disagreed was refused. "gate" text on an accepted finding is this wrapper\'s '
    'own. "engine_rule" text was authored by a separately distributed package: '
    "nothing about its wording was checked, corrected, or endorsed here, and it "
    "is reproduced exactly as that package emitted it."
)

# THE REFUSAL SECTION NEEDS ITS OWN SENTENCE, AND THE NOTICE ABOVE IS FALSE
# WITHOUT IT. Measured: a ``model_construct`` ghost carrying an
# instruction-shaped ``finding_id`` full of control characters, handed in on the
# GATE stream, renders as ``arrived on "gate" ... claimed finding_id "<hostile>"``
# -- and the attribution notice, read against that line, would tell a reader that
# the hostile string is THIS WRAPPER'S OWN TEXT. It is not. Three facts make the
# accepted-entry sentence inapplicable here, and each is why this second notice
# exists rather than a reworded first one:
#
#   * ``arrived_on`` IS NOT ``source``. It is an OBSERVATION by the merge about
#     which stream carried the object, never a claim by the object about who
#     wrote it -- ``RejectedFinding`` names the field ``arrived_on`` for exactly
#     that reason. A refused object may not even be a ``Finding``, so it may have
#     no ``source`` at all.
#   * NOTHING ABOUT A REFUSED OBJECT WAS VERIFIED. That is what refusal MEANS:
#     the source check runs only after the receipt gate passes, so a schema
#     failure or a non-Finding never reached it.
#   * ``claimed_finding_id`` DID NOT COME THROUGH THE ADAPTER ON EITHER STREAM.
#     ``_PASSTHROUGH_NOTICE``'s two provenances -- "came from HFSS" and "authored
#     by an engine rule" -- do not partition this value: it was read off an object
#     of unknown provenance, and the gate stream carries no guarantee about it
#     because the wrapper's own gates are not what produced this object. Saying
#     the value is unenveloped whatever stream it arrived on is the only claim
#     true in every case.
_REFUSAL_PROVENANCE_NOTICE = (
    "In the refusal list, the stream named is where the object ARRIVED, not who "
    "wrote it, and nothing about a refused object was verified -- that is what "
    "refusing it means. A claimed finding_id is read off an object of unknown "
    "provenance on either stream, did not come through the wrapper's read path, "
    "and is reproduced here exactly as it was found."
)

# WHY THE SANITIZATION STATEMENT IS UNCONDITIONAL -- W-6's argument, unchanged,
# and it applies here with one clause added. Nothing in this module computes
# whether stripping or truncation actually took effect on any string, and nothing
# may: the truncation marker is not authenticatable, and a conditional notice
# would have to branch on untrusted content to decide what to say about itself,
# which is precisely what ADR-9 forbids. The added clause is that W-10 sees TWO
# provenances and cannot tell them apart by inspection -- an HFSS-sourced string
# went through the adapter and an engine-authored one did not, and both arrive
# here as plain ``str`` with no runtime marker (``UntrustedStr`` IS ``str``). So
# the notice states which strings the guarantee covers rather than claiming it for
# everything in view.
_PASSTHROUGH_NOTICE = (
    "Strings that came from HFSS were length-capped and stripped of control "
    "characters other than tab and newline when the wrapper read them, and carry "
    "a visible marker if they were truncated -- which proves nothing on its own, "
    "because any text can contain that wording verbatim. Text authored by an "
    "engine rule did not come through that path and has had nothing removed from "
    "it. This paragraph rewrites neither."
)

# THE SPOOFING WARNING, AND WHY IT IS STRONGER HERE THAN AT ITS SOURCE. W-6
# already states the general fact -- "there is no delimiter safe against
# arbitrary text, and inventing an escaping scheme would mean rewriting HFSS's
# output, which this module does not do" -- and the reason is that TAB AND
# NEWLINE SURVIVE SANITIZATION BY DESIGN: they are real structure in a multi-line
# solver message, so ``adapter/sanitize`` deliberately keeps them. A delimiter can
# therefore be spoofed by exactly the characters the adapter chose to preserve,
# which makes the hole a consequence of a correct decision rather than an
# oversight anyone can close.
#
# IT IS STRONGER HERE FOR TWO REASONS, both worth stating rather than inheriting.
# First, an engine-authored string never passed the sanitizer at all, so it may
# carry ANY control character -- not merely the two that survive by policy -- and
# a terminal escape can move a cursor, recolour, or erase, none of which a quote
# mark contains. Second, this paragraph frames MORE fields than W-6's does, so
# there is more surface on which a convincing fake entry can be constructed. The
# honest response is the same one W-6 chose: say plainly that the shape is
# presentation, and point at what is authoritative instead.
_PRESENTATION_NOTICE = (
    "The numbering, quoting and labelling above are presentation only, not a "
    "parseable structure, and they can be imitated by the text they contain -- "
    "tab and newline survive sanitization because they are real structure in a "
    "solver message, and engine text was never sanitized at all. The "
    "machine-readable answer is the FindingReceipt itself: its accepted and "
    "rejected collections, and the counts on the first line."
)

# WHAT CAN HONESTLY BE SAID ABOUT AN ACTION PROPOSAL, AND WHAT CANNOT. This is
# the field where an envelope is most tempting to overclaim, so the limit is
# stated rather than implied.
#
# WHAT IS TRUE, each measured rather than asserted: no gate ever sets it (the
# full 4,536-finding sweep produced ``None`` every time); nothing anywhere in
# ``src/`` READS it -- ``grep`` finds its declaration and one docstring mention,
# and no other line; and the broker's risk tiers are the only path to any
# execution in this package, none of which consults a finding. So a proposal
# cannot become an action by any route that exists.
#
# WHAT IS NOT TRUE, and must not be implied: that the prose is safe. Stripping
# control characters would not make a paragraph inert, and this module strips
# nothing anyway. No delimiter is safe against arbitrary text -- see
# ``_PRESENTATION_NOTICE`` -- and this field's whole PURPOSE is to propose an
# action to a reader who may act on it, which makes it the one place where
# framing protects the wrapper's data model and not the reader's judgment.
# Saying "this is now safe" about it would be worse than saying nothing.
_SUGGESTED_ACTION_NOTICE = (
    "A suggested action is a PROPOSAL by whichever rule emitted it. The wrapper "
    "did not evaluate it, cannot carry it out, and has no code path that reads "
    "it; acting on one is acting on that rule's word, not on the wrapper's."
)

# NO LENGTH CAP IS APPLIED HERE, AND NO NUMBER IS NAMED. Both halves are
# deliberate and the second is the one with a precedent behind it.
#
# NO CAP: capping would mean choosing which findings or which fields to drop,
# which is ranking, which this module does not do -- W-6's reasoning for its own
# rendering, unchanged. The length is bounded by what the producers emitted and,
# for HFSS-sourced strings only, by the adapter's per-string cap.
#
# NO NUMBER: ``MAX_UNTRUSTED_STR_LEN`` lives in ``hfss_agent.adapter.sanitize``,
# and this package may not import it -- Layer 6's grant is ``contract`` only, one
# layer stricter than the W-6 site that already refused to hardcode it: "Naming a
# number we cannot read would be worse than not naming it." So the cap is stated
# as a PROPERTY of the read ("length-capped ... with a visible marker") and never
# as a value, which stays true the day the constant moves.
#
# A COMMENT AND NOT A BINDING, deliberately. A draft of this carried
# ``_NO_CAP_IS_NAMED = None`` as an anchor for this paragraph, which is verbatim
# the shape ``gating/common.py`` already removed once: "a binding that could not
# be false, restated by a test that could not fail. The FACT is worth recording
# and the BINDING was not." What enforces this is
# ``test_the_rendering_names_no_cap_and_no_number``, which searches the rendered
# text for digits.

_NO_FINDINGS_NOTICE = (
    "No findings survived receipt, so there is nothing to show here. That is "
    "what was reported; the wrapper draws no conclusion about the design from it."
)

_ACCEPTED_HEADING = "Findings, in the order the wrapper received them:"
_REFUSED_HEADING = (
    "Refused on receipt and NOT shown above, with the wrapper's own reason:"
)


def findings_template_text(receipt: FindingReceipt) -> str:
    """The deterministic findings paragraph for one receipt (§6.6 clause (c)).

    A pure function of the receipt -- see the module docstring for why the text
    lives here rather than on ``FindingReceipt`` or at Step 3.3, what Step 3.3
    owns instead, and why framing an already-rendered ``template_text`` is not a
    second rendering of it.

    BYTE-DETERMINISTIC AND TIMESTAMP-FREE, following W-5 and W-6. The same
    receipt rendered twice produces identical bytes, so tests can pin the wording
    and a diff between two results shows only what a producer actually said
    differently. Determinism holds structurally: both collections are tuples,
    iterated in order, with no sort, dedup, set, or dict iteration on this path --
    which matters more than it looks, because a sort keyed on an engine-authored
    id would make the output depend on untrusted content.

    EVERY UNTRUSTED STRING IS FRAMED THE SAME WAY, WHATEVER ITS SOURCE. There is
    no branch on ``Finding.source`` anywhere in this module: the label is printed
    as data and never read to choose a delimiter, a notice or a code path. That
    is decision (1)'s "no branch at all, so no source can be exempted" carried
    through the renderer, and it is checkable structurally rather than by reading.

    NUMBERING IS WRAPPER-ADDED STRUCTURE DERIVED FROM LIST POSITION, never from
    content, and it earns its keep for W-6's reason: a string here may contain
    newlines -- deliberately preserved by the sanitizer, or never sanitized at
    all -- so line breaks alone cannot delimit entries.

    WHAT THIS ASSERTS ABOUT SAFETY: nothing. See ``_PRESENTATION_NOTICE`` for why
    no delimiter is safe against arbitrary text, and ``_SUGGESTED_ACTION_NOTICE``
    for the one field where that matters most. The claim this paragraph makes is
    narrow and true: every untrusted string in it is QUOTED AS DATA, ATTRIBUTED,
    and never placed in an instruction position.

    THE TWO SECTIONS ARE ATTRIBUTED SEPARATELY, because one sentence covering both
    was measured to be FALSE. An accepted finding's ``source`` was verified against
    the stream it arrived on; a refused object's was not, and could not be -- the
    source check runs only after the receipt gate passes. So a ghost carrying a
    hostile ``finding_id``, handed in on the GATE stream, would be described by an
    accepted-entry attribution as the wrapper's own text. It is not.
    ``_REFUSAL_PROVENANCE_NOTICE`` is the sentence that keeps the refusal list
    honest, and it is rendered exactly when that list is non-empty.

    Args:
        receipt: what ``merge_findings`` returned. Its ``accepted`` members are
            exact ``Finding`` objects and its ``rejected`` members carry
            wrapper-authored reasons -- both guaranteed by the gate, which is why
            this function needs no validation of its own.

    Returns:
        The paragraph. Never raises for any receipt the gate can produce.
    """
    accepted = receipt.accepted
    rejected = receipt.rejected
    parts = [
        f"{len(accepted)} finding(s) accepted, {len(rejected)} refused on receipt."
    ]
    if accepted:
        parts.append(_ACCEPTED_HEADING)
        parts.extend(
            _accepted_entry(index, finding)
            for index, finding in enumerate(accepted, 1)
        )
    else:
        parts.append(_NO_FINDINGS_NOTICE)
    if rejected:
        parts.append(_REFUSED_HEADING)
        parts.extend(
            _refusal_entry(index, refusal)
            for index, refusal in enumerate(rejected, 1)
        )
    # EACH NOTICE IS RENDERED ONLY WHERE IT HAS SOMETHING TO DESCRIBE, and the
    # conditions are STRUCTURAL rather than about content -- "is this collection
    # empty", never "what does this text say". That distinction is the whole of
    # W-6's rule against conditional disclosure: what may not be computed is
    # whether stripping or truncation TOOK EFFECT on a payload, because deciding
    # that means branching on untrusted content to choose what to say about
    # itself. Asking whether there is a payload at all is not that question, and
    # W-6 asks it too (``if messages:``).
    #
    # WITHOUT THIS, AN EMPTY RECEIPT RENDERS THREE PARAGRAPHS ABOUT ENTRIES THAT
    # DO NOT EXIST -- "each accepted entry above", "the numbering above", a
    # sanitization statement covering no strings. Absurd rather than merely
    # verbose, and it teaches a reader that the notices are boilerplate to skip,
    # which is the cost the disclosure exists to avoid. Step 3.3 reaches the empty
    # receipt whenever the gates could not run and no engine is installed, so it
    # is an ordinary path and not an edge case.
    if accepted:
        parts.append(_ATTRIBUTION_NOTICE)
    if rejected:
        parts.append(_REFUSAL_PROVENANCE_NOTICE)
    if accepted or rejected:
        parts.append(_PASSTHROUGH_NOTICE)
    # Rendered when any accepted finding carries one. The test is ``is not None``
    # -- a structural question about whether the optional field is set, exactly as
    # above -- and never a question about what the text says.
    if any(finding.suggested_action is not None for finding in accepted):
        parts.append(_SUGGESTED_ACTION_NOTICE)
    if accepted or rejected:
        parts.append(_PRESENTATION_NOTICE)
    # Newline-joined, not space-joined: a finding list IS a list, and flattening
    # it onto one line would misrepresent its shape (W-6's reasoning for the same
    # choice).
    return "\n".join(parts)


def _accepted_entry(index: int, finding: Finding) -> str:
    """One accepted finding, framed. Emits producer text verbatim, quoted.

    FOUR FIELDS, NOT ELEVEN, and the selection is a decision rather than an
    accident of what seemed useful. ``Finding`` carries eleven free-text fields,
    and rendering all of them would reproduce the whole object as prose -- which
    is what ``FindingReceipt`` already is, machine-readably, and what
    ``_PRESENTATION_NOTICE`` points a consumer at. What a READER needs is who
    said it, what they concluded, and the producer's own sentence about it:

      * ``finding_id`` and ``rule_id`` -- identity, so a reader can refer to the
        finding at all. UNTRUSTED on the engine stream and framed accordingly.
      * ``outcome`` -- a closed ``Literal``, so it is one of five wrapper-owned
        tokens and needs no framing; it is what the finding actually concluded.
      * ``template_text`` -- the producer's own deterministic sentence, described
        by the contract as "complete without any LLM". This is the content.
      * ``suggested_action`` -- only when set, under its own label. See
        ``_SUGGESTED_ACTION_NOTICE`` for the limit stated about it.

    ``observed_values``, ``inspected``, ``applicability`` and ``provenance`` are
    deliberately NOT rendered: they are evidence a machine reads, they are already
    on the receipt in full, and prose is the wrong shape for them. Omitting them
    from a paragraph is not withholding them from a consumer.
    """
    lines = [
        f'[{index}] source="{finding.source}" outcome="{finding.outcome}" '
        f'finding_id="{finding.finding_id}" rule_id="{finding.rule_id}"',
        f'    text: "{finding.template_text}"',
    ]
    if finding.suggested_action is not None:
        lines.append(f'    suggested action (a proposal): "{finding.suggested_action}"')
    return "\n".join(lines)


def _refusal_entry(index: int, refusal: RejectedFinding) -> str:
    """One refusal, framed -- and the one place W-10's own record carries
    untrusted text.

    THREE OF THE FOUR VALUES HERE ARE WRAPPER-AUTHORED and need no framing:
    ``arrived_on`` is a closed ``Literal``, ``position`` is an integer this
    wrapper counted, and ``reason`` is one of five members of a local
    ``Literal``. ``detail`` is wrapper-authored prose by construction -- every
    refusal detail in ``receipt.py`` is this package's own sentence, pydantic's
    closed error vocabulary, or a ``Finding``-declared field name -- and it is
    deliberately NOT quoted here, because quoting our own text as data would
    suggest it is somebody else's.

    ``claimed_finding_id`` IS THE EXCEPTION, and it is the field Part 1 named
    when it wrote ``test_an_untrusted_finding_id_survives_verbatim_today``. It is
    read off an object of unknown provenance, it is often absent, and it is
    carried on the record VERBATIM -- control characters and instruction-shaped
    text included, because W-10 strips nothing (see the module docstring). This
    line is where that value stops being raw data and becomes framed data: quoted,
    labelled as claimed rather than verified, and never placed in an instruction
    position. ``None`` renders as the wrapper's own words, not as an empty quote,
    so "unreadable" cannot be confused with "an empty string was claimed".
    """
    claimed = refusal.claimed_finding_id
    identity = (
        "no readable finding_id"
        if claimed is None
        else f'claimed finding_id "{claimed}"'
    )
    return (
        f'[{index}] arrived on "{refusal.arrived_on}" at position '
        f"{refusal.position}, {identity} -- refused as {refusal.reason}. "
        f"{refusal.detail}"
    )
