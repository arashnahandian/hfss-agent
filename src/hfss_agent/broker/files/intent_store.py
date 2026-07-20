"""Design-intent persistence (W-4; plan §6, decisions 3-4): a broker-owned
envelope over the atomic write primitive.

THE ON-DISK FORMAT IS BROKER-OWNED, NOT A CONTRACT SCHEMA — only the returned
``DesignIntentState`` is contract-pinned, so the envelope can carry more than
the ``IntentObject`` without touching the pinned contract (decision 4): a
format marker (so a future envelope change is detectable rather than guessed
at), the intent itself, and the SELECTION CHAIN AS IT STOOD WHEN THE ENVELOPE
WAS WRITTEN. Surfacing that set-time chain at read time is what makes an
intent set under design A and read under design B visibly a cross-design read
— closing the stale-evidence path where a later compute_metrics would
interpret B's numbers against A's target.

Write semantics:
  * SET replaces the current intent atomically. No overwrite guard applies —
    replacing the intent IS the tool's stated action, so this is not an ADR-8
    exemption: the guard exists to prevent SILENT overwrites, and nothing
    here is silent.
  * CLEAR is a TOMBSTONE: the cleared state is written atomically in place;
    nothing is deleted. Keeping every delete primitive out of the file layer
    keeps "no deletion path exists anywhere in this codebase" a STRUCTURAL
    claim provable by AST audit, rather than "no deletion except here",
    which a reader must verify by hand. The predecessor project silently
    deleted designs; that guarantee is worth one stray file on disk.
  * GET: a missing file is the honest first-class "not set" state, never an
    error. Corrupt JSON or an unrecognized envelope raises a loud, typed
    ``BrokerFileError`` — never papered over.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from hfss_agent.broker.files.errors import BrokerFileError
from hfss_agent.broker.files.writes import atomic_replace_write
from hfss_agent.contract import IntentObject
from hfss_agent.contract.tool_io import SelectionChain

_FORMAT_MARKER = "hfss-agent/intent-envelope-v1"


class IntentEnvelope(BaseModel):
    """The broker-owned on-disk shape. Deliberately NOT a contract
    ``StrictModel`` subclass: nothing here is contract-pinned, and reusing
    the contract base would blur exactly the boundary decision 4 draws.
    ``extra="forbid"`` and a required format marker mean an unrecognized file
    is an invalid envelope surfaced loudly, never silently absorbed."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["hfss-agent/intent-envelope-v1"]
    intent: IntentObject | None
    selection_at_write: SelectionChain


class IntentStore:
    """Persistence over one intent file. The path is constructor-injected —
    tests pass a pytest ``tmp_path``; Step 2.8 composes with
    ``locations.default_intent_path()`` (plan §6e)."""

    def __init__(self, path: str) -> None:
        self._path = path

    @property
    def path(self) -> str:
        return self._path

    def write(self, intent: IntentObject | None, selection: SelectionChain) -> None:
        """Atomically persist ``intent`` (None = the CLEAR tombstone) together
        with the selection chain as it stands now (module docstring)."""
        envelope = IntentEnvelope(
            format=_FORMAT_MARKER, intent=intent, selection_at_write=selection
        )
        atomic_replace_write(self._path, envelope.model_dump_json(indent=2) + "\n")

    def read(self) -> IntentEnvelope | None:
        """The persisted envelope, or None when no file exists (the honest
        "not set" state). Raises ``BrokerFileError`` for an unreadable,
        corrupt, or unrecognized file."""
        try:
            with open(self._path, encoding="utf-8") as handle:
                raw = handle.read()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise BrokerFileError(
                self._path,
                f"the intent file could not be read: {type(exc).__name__}: {exc}",
            ) from exc
        try:
            return IntentEnvelope.model_validate_json(raw)
        except ValidationError as exc:
            raise BrokerFileError(
                self._path,
                "the intent file is corrupt or not a recognized intent "
                f"envelope ({exc.error_count()} validation error(s)); it was "
                "not modified — fix or replace it via set_design_intent",
            ) from exc
