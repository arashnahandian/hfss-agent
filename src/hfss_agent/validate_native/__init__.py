"""W-6 · validate_native — native HFSS validation passthrough.

Runs HFSS's own ValidateDesign via the adapter and returns its findings
verbatim-with-attribution (source: ``hfss_native``), always presented first. Does
not rephrase, filter, or rank native findings.
"""
