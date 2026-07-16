"""W-2 · session — AEDT session lifecycle and selection state.

Discovers and attaches (attach-only) to running AEDT processes; owns the
selection chain process -> project -> design -> setup -> sweep -> variation;
handles reconnect/crash/lost-session recovery; marks sessions suspect after an
abandoned stuck call (ADR-10).
"""
