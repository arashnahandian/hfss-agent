"""W-8 assembly: the ``DesignSnapshot`` builder (System Design §1.1, ADR-28).

Layer 5 (§5): imports ``contract`` ONLY — the layer number reflects ASSEMBLY
order, not imports (corrected ADR-28). W-8 EVALUATES NOTHING and CALLS NOTHING.
It receives the upstream outputs as data and composes them; the composition
itself — reading a session, dispatching through a broker, deciding what to read
first — belongs to the server layer, which is the only place that can hold both
a broker and this module.

TAKES NO BROKER, AND THE REASON DIFFERS FROM W-7'S. W-7 also takes none, but for
a correctness reason about gate provenance (see its module docstring); it is
*permitted* a broker by §5 and declines one. W-8 is not permitted one at all.
That is the whole content of the contract-only grant: a module whose output
crosses the wrapper->engine seam holds no capability that could have reached
HFSS, the filesystem, the network, or the OS, so what the engine sees can only
be what a caller handed in.

WHAT "CONTRACT ONLY" ADMITS, decided at Step 2.5b and recorded here because the
narrow reading is the tempting one. It is the PREFIX reading: the whole
``hfss_agent.contract`` package, ``tool_io`` included. The constraint is about
CAPABILITIES, not about which data shapes W-8 may name — ``tool_io`` types are
inert pydantic models and grant nothing. The narrow reading (§2 schemas only)
would make ADR-28 decision 8 unimplementable, because the refusal arms W-8 must
raise on are ``tool_io`` types; being unable to express the decision is the tell
that it is not what §5 meant. ``tests/boundary/test_snapshot_import_audit.py``
carries this as a named test so a future reader cannot narrow it silently.

THE THREE REASONS ASSEMBLY REFUSES, all raising ``SnapshotAssemblyError`` (the
raising logic itself lands in Part 3 of this step; this file is the skeleton the
import audit constrains):

  1. A REFUSAL ARM WAS RECEIVED (ADR-28 decision 8). ``SelectionRefused`` gets no
     representation on any field: a refusal means a selection stage was missing,
     and ``Selection`` requires all seven — so a snapshot with a refused
     selection is not a lesser snapshot, it is no snapshot. The same holds for a
     ``CannotEvaluate`` on the inspection or native-validation input.
  2. THE ``SelectionChain`` WAS INCOMPLETE. The chain carries every stage as
     optional (it is built stage by stage and reset downstream on any change),
     while ``DesignSnapshot.Selection`` requires all seven. A chain missing a
     stage cannot be narrowed without inventing one, so it is refused rather
     than defaulted.
  3. THE INSPECTION WAS A SUBSET READ. ``InspectionResult`` carries whatever
     subset the caller requested; ``DesignSnapshot.Inspection`` requires all
     eight sections and deliberately has NO absence arm (ADR-28) — its PARTIAL
     failures are already carried section by section as ``read_status`` and
     ``limitation``, which is finer-grained honesty than an arm could give. A
     three-section read therefore yields no snapshot.

WHAT ``created_at`` MEANS. Stated here in the words a stranger should be able to
read in six months, because the natural misreading — "this is when we looked at
the design" — is the one that matters:

    ``created_at`` is the UTC instant this snapshot was ASSEMBLED — not when
    anything in it was read. Every read it describes happened earlier and
    carries its own timestamp; this field says only when the pieces were
    composed into one artifact.

Stamped with an inline ``datetime.now(timezone.utc)`` at construction, with no
injected clock, following W-5 and W-6 exactly (``inspect/assembler.py`` and
``validate_native/assembler.py`` each call it inline at the instant they are
describing). The instant differs from theirs in what it means, not in how it is
taken: those two stamp a read they just performed, and W-8 performs no read at
all, so there is no read for this field to be the instant OF. Taking the
earliest input instant would make it a silently-drifting duplicate of
``read_at``; taking the latest would claim the snapshot existed before it did.

``snapshot_id`` IS ``"snap-" + uuid4().hex``, and it identifies a CAPTURE EVENT
rather than a design state. All three carriers of the field want that reading:
``AuditRecord`` correlates one dispatch, ``ProvenanceRecord`` says which capture
a metric came from, and ``DesignSnapshot`` is the capture. A content hash would
identify a design STATE instead, which is a different question — ADR-6's
"diffing two snapshots answers what changed" is answered by diffing payloads,
not by comparing ids — and it would collide across two captures of an unchanged
design, leaving the audit log unable to say which call produced which.

THE VARIATION HASH IS RECEIVED AS DATA AND NEVER COMPUTED HERE. §2 assigned the
canonical hash to this module; under the contract-only grant that assignment is
unimplementable (W-8 cannot import the adapter, and the adapter must mint a
``Variation`` at select time, long before any snapshot exists), so ownership
moves to the adapter and §2 is corrected. Recomputing and comparing was rejected
on measurement, not taste: ``_resolve_variation`` carries an unparseable
variation token through AS the hash, so a comparison would fire on legitimate
data — a design whose variation string is "nominal" has ``values={}`` and
``variation_hash="nominal"``, which no recomputation can reproduce.
"""

from __future__ import annotations


class SnapshotAssemblyError(Exception):
    """Assembly could not complete honestly, so no snapshot is emitted.

    RAISED, NOT RETURNED, and forced by the contract rather than chosen.
    ``DesignSnapshot`` has three absence arms — ``native_validation``,
    ``solve_state`` and ``solved_data`` — and none of them can say "the inputs
    arrived, but they do not compose into an artifact anyone should trust".
    ``inspection`` and ``selection`` have no arm at all, deliberately: every
    whole-read failure the first has is a session fault or a session/adapter
    state divergence, under either of which the snapshot itself is not
    trustworthy; and ADR-28 decision 8 fixes that a refused selection means "no
    snapshot", not "a snapshot with an absence arm".

    Every raise site therefore DISCARDS the inputs it was holding. A snapshot
    with a defaulted selection stage, a synthesized eighth section, or an
    absence arm standing in for a refusal is not a lesser artifact to fall back
    on; it is a record asserting something nobody verified, and it is the one
    thing that must never cross the wrapper->engine seam.

    See this module's docstring for the three reasons that reach here: a refusal
    arm was received, the ``SelectionChain`` was incomplete, or the
    ``Inspection`` was a subset read.

    A DELIBERATE FOURTH DUPLICATE of ``InspectionAssemblyError``,
    ``NativeValidationAssemblyError`` and ``MetricsAssemblyError``, and ADR-28
    decision 15 records the reasoning pre-emptively rather than waiting for
    someone to propose the cleanup:

        "W-8's assembly error will be a fourth duplicate, and that is correct.
         Three assembler exception types already exist with docstrings arguing
         that unification is impossible because no legal shared home exists
         under the import map. `SnapshotAssemblyError` will be the fourth. Four
         is the count at which someone proposes a base class; the base class
         would have to live in `contract`, which W-12 restricts to validation,
         or in a shared module no layer may import. Recorded pre-emptively so
         the proposal arrives already answered."

    The four reasons W-6's copy sets out at length all still hold, and this
    type's import position makes two of them STRICTER rather than merely equal.
    W-5, W-6 and W-7 may each at least import ``broker``; W-8 may not, so the
    set of packages all four may legally import is exactly ``contract`` — and an
    assembler-domain exception is not a contract schema (W-12 restricts that
    subpackage to validation, and it is closed at its current version). The
    messages must differ materially, because these say no SNAPSHOT is emitted
    and must never call the composition a "read" or a "run". And catching one
    must not catch another: the server-layer tool that composes W-5, W-6 and
    W-8 in a single operation needs to know which assembly failed, and a shared
    base class would let one bare ``except`` swallow the wrong one.

    A future maintainer tempted to unify the four must first find a package all
    four may legally import. Today there is none, and the count is now four
    rather than three because W-8 removed the only candidate that was left.
    """
