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
