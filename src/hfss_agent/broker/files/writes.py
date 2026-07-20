"""The broker's write primitives — the ONLY open()-for-write call sites in
the repo (W-4; ADR-8).

Two primitives, two guarantees:

* ``exclusive_create_write`` (the ``overwrite=False`` path): ``open(path,
  "x")`` makes the existence check and the claim ONE kernel-atomic operation,
  so no TOCTOU window exists between them. ``FileExistsError`` propagates to
  the caller, which maps it to the typed refusal (no silent overwrite,
  ADR-8). Documented limitation: a crash mid-write can leave a partial file
  at the requested path — acceptable because that path held nothing before.

* ``atomic_replace_write`` (the intent file and the ``overwrite=True`` export
  path): temp-then-``os.replace``. ``os.replace`` is the required call — it
  replaces atomically on BOTH platforms, where the non-replacing sibling
  raises ``FileExistsError`` on Windows when the destination exists. The temp
  is created via ``tempfile.mkstemp`` IN THE SAME DIRECTORY AS THE TARGET
  (atomic replacement requires the same volume), so temps sit beside their
  target: the broker's data directory for the intent file, the USER'S OWN
  directory for an overwrite-export (ADR-19 correction). On failure the temp
  is LEFT IN PLACE — no deletion primitive exists anywhere in this codebase
  (plan decision 3), and the alternatives (tearing the user's pre-existing
  file, or reintroducing deletion) are both worse — and the typed error NAMES
  the orphan so the leftover is never silent. A fresh ``mkstemp`` name per
  write means orphans never collide and are never re-read.

Encoding/newline policy (plan §6d): every text open passes
``encoding="utf-8"`` and every text write passes ``newline="\\n"``, so
``os.linesep`` translation cannot make output byte-different between the
windows-latest and ubuntu-latest CI legs. Binary payloads use ``"xb"`` /
``"wb"``. Operational failures (permissions, disk full, a path past an
un-opted-out MAX_PATH) surface as ``BrokerFileError`` naming the cause —
never a raw ``OSError`` traceback.
"""

from __future__ import annotations

import os
import tempfile

from hfss_agent.broker.files.errors import BrokerFileError


def _payload_size(payload: str | bytes) -> int:
    """True on-disk byte count: UTF-8 length for text (no newline translation
    happens under ``newline="\\n"``), raw length for bytes."""
    return len(payload.encode()) if isinstance(payload, str) else len(payload)


def exclusive_create_write(path: str, payload: str | bytes) -> int:
    """Create ``path`` — which must not exist — and write ``payload``;
    returns the bytes written.

    Raises ``FileExistsError`` when the path already exists (the kernel-atomic
    ADR-8 refusal signal; the caller maps it to the typed refusal and never
    swallows it) and ``BrokerFileError`` for any other failure.
    """
    try:
        if isinstance(payload, str):
            with open(path, "x", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
        else:
            with open(path, "xb") as handle:
                handle.write(payload)
    except FileExistsError:
        raise
    except OSError as exc:
        raise BrokerFileError(
            path, f"the file could not be created: {type(exc).__name__}: {exc}"
        ) from exc
    return _payload_size(payload)


def atomic_replace_write(path: str, payload: str | bytes) -> int:
    """Write ``payload`` to ``path`` atomically (temp-then-replace); returns
    the bytes written. The target is either fully replaced or untouched —
    never torn.

    Raises ``BrokerFileError`` on failure. If the temp file had already been
    created it is left in place and NAMED in the error (module docstring):
    for an overwrite-export that orphan sits in the user's own directory.
    """
    directory = os.path.dirname(path)
    prefix = os.path.basename(path) + "."
    try:
        fd, temp_path = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=directory)
    except OSError as exc:
        raise BrokerFileError(
            path,
            "no temporary file could be created beside the target: "
            f"{type(exc).__name__}: {exc}",
        ) from exc
    try:
        if isinstance(payload, str):
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                # fsync BEFORE the replace: the replace must never promote a
                # temp whose bytes are still only in the OS write cache.
                os.fsync(handle.fileno())
        else:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception as exc:
        # Catch Exception, NOT BaseException (the ADR-17 decision 4 watchdog
        # precedent): KeyboardInterrupt and SystemExit are never reclassified
        # as broker file errors, so Ctrl-C during a write behaves like Ctrl-C.
        # The breadth matters: a non-OSError failure between mkstemp and the
        # replace — e.g. a lone surrogate in an untrusted HFSS-sourced chain
        # name making handle.write raise UnicodeEncodeError, a ValueError —
        # would otherwise orphan the temp WITHOUT naming it, the exact silent
        # leftover the ADR-19 correction exists to prevent.
        raise BrokerFileError(
            path,
            f"the write did not complete: {type(exc).__name__}: {exc}",
            orphaned_temp=temp_path,
        ) from exc
    return _payload_size(payload)
