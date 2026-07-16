"""W-10 · findings — receipt validation, attribution, sanitization.

Validates every finding the engine returns against the seven-field findings
schema and rejects malformed or evidence-incomplete findings as protocol errors;
merges native, gate, and supplemental findings with per-finding source
attribution; applies the untrusted-string envelope to every HFSS-sourced string.
"""
