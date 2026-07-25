"""W-5 · inspect — Journey 1.1: full structured design read-out.

Project, design, solution type, units, variables, objects, materials, boundaries,
excitations/ports, setups, sweeps, available results — each section carrying a
``read_status`` (ok / not_readable, with the exact PyAEDT limitation named). Does
not judge or validate anything it reads.

The assembly itself lives in ``assembler``; see that module's docstring for the
dispatch order, the provenance sources, and the one residual honesty gap.
"""

from hfss_agent.inspect.assembler import InspectionAssemblyError, inspect_design

__all__ = [
    "inspect_design",
    "InspectionAssemblyError",
]
