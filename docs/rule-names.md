# Rule names and purposes

The published half of the supplemental rule set. System Design §1.2 (E-2)
requires that rule **names and stated purposes be public, published from the
wrapper side**, while implementations live in the separate rule engine. This
file is that publication, and it is deliberately the whole of it: a name and a
purpose per rule, and nothing about how any of them reaches a conclusion.

The engine is a separately-distributed package, and **no integration with it
exists in this repository today.** Nothing here imports, invokes, detects, or
reports on an engine; it is not a dependency, optional or otherwise. There is no
code path that can tell a caller whether one is installed, and installing
something today would not make the rules below run.

What exists is the seam they will arrive through, which is real and is most of
the contract: the versioned `DesignSnapshot` handed across it, and a `Finding`
schema whose `FindingSource` admits `engine_rule` alongside the wrapper's own
`gate`. The `validate_setup` tool that would carry an engine-presence notice is
registered as **deferred**, and whether its `engine_status` field can be answered
at all is an open judgment recorded against Step 3.3 — not a settled behaviour.

These names are published now because publishing them is a standing requirement
on this side of the seam, independent of when the other side arrives.

## The limitation, stated before the content

**This repository cannot verify these strings.** The engine is a separate
private package that this repository does not depend on, does not import, and
cannot import — that independence is the architecture, not an oversight. There
is no build step, test, or CI check here that reads the engine's constants and
compares them to the text below.

The list is therefore **maintained by hand, and can drift.** If a purpose string
is edited in the engine and not here, or here and not there, nothing detects it
and nothing fails. Read the four entries below as a faithful hand copy of the
engine's `RULE_PURPOSE` constants, which is what they are — not as a guarantee
that the engine currently says the same words. That guarantee is not available
from this side of the seam, so this document does not imply one.

The purpose strings are quoted on single unwrapped lines below, against this
project's usual wrap, so that a person auditing them against the engine can
compare a whole string at once rather than reassembling it across line breaks.

## What these rules are, and what they are not

### Supplemental to native validation, and second to it

They are **supplemental**: they add to HFSS's own validation and never replace
it, and native validation comes first. That is a design commitment of the
composed validation workflow, and the honest tense for it today is future.

**No code in this repository runs the two together yet.** The native-validation
module (W-6) is built and produces the native block from HFSS's own validator;
nothing in `src/` calls it. The `validate_setup` tool that would compose native
validation with supplemental findings is registered as **deferred**, its
composition assigned to Step 3.3. So there is at present no execution order to
enforce, and no run in which one could be observed — nor has any of this been
exercised against a live solver.

Two parts of the commitment are already real in code, and both are the schema
half rather than the runtime half. HFSS's messages are passed through without
rephrasing, filtering, ranking or judging them — W-6's stated guarantee, bounded
by a sanitization it discloses. And `ValidationReport` declares `native` before
`findings`, which fixes native-first as **block order in the serialized
response** rather than as a sort each producer must remember to apply; that
guarantee cannot constrain how a downstream renderer displays things, and it
describes a response type nothing constructs yet.

What is not settled is stated rather than smoothed over: `ValidateSetupRequest`
carries an `include_supplemental` flag, and whether it can be honoured is one of
the open judgments on the deferred tool. Read the ordering above as what the
composed workflow is committed to, not as behaviour this package performs today.

### Not the wrapper's own validity gates

They are also not the wrapper's solution-validity gates. This repository has its
own four gates under `src/hfss_agent/gating/`, each carrying its own
`RULE_PURPOSE` constant and a `gate.<name>` identifier, and those are a
different mechanism serving a different job. A reader grepping this repository
for rule purposes will find the gates, because the gates are implemented here.
The rules named below are not implemented here, which is exactly why they need
publishing.

## The V1 rules

- **`setup_exists`** — "Reports whether the setup named in the selection is present in the design's own list of analysis setups."
- **`sweep_exists_under_setup`** — "Reports whether the sweep named in the selection is present under the selected setup in the design's own sweep list."
- **`excitation_present`** — "Reports whether the design defines at least one excitation or port."
- **`target_frequency_usable`** — "Reports whether the target frequency stated in the design intent is a usable number: finite, and greater than zero."

## What a rule reports

Every rule reports **what it checked and what it did not.** The scope of a
result is stated with the result, so a reader is never left to infer how far a
conclusion reaches.

And when a rule cannot evaluate something, it says so. It does not guess, does
not fall back to a plausible answer, and does not let an absent input pass as a
negative finding. An unevaluable check is reported as unevaluable — the same
discipline the rest of this package holds itself to, applied on the other side
of the seam.

## Why V1 is small

The rule set is **V1 and deliberately small.**

A rule is included only where it is defensible as strictly deterministic. Checks
with a judgment flavour to them are excluded **on purpose, not for lack of
effort** — a check that would require weighing, estimating, or interpreting is
not made deterministic by being written down confidently, and this package does
not have a place to put a value that is neither read from HFSS nor computed by
an open formula. Four rules is what cleared that bar for V1.

Smallness here is a property of the standard, not a measure of the work. A later
version growing the set would mean more checks met the same bar, and nothing
weaker.

## Enforcement, and what is not enforced

Nothing about this file is machine-checked, and the reasons differ per claim:

- **The strings against the engine's:** not enforceable from here, permanently,
  for the reason given at the top. No test can be added that would close this,
  because closing it would require this repository to depend on the engine.
- **The rule list being complete:** not enforced. A fifth rule shipping in the
  engine without an entry here would go unpublished, silently.
- **This file's path:** not referenced by any constant in this package, unlike
  `docs/support-matrix.md`, which `PreflightReport.support_matrix_ref` pins.
  Moving or renaming this file breaks no code — and publishes nothing.

Keeping this document true is a manual step in the engine's own release
discipline. It is recorded here so that a reader knows the guarantee's shape
before relying on it.
