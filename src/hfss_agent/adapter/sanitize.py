"""Untrusted-string sanitization at the capability boundary (W-3, ADR-9).

All strings read from HFSS — project/design/material names, notes, solver
messages — are untrusted data (System Design §6.6). ADR-9 fixes the ADAPTER as
the enforcement point, so this runs in the ``Adapter`` ABC's template path and
every implementation (``FakeAdapter`` now, the real PyAEDT adapter later)
inherits it structurally rather than re-implementing it.

Sanitization is deliberately minimal and non-destructive: strip control
characters and cap length, and NOTHING else. We report the design as it is and
neutralize hostile content by framing/typing (it stays an untrusted string),
never by rewriting it — instruction-like text passes through verbatim (minus any
control characters), it is not censored or reworded.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from typing import Any

from pydantic import BaseModel

# Hard length cap for any single untrusted string. 10 000 is a deliberate
# judgment call, NOT a derived or measured bound: it is chosen to sit far above
# any realistic HFSS name or solver message while still bounding a hostile
# payload. It has not been validated against real AEDT output — Phase 5.2 live
# validation is where that assumption gets checked. Not a contract field.
MAX_UNTRUSTED_STR_LEN = 10_000

# Tab and newline are legitimate structure in multi-line solver messages, kept so
# sanitization does not mangle real content. Every other control character
# (category "Cc": NUL, ESC/ANSI, BEL, backspace, form-feed, carriage-return, the
# C1 range, …) is removed because it is an injection vector once the untrusted
# text is rendered downstream.
_KEEP_CONTROL = frozenset({"\t", "\n"})


def _truncation_marker(omitted: int) -> str:
    """Our own, fixed-format truncation notice. Only the numeric count is
    interpolated — no untrusted input is ever echoed into it."""
    return f"...[truncated by hfss-agent: {omitted} characters omitted]"


def sanitize_str(value: str) -> str:
    """Strip control characters (keeping tab/newline), then length-cap.

    An over-length string is truncated AND visibly marked, so a cut string never
    reads as complete — reporting incomplete data as complete would be a false
    statement by omission. The marker replaces enough trailing content to keep
    the whole result within ``MAX_UNTRUSTED_STR_LEN`` (the cap stays a hard
    bound). An under-length string is returned byte-for-byte unchanged.
    """
    stripped = "".join(
        ch for ch in value if ch in _KEEP_CONTROL or unicodedata.category(ch) != "Cc"
    )
    if len(stripped) <= MAX_UNTRUSTED_STR_LEN:
        return stripped
    # Reserve marker room using the largest possible count (the whole stripped
    # length); the actual count is <= that, so its marker is never longer — the
    # total lands at or under the cap, never over it.
    reserved = len(_truncation_marker(len(stripped)))
    keep = MAX_UNTRUSTED_STR_LEN - reserved
    omitted = len(stripped) - keep
    return stripped[:keep] + _truncation_marker(omitted)


def sanitize_result(value: Any) -> Any:
    """Recursively return ``value`` with every contained string sanitized.

    Handles the shapes an adapter operation returns — a contract ``BaseModel``, a
    list of them, a dict keyed by section name, and the adapter-domain outcome
    dataclasses — plus strings nested anywhere inside (including free-form
    ``InspectionSection.data`` and dict keys). Non-string leaves (numbers,
    datetimes, bools, ``None``) pass through untouched.

    Because ``UntrustedStr`` is a plain ``str`` alias, there is no runtime marker
    distinguishing untrusted from wrapper-owned strings; sanitizing every string
    is the conservative, structural choice, and it is safe — stripping control
    characters and capping length is harmless to a legitimate path or version.
    """
    if isinstance(value, str):
        return sanitize_str(value)
    if isinstance(value, BaseModel):
        # model_dump flattens nested models to plain data; sanitize that, then
        # re-validate so the result is the same type and still schema-valid.
        return type(value).model_validate(
            sanitize_result(value.model_dump(mode="python"))
        )
    if is_dataclass(value) and not isinstance(value, type):
        return replace(
            value,
            **{f.name: sanitize_result(getattr(value, f.name)) for f in fields(value)},
        )
    if isinstance(value, Mapping):
        return {sanitize_result(k): sanitize_result(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(sanitize_result(item) for item in value)
    return value
