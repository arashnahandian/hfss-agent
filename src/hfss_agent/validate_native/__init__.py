"""W-6 · validate_native — native HFSS validation passthrough.

Runs HFSS's own ValidateDesign via the adapter and returns its MESSAGES — not
findings — in a ``NativeValidationBlock``: the adapter's ``NativeValidation``
(whose ``source`` literal is the attribution, fixed at ``hfss_native``) paired
with a ``NativeValidationProvenance`` for the run. A native message is not a
``Finding`` and W-6 builds none (ADR-23): we own no rule id, rule version,
calculation, or machine-checked applicability behind an Ansys validator
message, so carrying one as a Finding would mean faking most of that schema.

Does not rephrase, filter, rank, or judge the messages, and does not read
inside them. "Always presented first" is no longer a behaviour this module
maintains: ``ValidationReport`` declares its native block ahead of
``findings``, so the ordering is a property of the serialized artifact rather
than a sort a producer must remember to apply.

What passes through is HFSS's output AS SANITIZED at the capability boundary
(ADR-9) — see ``NativeValidationBlock`` for exactly what that does and does not
guarantee.

The assembly itself lives in ``assembler``; see that module's docstring for the
three-name split (entry point / capability / tool), the dispatch order, the
provenance sources, the residual honesty gap, and why ``template_text`` is a
function here rather than a field on W-6's output.
"""

from hfss_agent.validate_native.assembler import (
    NativeValidationAssemblyError,
    native_template_text,
    validate_native,
)

__all__ = [
    "validate_native",
    "native_template_text",
    "NativeValidationAssemblyError",
]
