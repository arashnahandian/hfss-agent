# Support matrix

The published matrix `preflight_environment` (W-11) checks a machine against,
and the **specification the version-classification code reads its boundaries
from** — not a citation target that trails the code. Every band below is a
requirement on the assembler, not a description of it.
`PreflightReport.support_matrix_ref` points at this file.

Two vocabularies, defined before use, on two **independent** axes. Collapsing
them is the specific mistake this document is shaped to prevent: intending to
support a version and having confirmed one are different claims, and only one of
them is evidence.

**Support status — what this project builds toward. Intent, never evidence.**

- **`target`** — the version this project is built and reasoned against. Design
  decisions were taken with it in mind. Exactly one row per axis holds it.
- **`expected`** — inside the pinned dependency's own supported range, but
  neither built against nor exercised here.
- **`beyond-pin`** — above the newest version the pinned dependency knows about,
  or above a ceiling this project chose. Not blocked, not endorsed.
- **`unsupported`** — outside what this project will support. The floor may be
  one the dependency states, one it merely warns at, or one only this project
  sets; the band says which.

**Validation status — whether a live, licensed AEDT/HFSS session has confirmed
the row.**

- **`unvalidated`** — no live-AEDT run has confirmed anything about this row.
- **`validated`** — defined here so the word carries a fixed meaning the first
  time it is used, and **used nowhere in this document.**

## The limitation, stated before the content

The live-solver validation pass is separate, manual and license-gated, and it
**has not run.** Every row below is `unvalidated`, the `target` rows included.
No entry in this document has been confirmed against a real AEDT installation or
a real HFSS session.

`target` therefore says where this project's attention went, not that the
version works. Read the whole document that way: it is a statement of what the
wrapper will and will not claim to support, standing on the dependency's own
declared boundaries and on this project's own pins — the two kinds of evidence
that can be read off a file — and on nothing else.

`docs/pyaedt-coverage.md` carries the same limit from the other side: every
adapter operation there is `mock-only`. That document is about whether the
**calls** behave as assumed; this one is about which **versions** they are
assumed to behave that way on. Neither has met a licensed session.

## AEDT

| AEDT version | Support status | Validation status | Short reason |
|--------------|----------------|-------------------|--------------|
| `2026.1` | target | unvalidated | The anchor; the version this project is built against. |
| `2022.2 <= v < 2026.1` | expected | unvalidated | Inside PyAEDT's own supported range; never exercised here. |
| `v > 2026.1` | beyond-pin | unvalidated | Newer than the pinned PyAEDT's `CURRENT_STABLE_AEDT_VERSION`. |
| `v < 2022.2` | unsupported | unvalidated | Our floor, not PyAEDT's — it only warns here and attaches anyway. |

The four bands are unconfirmed for four **different** reasons. They must not
share one label without the difference being written down, because the remedy
differs in each case: one wants a live pass, one wants a test machine, one wants
a dependency bump, and one wants a newer AEDT.

### `2026.1` — the anchor

The version this product is built and reasoned against. Two independent facts
corroborate it as a sensible anchor, and neither is a validation:

- The pinned PyAEDT's own package metadata states its testing baseline —
  `.venv/Lib/site-packages/pyaedt-1.2.0.dist-info/METADATA:201`: `- All tests
  were conducted using AEDT 2026 R1.`
- The same release's newest-known-stable constant holds the same value —
  `.venv/Lib/site-packages/ansys/aedt/core/internal/aedt_versions.py:40`:
  `CURRENT_STABLE_AEDT_VERSION = 2026.1`.

**Why it is still `unvalidated`, and why that matters most here.** The anchor is
where the assumptions are concentrated, not where they are absent. Every
`mock-only` row in `docs/pyaedt-coverage.md` is an assumption about how PyAEDT
behaves on *this* version specifically. The two facts above show that 2026.1 is
the version PyAEDT 1.2.0 itself was tested against — which makes it the best
available anchor and changes nothing about whether this wrapper's reads work on
it.

### `2022.2 <= v < 2026.1` — older, and untried

Unconfirmed for a plainer reason than the anchor: PyAEDT supports these versions
and this project has never run against one. There is no evidence either way,
because there has been no machine in the loop carrying these versions — a gap in
coverage, not a doubt about the dependency.

The specific risk is not that attach fails. It is that the adapter's read
assumptions were written against 2026.1 and could differ further down the range —
result-object shapes, message formats, and property availability are exactly the
things that drift across releases, and every one of them is already `mock-only`
even at the anchor. `expected` claims only that nothing known forbids these
versions.

### `v > 2026.1` — newer than the pinned dependency knows about

Unconfirmed for a third reason, and the one most likely to be mishandled: the
pinned `pyaedt==1.2.*` **does not know these versions exist.**
`CURRENT_STABLE_AEDT_VERSION` is a hand-maintained constant — the module
docstring at `aedt_versions.py:27` says it "should be updated every time a new
stable version is released" — so it marks the newest release *that PyAEDT build
was aware of*, not a capability boundary.

**A newer AEDT must not be treated as an absent one.** The classification code
has to get this right, so the mechanism is recorded rather than summarised:

- `stable_versions` filters the installed set to `<= CURRENT_STABLE_AEDT_VERSION`
  (`aedt_versions.py:224`), and `current_version` is the first of those, or `""`
  when there are none (`aedt_versions.py:240-244`).
- `latest_version` applies **no such filter** — it is the first installed key,
  pre-release or not (`aedt_versions.py:278-283`).
- `Desktop.__check_version` raises only when **both** are empty
  (`desktop.py:2801-2802`):
  `if self.current_version == "" and aedt_versions.latest_version == "": raise
  AEDTRuntimeError("AEDT is not installed on your system. ...")`.

So on a machine carrying **only** a future version, `current_version` is `""`
while `latest_version` is not, the `and` is not satisfied, and PyAEDT does not
reject it. Attach may well proceed — through code paths written before that AEDT
version existed. `beyond-pin` is the honest verdict: not blocked, not endorsed,
and specifically **not** reported as "AEDT not installed."

### `v < 2022.2` — our floor, standing on PyAEDT's warning

The one boundary whose number this project did not pick. PyAEDT states it
itself, in `.venv/Lib/site-packages/ansys/aedt/core/desktop.py:2838-2841`:

```python
elif float(specified_version[0:6]) < 2022.2:
    warnings.warn(
        """PyAEDT has limited capabilities when used with an AEDT version earlier than 2022 R2.
        Update your AEDT installation to 2022 R2 or later."""
    )
```

Two lines above it (`desktop.py:2837`) a harder floor raises rather than warns:
`raise ValueError("PyAEDT supports AEDT version 2021 R1 and later. Recommended
version is 2022 R2 or later.")` — reached when the version is below 2019.

This matrix takes **2022.2** as the floor, the warning line and not the raising
line, deliberately: below it PyAEDT declares its own capabilities limited, and a
verification-first wrapper cannot stand its claims on a dependency that has
declared itself unreliable underneath them. A version in `2019 <= v < 2022.2`
will still attach, with a warning, and is still `unsupported` here.

## Python

| Python | Support status | Validation status | Short reason |
|--------|----------------|-------------------|--------------|
| `3.12` | target | unvalidated | Recommended interpreter; the build venv and both CI legs run it. |
| `3.10`, `3.11` | expected | unvalidated | Inside `requires-python`; not exercised in CI. |
| `3.13`, `3.14` | beyond-pin | unvalidated | Wheel-viable, deliberately not adopted (ADR-13). |
| `< 3.10` | unsupported | unvalidated | Below both this project's pin and PyAEDT's own `Requires-Python`. |

The band is `>=3.10,<3.13`, enforced at the packaging level in `pyproject.toml`
and not only in prose.

**This ceiling is a choice, not a PyAEDT limit, and the distinction is
load-bearing** — a reader who assumes otherwise will "fix" the pin the first
time they see PyAEDT advertise a wider range. PyAEDT 1.2.0's own metadata is
`Requires-Python: <4,>=3.10`, and the same file claims compatibility "up to
Python 3.14" (`pyaedt-1.2.0.dist-info/METADATA:199`). A Phase 0 wheels-only
resolution of the full `pyaedt[all]` set against `win_amd64` found 3.10 through
3.14 all resolving to prebuilt Windows wheels with no source build required
(ADR-13). The ceiling sits at 3.12 for ecosystem/PyAEDT **test** maturity, which
is not the same thing as wheel availability, and it is revisitable on that basis
rather than on a resolution result.

That Phase 0 check is the only positive evidence anywhere in this document, and
it is worth being exact about what it covers: it confirms that dependencies
*install*. It says nothing about any interpreter running against a live AEDT
session, which is why every row above is still `unvalidated`.

## PyAEDT

| PyAEDT version | Support status | Validation status | Short reason |
|----------------|----------------|-------------------|--------------|
| `1.2.*` | target | unvalidated | The `live` extra's pin; 1.2.0 is what is installed and read from. |
| `> 1.2` | beyond-pin | unvalidated | Outside the pin; `CURRENT_STABLE_AEDT_VERSION` and the API surface both move between minors. |
| `< 1.2` | unsupported | unvalidated | Outside the pin, and below the 1.0 restructure this code assumes. |
| absent | — | — | A determination, not a gap. See below. |

The pin is `live = ["pyaedt==1.2.*"]` in `pyproject.toml`, an **optional** extra.
Every source citation in this document was read from the installed 1.2.0 under
that pin; on a different minor the line numbers, and possibly the constants,
will differ.

**Absence is a determination, and preflight reports it as one.** PyAEDT is a
required component: without it no attach can occur, so an absent distribution is
`incompatible`, never "could not determine." This is not the unusual case —
public CI runs `uv sync` **without** the `live` extra on both OS legs, so the
environment this report most often describes is one where `pyaedt` is genuinely
absent and `PreflightEnvironment.pyaedt_version` is `None`.

## The six components checked

`ComponentCheck.required` carries the matrix requirement in plain language;
these are the requirements it carries. `severity` decides whether a failure
blocks the user, and it is what keeps the roll-up honest in both directions —
"only `incompatible` demotes" would report a machine with AEDT but no PyAEDT as
healthy, and "any `unavailable` demotes" would mark every machine incompatible
forever, since the license row can never be anything else.

| Component | Requirement (plain language) | Severity | Reachable statuses |
|-----------|------------------------------|----------|--------------------|
| `aedt` | AEDT 2022.2 or later installed; 2026.1 is the target | required | `ok`, `incompatible` |
| `pyaedt` | PyAEDT `1.2.*` installed (the `live` extra) | required | `ok`, `incompatible` |
| `python` | Python 3.10–3.12; 3.12 recommended | required | `ok`, `incompatible` |
| `grpc` | gRPC transport available to the target process | advisory | `unavailable` |
| `license` | A valid AEDT license at attach time | advisory | `unavailable` |
| `processes` | Running AEDT processes to attach to | advisory | `unavailable` |

The three required components are exactly the three that are **structurally
determinable**: the AEDT installation scan always returns a set (empty is an
answer), `importlib.metadata` either yields a version or says the distribution
is absent, and the running interpreter cannot fail to report its own version. A
required component reporting `unavailable` would describe a producer defect, not
a machine, and the contract refuses to construct such a report.

The three advisory components are `unavailable` **permanently**, each for its
own structural reason — not pending work that a later step will finish:

- **`license`** — the zero-egress invariant forbids contacting a license server,
  and no local file states whether a checkout would succeed. AEDT reports
  licensing at attach time; preflight cannot anticipate it.
- **`grpc`** — not a machine property at all. It is a per-process fact PyAEDT
  reads from `active_sessions()` at attach, where a port of `-1` means a COM
  session that still attaches perfectly well
  (`ansys/aedt/core/generic/general_methods.py:1364`: "``-1``: COM session (no
  gRPC server running)"). With no process selected there is nothing to report.
- **`processes`** — process discovery is deferred to its own step (ADR-18
  decision 1): the `AedtProcess` schema cannot be honestly filled from any
  read-only PyAEDT path without breaking the attach-once model. Deferred with a
  destination is not the same as unknown, but it is still `unavailable` today.

## What a live pass must answer

Open questions, in the form `docs/pyaedt-coverage.md` uses: things this document
asserts on documented behaviour and file-readable pins, which only a licensed
session can settle. Recording them as questions is the point — an unverified
assumption written as a statement stops being visible.

- **Does an attach against the `2026.1` target actually succeed end to end, and
  do the adapter's seven operations return the shapes assumed?** The whole
  matrix leans on the anchor; nothing has confirmed it. Until this is answered,
  every band is provisional, not just the ones marked unconfirmed for their own
  reasons.
- **On a machine carrying only an AEDT newer than `CURRENT_STABLE_AEDT_VERSION`,
  what does attach actually do?** The source shows PyAEDT does not *reject* such
  a machine. It does not show that the session works. If attach succeeds but
  reads misbehave, `beyond-pin` needs to become a warning louder than the
  advisory it is today; if it fails cleanly, the band should say so plainly.
- **How far down does `2022.2 <= v < 2026.1` really hold?** Record the oldest
  AEDT version against which the adapter's reads were confirmed. That version,
  not PyAEDT's warning threshold, is the honest lower edge of `expected` — and
  until one is recorded the band rests entirely on the dependency's claim.
- **On a multi-version machine, which install does an attach bind to?**
  `aedt_version` is reported only when the installed set has exactly one member
  or a session is attached, because PyAEDT resolves the target by matching the
  process against each installed version in turn. Confirm that behaviour, and
  record whether a multi-version machine can be resolved without attaching.
- **Does an `AWP_ROOT*` variable without an `AnsysEM` subdirectory appear on real
  machines?** PyAEDT's own install scan requires that subdirectory to exist for
  the `AWP_ROOT` branch, so a naive environment-variable-only reimplementation
  would over-report an install PyAEDT will refuse. Confirm the scan agrees with
  PyAEDT's on a machine with a stale root variable.

## Enforcement, and the reference constant

`PreflightReport.support_matrix_ref` is a required string, so **this file's path
is a published value.** Renaming or moving this document turns every report's
reference into a dead link, silently — it will be pinned by a test that resolves
the constant against the repo and fails if nothing is there, so a rename breaks
CI rather than shipping a broken pointer.

What is enforced today, by path: `tests/schemas/test_tool_io.py` pins the three
`PreflightReport` roll-up validators — that a verdict rests on at least one
required check, that no required check reports `unavailable`, and that `overall`
is `incompatible` if and only if a required check is. Those tests constrain the
report's **shape**; they do not check any value in this document, and one of
them already carries `"docs/support-matrix.md"` as a fixture string.

What is not enforced yet, stated as a gap rather than left to be assumed: no
test asserts that the assembler's bands match the bands written above, that the
component tuple matches the six listed above, or that this file exists at the
referenced path. Those land with the W-11 assembler and its suite. Until then
this document is authoritative by convention only, and a drift between it and
the code would be silent.
