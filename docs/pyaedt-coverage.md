# PyAEDT operation coverage

Verification status of every adapter operation, per the CLAUDE.md testing rule:
no operation ships as silently unverified. Two states:

- **`mock-only`** — exercised only against the `FakeAdapter` in CI; no live-AEDT
  run has confirmed the real PyAEDT calls behave as assumed.
- **`verified-live`** — confirmed against a real, licensed AEDT/HFSS session in
  the separate, manual, license-gated validation pass.

CI never requires a license (System Design §4); everything here is `mock-only`
until the live pass runs.

The real adapter (`adapter/real/`, Step 1.2) now exists and is exercised in CI
only against a hand-written PyAEDT double, so **every operation below is
`mock-only`** — the double can be wrong in the same way the documented-API
assumptions can be wrong, so those tests confirm wiring, not PyAEDT correctness.
Live behaviour is confirmed later on licensed hardware (Phase 5.2). The one
PyAEDT-importing file (`adapter/real/session.py`) is not imported in CI at all;
its call signatures are review- and live-verified, never CI-verified.

`tests/adapter/test_pyaedt_api_contract.py` statically checks the adapter's
constructor-parameter and class-attribute assumptions against the *installed*
`pyaedt` when the `live` extra is present (it skips otherwise, so CI is
unaffected). This is signature verification, **not** live verification: a
parameter or property existing does not confirm its runtime behaviour or return
shape, so **no operation is promoted off `mock-only` on its strength**. It has
already caught two wrong assumptions and they were fixed at source: `excitations`
→ `excitation_names`, and `desktop.project_list` is a property (read without a
call), not a method.

## Adapter operations (W-3)

The seven adapter-level operations are the whole surface the ten PyAEDT-reaching
tools need.

| Operation | Returns (contract type) | Serves (of the ten tools) | Status |
|-----------|-------------------------|---------------------------|--------|
| `attach` | `Environment` | attach | mock-only |
| `list_options` | `list[SelectionOption]` | list_selection_options | mock-only |
| `select` | `SelectionChain` | select | mock-only |
| `inspect` | `dict[InspectionSectionName, InspectionSection]` | inspect_design | mock-only |
| `validate_native` | `NativeValidation` | validate_setup | mock-only |
| `read_solve_state` | `SolveState` | check_solution_validity, get_solve_health, compute_metrics (gate), export_diagnostics_bundle | mock-only |
| `read_solved_data` | `SolvedData` | compute_metrics, export_results, check_solution_validity (freq axis), export_diagnostics_bundle | mock-only |

Notes:
- `export_results` and `export_diagnostics_bundle` add no adapter operation of
  their own: the first is `read_solved_data` + a broker-owned file write; the
  second composes `inspect` + `validate_native` + `read_solve_state` +
  `read_solved_data` + a broker-owned bundle write.
- `list_aedt_processes` and `preflight_environment` are intentionally **not**
  adapter operations at this step; whether/where they touch PyAEDT is a separate,
  later decision.

### Known `cannot_evaluate` / degradation paths in the real adapter (Step 1.2)

Deliberate, approved gaps — PyAEDT does not expose these cleanly, so the adapter
returns a typed outcome naming the specific limitation rather than guessing or
fabricating. All `mock-only`:

- **`read_solve_state`** returns `AdapterCannotEvaluate` when per-pass
  convergence history / convergence status is unavailable, and (separately) when
  a solve-completion timestamp is unavailable — each with a specific limitation
  string. `freshness_evidence` defaults to `determinable=False` with empty
  signals (no reliable design-modified-since-solve signal; ADR-4).
- **`inspect`** degrades per-section to `read_status="not_readable"` with a named
  limitation (materials detail, ports, available results are the uncertain ones)
  rather than failing the whole read.
- **`read_solved_data`** returns `AdapterCannotEvaluate` when no solved data
  exists for the selection or the frequency sweep unit is unrecognised for Hz
  normalisation.
- **`list_options("variation")`** returns `AdapterCannotEvaluate` when PyAEDT
  exposes no readable variation list.
- **`validate_native`** (added Step 2.2b) returns `AdapterCannotEvaluate` when
  the narrow `_UNAVAILABLE` guard on the seam call fires: HFSS's own design
  validator could not be run, or its messages could not be read back, through
  PyAEDT for this design. Without the guard this surfaced as
  `AdapterInternalError` — a `SessionFault` blaming the wrapper's own
  bookkeeping for an unavailable HFSS validator. The guard covers this path
  only; the adapter-wide guard policy is Phase 6.1 work. Note the outcome is
  **not** a statement about the design, and is not the same as a validator that
  ran and reported nothing (an empty `raw_output`, which is a success).

### Re-attach handle hygiene (Step 1.3 — `mock-only`)

Introduced with the session module (W-2), which recovers a lost session by having
the user re-attach — a *second* `attach()` on an already-attached `LiveSession`.
`RealAdapter._attach` now calls `LiveSession.reset_bindings()` on every (re)attach;
the **drive** (the adapter invalidating bindings on attach) is CI-verified via the
seam double, but two effects stay `mock-only` until a live licensed session:

- **`reset_bindings()` clearing `_apps`** — verify that a subsequent
  `application()` call binds a fresh `Hfss` handle against the newly-attached
  `Desktop`, so no stale-handle read survives a second `attach()`.
- **Rebinding `self._desktop`, orphaning the previous one** without
  `release_desktop`/`close_desktop` (both AST-forbidden, ADR-17 #10) — verify it
  does not leak a grpc/COM connection or a zombie process reference, i.e. PyAEDT's
  process-level session dedup reclaims/reuses the prior handle. If it leaks,
  escalate: attach-only-without-release may be incompatible with re-attach, and
  re-attach recovery needs a different mechanism.

Read-only / attach-only enforcement lives in
`tests/prohibited_ops/test_adapter_read_only.py` (AST: no dynamic dispatch, no
mutating/`release_desktop`/`close_desktop` names) and
`tests/boundary/test_adapter_import_audit.py` (only `session.py` may import the
AEDT API, under both `pyaedt` and `ansys.aedt` name shapes).

### Native validation side effects (Step 2.2b — `mock-only`)

Introduced with the native validation passthrough (W-6). The `_UNAVAILABLE`
guard and the message passthrough are CI-verified via the seam double and the
`FakeAdapter`'s six native fixtures, but three assumptions are unverified — two
about what `ValidateDesign` and `GetMessages` actually DO on a live session, one
about what their output contains. The first two were flagged during the Step
2.2b safety check as unsure rather than rounded up to "safe"; the third is the
Phase 5.2 question ADR-23 #15 assigns to this document. All three are recorded
here rather than left as confidence:

- **Does `ValidateDesign` write anything to disk, on any AEDT version?** It was
  chosen over `validate_full_design()` specifically because the latter writes a
  validation log to the project directory, which this package's read-only stance
  forbids. That choice rests on documented behaviour and has never been
  confirmed against a licensed session. Verify that a native validation run
  leaves the project directory byte-identical. If `ValidateDesign` writes
  anything at all, the read-only claim for this path is wrong and the operation
  needs re-scoping — not a footnote.
- **Does `GetMessages` mutate the message queue it reads?** It demonstrably
  populates the AEDT message manager, which is solver-session state, so this
  operation is not provably side-effect-free in the way the other six reads are.
  The full scope of that effect is unverified: whether messages are consumed,
  cleared, re-ordered, or merely observed. Verify what the queue holds before and
  after a run, and whether a second consecutive validation returns the same
  messages.
- **Does real ValidateDesign output contain control characters, and does any
  single message approach `MAX_UNTRUSTED_STR_LEN`?** (ADR-23 #15.) The sanitizer
  strips control characters other than tab and newline, leaving no trace, and
  caps each message at 10 000 with a visible truncation marker. That cap is
  documented in-code as an unvalidated judgment call — it has never met live
  AEDT output, because `validate_native` is `mock-only`. A live pass should
  record whether any real message contains control characters (and which), and
  the longest single message observed, so the cap can be confirmed or moved on
  evidence rather than judgment.

### S-parameter expression key spelling (Step 2.3 — `mock-only`)

Introduced with the export content generators (W-7). `SolvedData.s_parameters`
is keyed by S-parameter name, and its docstring gives `"S(1,1)"` as the
canonical form — but nothing enforces that. `RealAdapter.read_solved_data`
builds the mapping straight from `data.expressions` and normalises no key, so
**canonical spelling is an assumption about what PyAEDT emits, not a guarantee
this package makes.** It has never met a live AEDT session.

`metrics/export.py` infers the port count by parsing those keys, so the
assumption became load-bearing there: an unparsed key means no port count, and
no port count means no Touchstone file. The parser (`_S_PARAM_KEY`) is therefore
**strict** — `^S\((\d+),(\d+)\)$`, no case-insensitivity, no whitespace
tolerance — and refuses anything else by name. A tolerant parser was written
first and deliberately tightened: it would have absorbed a spelling difference
silently, produced a correct-looking file, and destroyed the evidence that the
assumption was wrong.

A live pass should record:

- **The exact spelling `data.expressions` returns** for a multi-port solved
  setup — whether it is `S(1,1)`, `S(1, 1)`, `s(1,1)`, or something else
  entirely, and whether it varies by solution type or AEDT version.
- **Whether non-S-parameter expressions appear in the same mapping** (for
  example `dB(S(1,1))`, which is a real HFSS expression shape and is currently
  refused). If they do, the fix is to filter the mapping upstream, not to loosen
  the parser — an export must state a complete N×N matrix, and a mapping that
  mixes derived expressions with matrix entries cannot be trusted to be one.
- **Whether port indices are ever zero-padded** (`S(01,1)`). Currently accepted
  by the regex and then refused as a duplicate position if the unpadded key is
  also present.

If the real spelling differs, the refusal is expected to fire loudly at Phase
5.2 — that is the intended outcome, not a regression. Fix it at the source that
produces the key, and record the confirmed spelling here.

### AEDT install detection in `preflight` (Step 2.4b — not an adapter operation)

Introduced with W-11's probes. **This section carries no `mock-only` status,
and the omission is deliberate:** those two states describe whether a real
PyAEDT *call* behaves as assumed, and `preflight` makes none — it does not
import `pyaedt`, reach the adapter, or open a session (ADR-26 decision 1). What
follows is recorded here anyway because this file is the ledger for exactly this
class of assumption: a documented PyAEDT behaviour this package depends on
without having met it live.

W-11 reimplements PyAEDT's own installed-version scan rather than calling it,
because calling it would mean importing `pyaedt` in a module that must work
without it. The reimplementation is a deliberate, forced duplicate (ADR-26
alternative (h)) and it can therefore disagree with the original. One
disagreement is known and was chosen:

- **Does a real machine ever have a FILE where the `AnsysEM` subdirectory
  belongs?** PyAEDT counts an `AWP_ROOT*` variable as an install only when
  `<root>/AnsysEM` exists, testing it with `Path(...).exists()` — which is true
  for a file as well as a directory. W-11 uses `os.path.isdir`, which is not.
  On such a machine PyAEDT reports an install and this wrapper reports none, so
  preflight would say `incompatible` where an attach would in fact proceed.
  `isdir` was chosen because it is what the check actually means and because
  under-reporting is the safer error — telling a user their environment is not
  ready is recoverable, telling them it is ready for an attach that cannot
  happen is not. But it IS a disagreement with the dependency rather than a
  match, so a live pass should record whether the shape occurs at all. If it
  never does, the two are equivalent in practice and this note can be closed; if
  it does, the choice needs re-deciding on evidence rather than on which error
  is safer.
- **Does the scan agree with PyAEDT's on a machine with a stale root
  variable?** An `AWP_ROOT*` left behind by an uninstall, or pointing at a
  directory that no longer holds `AnsysEM`, is the case the subdirectory check
  exists for. Confirm the two implementations return the same install set on a
  machine that has one.
- **Does `Desktop.aedt_version_id` ever return something
  `parse_dotted_version` cannot read?** W-11 parses the attached session's
  version rather than passing it through, and falls back to the installed scan
  when it will not parse (see `preflight/assembler.py`). The fallback has never
  been exercised against a real session because no real session has run. Record
  the exact string a live attach yields, and whether it is ever anything other
  than `year.release`.
