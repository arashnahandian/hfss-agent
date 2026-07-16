"""hfss-agent — open capability wrapper for a verification-first HFSS MCP agent.

The sole component capable of touching HFSS, project files, the network, or the
OS. Emits a versioned, read-only design snapshot to the optional closed engine
and works standalone when the engine is absent. See System Design §1.1.
"""
