"""broker/files — all file I/O for both units.

Exports refuse existing paths without explicit ``overwrite=true``; the intent
file is written atomically (temp-then-rename); write paths are never derived from
HFSS-sourced strings (ADR-8, ADR-9).
"""
