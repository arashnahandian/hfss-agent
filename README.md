# hfss-agent

Open-source capability wrapper for a verification-first MCP agent for Ansys
HFSS. It runs entirely on your machine against your own licensed HFSS/AEDT
install, **attach-only**, and gives an AI assistant safe, structured,
**read-only** access to a live design: full inspection, native HFSS validation
passthrough, solution-validity gating, and deterministic S-parameter metrics.
Every claim is grounded in data read from HFSS, a deterministic calculation, or
an explicit rule with named applicability — when something can't be evaluated,
it says so. **Nothing ever leaves your machine.**

This is the public wrapper. It works standalone (inspection + native validation
+ validity gates + open metric formulas) and degrades gracefully when the
optional closed rule engine (`hfss-agent-engine`) is absent.

## Prerequisites

- **Python 3.12** (recommended), launched via the Windows `py` launcher:
  `py -3.12`. The supported range is **3.10–3.12** (see the pin note below).
- **[uv](https://docs.astral.sh/uv/)** for package installs.
- Windows is the primary platform (AEDT reality); Linux is also supported for
  license-free development against the fake adapter.

## Setup

```powershell
# From the repo root. Create the venv with the real 3.12 interpreter directly
# (do NOT use `uv venv` — it can pull its own bundled Python, which has a known
# OpenSSL DLL conflict with PyAEDT/PyEDB on Windows).
py -3.12 -m venv .venv

# Activate it.
.\.venv\Scripts\Activate.ps1        # PowerShell
# source .venv/bin/activate         # bash / Linux

# Install the package (editable) into the venv using uv's pip interface.
uv pip install -e .

# Lint.
uv run ruff check .
```

Verify the interpreter reports 3.12.x:

```powershell
.\.venv\Scripts\python.exe --version
```

## Python version pin

The supported interpreter range is deliberately held at **3.10–3.12** (3.12
recommended), pinned at the packaging level in `pyproject.toml`
(`requires-python = ">=3.10,<3.13"`). This is a *choice*, not a PyAEDT
constraint — PyAEDT 1.2.0 resolves to prebuilt wheels well past 3.12 — made for
ecosystem/PyAEDT test maturity rather than raw wheel availability. See **ADR-13**
in the project's ADR log for the full reasoning.

## Status

Scaffold only (Step 0.1): the package tree imports cleanly; no feature logic
exists yet.
