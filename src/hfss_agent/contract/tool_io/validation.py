"""Validation tool I/O (§3): validate_setup."""

from hfss_agent.contract.common import StrictModel
from hfss_agent.contract.finding import Finding
from hfss_agent.contract.tool_io.common import CannotEvaluate, EngineStatus


class ValidationReport(StrictModel):
    """validate_setup response (§3, W-6/W-10): native findings first, then engine
    findings if the engine is present; with the engine absent, native findings
    plus an explicit engine_absent notice — graceful degradation, never a silent
    gap.

    Reuses Finding for every entry (``source`` attributes native vs gate vs
    engine_rule). The only new element is ``engine_status``, the explicit
    present/absent notice.
    """

    findings: list[Finding]
    engine_status: EngineStatus
    template_text: str


class ValidateSetupRequest(StrictModel):
    include_supplemental: bool = True


ValidateSetupResult = ValidationReport | CannotEvaluate
