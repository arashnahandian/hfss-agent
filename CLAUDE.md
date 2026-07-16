# CLAUDE.md — hfss-agent (public wrapper)

*(This is the PUBLIC-REPO variant. Commit this file, named `CLAUDE.md`, at
the root of the public `hfss-agent` repo. The full internal version —
`hfss-agent-CLAUDE.md` in the build project's files — goes in the PRIVATE
engine repo only. This variant carries the same engineering rules with
internal strategy, process, and personal details removed, because
everything in this file is world-readable.)*

This file governs every Claude Code session on this repo.

## What this project is
An open-source capability wrapper for a verification-first MCP agent for
Ansys HFSS. It runs entirely on the user's machine against their own
licensed HFSS/AEDT install, attach-only, and gives an AI assistant safe,
structured, read-only access to a live design: full inspection, native
HFSS validation passthrough, solution-validity gating, and deterministic
S-parameter metrics — every claim grounded in data read from HFSS, a
deterministic calculation, or an explicit rule with named applicability.
When something can't be evaluated, it says so instead of guessing. Nothing
ever leaves the user's machine.

## Architecture in one paragraph
This package is the sole component capable of touching HFSS, project
files, the network, or the OS. It emits a structured, versioned, read-only
design snapshot (plain JSON-serializable data — never live handles,
sessions, paths, or callables) to an optional separately-distributed rule
engine, which returns findings but holds no capabilities and executes
nothing. The wrapper works standalone when the engine is absent
(inspection + native validation + validity gates + open metric formulas),
degrading gracefully and explicitly — never silently.

## Hard rules — CI-enforced, not conventions
- **Only `adapter` imports `pyaedt`.** Anywhere else is a CI failure.
- **Only `broker` performs file I/O.** All writes route through it and
  inherit its guards.
- **Nothing below the `server` layer imports `server`.**
- **`gating` imports only `hfss_agent.contract`** — it carries the same
  import-purity constraint as engine code, by design; keep it pure.
- **`contract` must stay import-clean** — importing it must never pull in
  `pyaedt` or anything I/O-capable. The purity test is load-bearing.
- **No mutating PyAEDT method is reachable through the tool surface.** The
  MVP is read-only by construction; the prohibited-operations suite proves
  it. Do not add a mutating call to the adapter whitelist.
- **No arbitrary-execution path exists — deliberately.** No `eval`, no
  `exec`, no subprocess-driven scripting against the HFSS session,
  anywhere. If you think a task needs one, the answer is a typed
  `cannot_evaluate` outcome, not a script hatch.
- **Zero egress.** This package makes no outbound network calls of any
  kind. No telemetry, no update checks, no license pings. Anything that
  looks like it needs the network is out of scope here.

## Safety and honesty rules
- Every tool is registered with a risk tier (the entire current surface is
  safe-tier); a tool without a declared tier does not register.
- Every adapter call runs under a per-call watchdog timeout and returns
  data, a typed error, or `cannot_evaluate` — never a hang. On timeout the
  call is abandoned (not pretended-cancelled), the session is marked
  suspect, and the next operation forces reconnect-and-verify.
- No silent overwrite or delete anywhere on the file surface: exports
  refuse existing paths without explicit `overwrite=true`; the audit log
  is append-only; the intent file writes atomically.
- All strings read from HFSS (project/design/material names, notes, solver
  messages) are untrusted data: typed as untrusted in schemas,
  length-capped and control-character-stripped at the adapter, rendered
  only inside explicit data delimiters, and never allowed to influence
  control flow, tier decisions, or file paths.
- Computed values come only from this package's open, individually
  referenceable formulas and gates, or from versioned engine rules under
  machine-checked applicability. There is no output field an LLM can
  populate; language models sit strictly downstream and can rephrase,
  never substitute. Never present an unverified or LLM-generated value as
  a measured one.
- Metrics are computed only after the four validity gates pass (solution
  exists / convergence / freshness / target coverage). On gate failure,
  report why and refuse interpretation — no numbers.
- Where PyAEDT cannot read or evaluate something, say exactly that
  (`read_status: not_readable` with the limitation named, or
  `cannot_evaluate`) — never improvise, never paper over a gap.

## Testing requirements
Core logic requires unit tests against the fake adapter before a module is
done. CI never requires a live AEDT license — everything in CI runs
against the fake adapter, which can simulate hangs, crashes, and
disconnects. The prohibited-operations, boundary, session-lifecycle, and
schema-rejection suites must stay green; they are never cut, even under
schedule pressure. Live-solver validation is a separate, manual,
license-gated pass and is never assumed in CI. Track each adapter
operation's verification status in `docs/pyaedt-coverage.md`
(`verified-live` / `mock-only`) — no operation ships as silently
unverified.

## Environment
Python 3.10–3.12 (3.12 recommended) — this project pins below PyAEDT's
currently-supported range for ecosystem maturity, not because PyAEDT
can't run on newer interpreters (1.2.0 resolves cleanly through 3.14);
always work inside the project venv (`uv`-managed), never a
system Python. `ruff` must pass. Windows is the primary platform (AEDT
reality) and is exercised in CI alongside Linux. Keep the repo outside any
OneDrive-synced folder — sync corrupts git internals and venvs.

## Scope discipline
This repo is the read-only Tier 1 wrapper. Do not add: modification tools,
far-field metrics, solve orchestration, optimization, run history,
templates, support for other solvers, or any capability beyond the current
documented surface — flag the idea instead of building it. Do not add
fields to the snapshot or findings schemas beyond what the documented data
model specifies; flag gaps rather than improvising. Contract/schema
changes are versioned events (semver on the snapshot contract), never
casual edits.

## Git discipline
One step = one branch = one reviewed commit. Plan-first-then-approve for
any change touching more than one file. CI green before merge.

## Handoff-readiness mindset
Write as if a stranger reads this in six months with no one to ask.
Meaningful naming over clever naming. Comment the "why" of non-obvious
rules inline — the "what" the code already shows.
