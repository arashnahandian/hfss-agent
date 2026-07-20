"""broker/files — all file I/O for both units.

Exports refuse existing paths without explicit ``overwrite=true``; the intent
file is written atomically (temp-then-replace); write paths are never derived
from HFSS-sourced strings (ADR-8, ADR-9). Temporary files sit BESIDE their
target — atomic replacement requires the same volume — which is the broker's
data directory for the intent file and the USER'S export directory for an
overwrite-export; a failed write leaves its temp in place (no deletion
primitive exists anywhere in this codebase, plan decision 3) and the typed
error names the orphan so it is never silent (ADR-19).
"""

from hfss_agent.broker.files.errors import BrokerFileError
from hfss_agent.broker.files.intent_store import IntentEnvelope, IntentStore
from hfss_agent.broker.files.locations import (
    default_audit_log_path,
    default_data_dir,
    default_intent_path,
    ensure_data_dir,
)
from hfss_agent.broker.files.paths import validate_export_path
from hfss_agent.broker.files.writes import atomic_replace_write, exclusive_create_write

__all__ = [
    "BrokerFileError",
    "IntentEnvelope",
    "IntentStore",
    "atomic_replace_write",
    "default_audit_log_path",
    "default_data_dir",
    "default_intent_path",
    "ensure_data_dir",
    "exclusive_create_write",
    "validate_export_path",
]
