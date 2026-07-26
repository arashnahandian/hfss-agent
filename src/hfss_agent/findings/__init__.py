"""W-10 · findings — receipt validation, attribution, sanitization.

Validates every finding the engine returns against the seven-field findings
schema and rejects malformed or evidence-incomplete findings as protocol
errors; merges gate and engine findings with per-finding source attribution;
applies the untrusted-string envelope to every HFSS-sourced string.

Native HFSS validation does NOT pass through here (ADR-23). It is not a
``Finding``, it never enters the merge, and W-6 delivers it as its own
structural block. That is what makes the rejection gate above UNCONDITIONAL
rather than a check with a native-shaped hole in it: there is no source for
which the seven-field requirement could be relaxed, so there is no branch to
write and none to forget.
"""
