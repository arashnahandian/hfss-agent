"""W-11 · preflight — Journey 1.0: environment health + sanitized diagnostics.

Checks AEDT version, PyAEDT version, Python environment, gRPC availability,
license access, and running AEDT processes against the published support matrix
(anchored on AEDT 2026.1, and see ``support_matrix`` for why that anchor is not
read from PyAEDT's own constant). Also produces the sanitized diagnostics
bundle. Does not auto-fix anything.

TWO SENSES OF "SANITIZED", AND THIS PACKAGE USES BOTH — disambiguated here
because the word appears in the line above with one meaning and everywhere else
in this repo with the other, and a reader who carries the wrong one across will
ship a disclosure (ADR-26 decision 18(f)):

  * THE ADAPTER'S SENSE (ADR-9, ``adapter/sanitize.py``): control characters
    other than tab and newline are stripped from every string read from HFSS,
    and each is length-capped. It is about INJECTION. It removes no identity of
    any kind — a sanitized project name is still the project's real name, and a
    sanitized path is still the user's real path. This is the sense every other
    module in the repo means.
  * THIS MODULE'S DIAGNOSTICS SENSE (spec Point 21, the "sanitized diagnostics
    bundle" above): project, design, and user-identifying strings are REMOVED,
    so the bundle can be sent to someone else. It is about DISCLOSURE.

The two are unrelated operations with unrelated purposes, and neither implies
the other. Adapter-sanitized data is NOT safe to share; diagnostics-sanitized
data has not thereby been made injection-safe. The bundle itself arrives in a
later step — this note exists now so the word does not sit here undefined until
then, and so the code that builds the bundle inherits the distinction rather
than re-deciding it.

Nothing in this package reaches PyAEDT, the adapter, or the network (ADR-26
decision 1), and only ``probes`` touches the machine at all.
"""

from hfss_agent.preflight.assembler import COMPONENT_ORDER, preflight_environment
from hfss_agent.preflight.probes import (
    REAL_PROBES,
    EnvironmentProbes,
    VersionRead,
)
from hfss_agent.preflight.support_matrix import SUPPORT_MATRIX_REF

__all__ = [
    "COMPONENT_ORDER",
    "REAL_PROBES",
    "SUPPORT_MATRIX_REF",
    "EnvironmentProbes",
    "VersionRead",
    "preflight_environment",
]
