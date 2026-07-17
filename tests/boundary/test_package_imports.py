"""Boundary smoke test: the package tree imports cleanly.

Placeholder until Step 1.1 adds real boundary-suite coverage. Keeps the CI
pytest step honest — it exercises something real (a clean import) rather
than suppressing pytest's "no tests collected" exit code.
"""

import hfss_agent


def test_package_imports() -> None:
    assert hfss_agent is not None
